import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { ThreeMFLoader } from 'three/examples/jsm/loaders/3MFLoader.js';
import { DRACOLoader } from 'three/examples/jsm/loaders/DRACOLoader.js';
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader.js';
import { BELT_PRINTER_PREVIEW_MARGIN_MM, BELT_PRINTER_PREVIEW_MARGIN_MM_WITH_SUPPORT, type BedSize, type Dimensions } from '../dimensions';
import type { ColorNode } from '../types';

interface ViewerProps {
	file: File | null;
	onDimensions?: (dims: Dimensions | null) => void;
	bedSize?: BedSize | null;
	// Per-object/part colors for a .3mf, in the exact tree shape 3MFLoader
	// itself builds (see api/app/threemf.py) -- applied by walking the
	// loaded Group in lockstep with this tree. Ignored for STL/DRC (which
	// never produce a Group) or when empty/absent, in which case every mesh
	// gets the same flat default color as before this existed.
	colorTree?: ColorNode[];
	// The last successful job's total filament weight (api/app/gcode_stats.py),
	// shown as a small badge over the model -- null/undefined hides it (no
	// successful job yet, or it didn't report one).
	filamentUsedGrams?: number | null;
	// Mirrors QuickSettings' enable_support toggle -- the belt placement
	// margin below only needs to be wide when support material is enabled
	// (see BELT_PRINTER_PREVIEW_MARGIN_MM_WITH_SUPPORT); this keeps the
	// preview consistent with the same enable_support-conditioned margin the
	// slicer itself now uses (vendor/orcaslicer/src/OrcaSlicer.cpp).
	supportEnabled?: boolean;
	// .3mf only: indices of build items (see ObjectInfo.index) the user chose
	// not to print. They stay visible but dimmed, so it is clear what is left
	// out. Ignored for anything but a .3mf Group.
	excludedObjects?: number[];
	// Where the model's footprint centre sits on the plate (plate coordinates,
	// see BedSize.minX/minY); null/undefined = the slicer's default spot. Needs
	// bedSize; moving it never rebuilds the scene.
	placement?: { x: number; y: number } | null;
	// .3mf only: show just these objects (indices as in ObjectInfo.index), centred
	// on the bed, and report their size -- used to preview one plate of a
	// multi-plate file. null/undefined shows everything.
	shownObjects?: number[] | null;
	// .3mf on a belt printer that lines objects up: where each kept object goes (a move from its place in
	// the file, by object index; see beltLayout.ts). Objects without an entry are not printed and are hidden.
	rowShifts?: Record<number, { dx: number; dy: number }> | null;
	// .3mf with more than one object: called after each load with one small
	// rendered picture (a data: URL) per build item, keyed by index, for the
	// object picker. Must be a stable reference (it is an effect dependency).
	onObjectThumbnails?: (thumbnails: Record<number, string>) => void;
}

export interface ViewerHandle {
	// A snapshot of whatever this viewer is currently showing (the exact
	// colors/nozzle assignment the user has configured), as a data: URL --
	// used to embed a real preview into the sliced gcode and this app's own
	// job thumbnail, since the OrcaSlicer CLI itself never generates one (see
	// api/app/gcode_thumbnail.py). null if nothing's loaded yet or the
	// capture fails for any reason -- best-effort, never blocks slicing.
	capturePreview: () => string | null;
}

const CAPTURE_SIZE = 512;
// The model's furthest corner reaches 88% of the square capture frame,
// leaving a small margin so anti-aliased edges aren't clipped -- chosen
// by comparing several options directly against the real bee model.
const FRAME_FILL = 0.88;

// The box's eight corners as pixels of the square capture frame, and the rectangle they cover.
function projectedExtent(box: THREE.Box3, camera: THREE.Camera) {
	let minPx = Infinity;
	let maxPx = -Infinity;
	let minPy = Infinity;
	let maxPy = -Infinity;
	for (const x of [box.min.x, box.max.x]) {
		for (const y of [box.min.y, box.max.y]) {
			for (const z of [box.min.z, box.max.z]) {
				const ndc = new THREE.Vector3(x, y, z).project(camera);
				const px = (ndc.x * 0.5 + 0.5) * CAPTURE_SIZE;
				// NDC's +y is up; pixel space's +y is down.
				const py = (1 - (ndc.y * 0.5 + 0.5)) * CAPTURE_SIZE;
				minPx = Math.min(minPx, px);
				maxPx = Math.max(maxPx, px);
				minPy = Math.min(minPy, py);
				maxPy = Math.max(maxPy, py);
			}
		}
	}
	return { minPx, maxPx, minPy, maxPy };
}

// Hides an object and returns what puts it back as it was.
function hideTemporarily(object: THREE.Object3D | null): () => void {
	if (!object) return () => undefined;
	const was = object.visible;
	object.visible = false;
	return () => {
		object.visible = was;
	};
}

// The canvas as a PNG, or null when the browser will not give one.
function canvasPng(canvas: HTMLCanvasElement): string | null {
	try {
		return canvas.toDataURL('image/png');
	} catch {
		return null;
	}
}

interface LiveScene {
	renderer: THREE.WebGLRenderer;
	scene: THREE.Scene;
	camera: THREE.PerspectiveCamera;
	controls: OrbitControls;
	plate: THREE.Mesh | null;
	ceiling: THREE.Mesh | null;
	modelBox: THREE.Box3 | null;
}

// A square picture cropped tight to the model, then everything put back before the next paint.
function captureModelSquare(live: LiveScene & { modelBox: THREE.Box3 }, canvas: HTMLCanvasElement): string | null {
	const { renderer, scene, camera, plate, ceiling, modelBox } = live;
	const restorePlate = hideTemporarily(plate);
	const restoreCeiling = hideTemporarily(ceiling);
	const savedAspect = camera.aspect;
	const savedSize = renderer.getSize(new THREE.Vector2());
	try {
		renderer.setSize(CAPTURE_SIZE, CAPTURE_SIZE, false);
		camera.aspect = 1;
		camera.updateProjectionMatrix();
		const { minPx, maxPx, minPy, maxPy } = projectedExtent(modelBox, camera);
		const bboxCx = (minPx + maxPx) / 2;
		const bboxCy = (minPy + maxPy) / 2;
		// A single half-extent, big enough to cover whichever axis needs
		// more room -- keeps the crop window perfectly square so there's
		// no second crop needed downstream.
		const cropHalf = Math.max(maxPx - minPx, maxPy - minPy) / 2 / FRAME_FILL;
		camera.setViewOffset(CAPTURE_SIZE, CAPTURE_SIZE, bboxCx - cropHalf, bboxCy - cropHalf, cropHalf * 2, cropHalf * 2);
		camera.updateProjectionMatrix();
		renderer.render(scene, camera);
		return canvas.toDataURL('image/png');
	} catch {
		return null;
	} finally {
		camera.clearViewOffset();
		camera.aspect = savedAspect;
		restorePlate();
		restoreCeiling();
		camera.updateProjectionMatrix();
		renderer.setSize(savedSize.x, savedSize.y, false);
		renderer.render(scene, camera);
	}
}

// A copy of the geometry with one flat vertex colour per original triangle (null = the fallback colour).
function paintedGeometry(geometry: THREE.BufferGeometry, triangleColors: (string | null)[], fallbackHex: string): THREE.BufferGeometry {
	const nonIndexed = geometry.toNonIndexed();
	const colors = new Float32Array(nonIndexed.attributes.position.count * 3);
	const fallback = new THREE.Color(fallbackHex);
	const tmp = new THREE.Color();
	triangleColors.forEach((hex, i) => {
		const c = hex ? tmp.set(hex) : fallback;
		for (let vertex = 0; vertex < 3; vertex++) {
			const base = (i * 3 + vertex) * 3;
			colors[base] = c.r;
			colors[base + 1] = c.g;
			colors[base + 2] = c.b;
		}
	});
	nonIndexed.setAttribute('color', new THREE.BufferAttribute(colors, 3));
	return nonIndexed;
}

// One flat colour per original triangle of a mesh; a mesh whose triangle count does not match keeps the flat material.
function paintMesh(mesh: THREE.Mesh, baseColorHex: string | null, triangleColors: (string | null)[], flat: THREE.Material): void {
	const geometry = mesh.geometry;
	const faceCount = geometry.index ? geometry.index.count / 3 : geometry.attributes.position.count / 3;
	if (faceCount !== triangleColors.length) {
		// Shape mismatch -- bail to this mesh's flat default rather than
		// risk coloring the wrong faces.
		mesh.material = flat;
		return;
	}
	mesh.geometry = paintedGeometry(geometry, triangleColors, baseColorHex ?? '#ffffff');
	geometry.dispose();
	mesh.material = new THREE.MeshStandardMaterial({ vertexColors: true, metalness: 0.05, roughness: 0.55 });
}

// How far the model sits from the middle of the bed: where the user placed it, or the default a belt printer gives.
function placementOffset(
	bedSize: BedSize | null | undefined,
	wanted: { x: number; y: number } | null | undefined,
	plate: { w: number; d: number },
	supportEnabled: boolean | undefined,
	rowDepth: number | null,
): { x: number; y: number } {
	if (bedSize && wanted) {
		return { x: wanted.x - bedSize.minX - plate.w / 2, y: wanted.y - bedSize.minY - plate.d / 2 };
	}
	if (bedSize?.beltPrinterInfiniteY) {
		const margin = supportEnabled ? BELT_PRINTER_PREVIEW_MARGIN_MM_WITH_SUPPORT : BELT_PRINTER_PREVIEW_MARGIN_MM;
		// A lined-up row starts at the belt's start; a lone object is centred near it.
		return { x: 0, y: -plate.d / 2 + margin + (rowDepth !== null ? rowDepth / 2 : 0) };
	}
	return { x: 0, y: 0 };
}

const THUMBNAIL_SIZE = 160;

// One object drawn from a three-quarter view onto the thumbnail renderer, or null for an empty object.
function renderThumbnail(
	renderer: THREE.WebGLRenderer,
	scene: THREE.Scene,
	camera: THREE.PerspectiveCamera,
	item: THREE.Object3D,
): string | null {
	const clone = item.clone(true);
	scene.add(clone);
	try {
		clone.updateMatrixWorld(true);
		const box = new THREE.Box3().setFromObject(clone);
		if (box.isEmpty()) return null;
		const center = box.getCenter(new THREE.Vector3());
		const radius = Math.max(box.getSize(new THREE.Vector3()).length() / 2, 0.001);
		const distance = (radius / Math.sin(THREE.MathUtils.degToRad(35 / 2))) * 1.05;
		camera.position.copy(center).addScaledVector(new THREE.Vector3(1, -1, 0.8).normalize(), distance);
		camera.lookAt(center);
		camera.near = Math.max(distance - radius * 2, 0.01);
		camera.far = distance + radius * 2;
		camera.updateProjectionMatrix();
		renderer.render(scene, camera);
		return renderer.domElement.toDataURL('image/png');
	} finally {
		scene.remove(clone);
	}
}

// Show the chosen objects of a file and hide the rest, moving each kept object by its row shift.
function arrangeShown(
	group: THREE.Object3D,
	starts: THREE.Vector3[],
	shown: Set<number> | null,
	rowShifts: Record<number, { dx: number; dy: number }> | null | undefined,
): void {
	group.children.forEach((item, i) => {
		// A lined-up row moves each kept object; the others are not printed, so they are not shown.
		const start = starts[i];
		if (start) {
			item.position.copy(start);
			const shift = rowShifts?.[i];
			if (shift) {
				item.position.x += shift.dx;
				item.position.y += shift.dy;
			}
		}
		item.visible = (shown === null || shown.has(i)) && (!rowShifts || rowShifts[i] !== undefined);
	});
}

// The box around what is visible, measured with the group at the origin.
function visibleBox(group: THREE.Object3D): THREE.Box3 {
	const saved = group.position.clone();
	group.position.set(0, 0, 0);
	group.updateMatrixWorld(true);
	const box = new THREE.Box3();
	for (const item of group.children) if (item.visible) box.expandByObject(item, true);
	group.position.copy(saved);
	group.updateMatrixWorld(true);
	return box;
}

// Swap in the dim material on excluded objects and put the original back on the rest.
function dimExcluded(group: THREE.Object3D, excluded: Set<number>, dim: THREE.Material): void {
	group.children.forEach((item, i) => {
		item.traverse((node) => {
			if (!(node instanceof THREE.Mesh)) return;
			if (!excluded.has(i)) {
				if (node.userData.origMaterial) {
					node.material = node.userData.origMaterial;
					delete node.userData.origMaterial;
				}
			} else if (!node.userData.origMaterial) {
				node.userData.origMaterial = node.material;
				node.material = dim;
			}
		});
	});
}

// Basic model preview: not meant to be a full slicer viewport (no layer
// preview, no plate/gizmos) -- just enough to confirm "yes, that's the
// object I uploaded" before slicing. Drag-to-rotate/zoom via OrbitControls
// comes along for free with three.js and costs nothing extra, but nothing
// here depends on interaction actually happening.
const Viewer = forwardRef<ViewerHandle, ViewerProps>(function Viewer(
	{
		file,
		onDimensions,
		bedSize,
		colorTree,
		filamentUsedGrams,
		supportEnabled,
		excludedObjects,
		onObjectThumbnails,
		placement,
		shownObjects,
		rowShifts,
	},
	ref,
) {
	const containerRef = useRef<HTMLDivElement>(null);
	// Set to the live renderer's canvas each time the effect below (re)creates
	// one, and cleared on teardown -- capturePreview reads through this
	// rather than closing over a specific renderer instance, since the whole
	// scene gets recreated on every file/colorTree change.
	const canvasRef = useRef<HTMLCanvasElement | null>(null);
	// Everything capturePreview needs to temporarily re-frame the shot around
	// just the model (see below) -- populated once finishLoad knows the
	// model's own bounds, cleared on teardown alongside canvasRef.
	const liveRef = useRef<LiveScene | null>(null);
	useImperativeHandle(ref, () => {
		// The interactive view frames the model's bounding SPHERE (a
		// deliberately loose, orientation-independent fit, see finishLoad
		// below) in whatever (usually non-square) aspect ratio the viewer
		// panel happens to be, and always shows the reference plate/ceiling --
		// both sized for a big multi-material bed, they're mostly empty space
		// around a typical print. A gcode thumbnail is tiny (48x48 on a
		// printer's own screen), always square, and has no use for that
		// context, so this temporarily hides the plate/ceiling, renders into a
		// SQUARE capture buffer instead of the panel's own aspect (cropping
		// tight to the model in a non-square frame first and then
		// center-square-cropping afterward double-crops -- confirmed: an
		// asymmetric shape, like a part with wings extending past one side of
		// its own bounding box, got clipped by that second crop even though it
		// fit the first one), and uses setViewOffset (a "virtual sensor crop"
		// -- no camera movement, so it can't perturb OrbitControls' own state)
		// centered on the model's OWN projected bounding box rather than the
		// frame's center, then restores everything before the next paint --
		// synchronous, so the live view never actually flashes any of this.
		const capturePreview = (): string | null => {
			const canvas = canvasRef.current;
			const live = liveRef.current;
			if (!canvas) return null;
			if (!live?.modelBox) return canvasPng(canvas);
			return captureModelSquare({ ...live, modelBox: live.modelBox }, canvas);
		};
		return { capturePreview };
	}, []);
	// Geometry loading (a fresh .3mf/.stl/.drc) and per-triangle color
	// application (toNonIndexed() + a fresh vertex-color buffer per painted
	// mesh, see applyTriangleColors below) can both take a noticeable moment
	// on a large model -- this whole effect re-runs on every colorTree change
	// too (a nozzle reassignment), re-fetching and re-parsing the file from
	// scratch, not just recoloring in place. Surfaced as a loading overlay
	// rather than left silent so a slow model/reassignment doesn't look hung.
	const [isRendering, setIsRendering] = useState(false);
	// The loaded .3mf Group (null for STL/DRC), plus a counter bumped on every
	// load so the dimming effect below re-applies after the scene is rebuilt.
	const loadedGroupRef = useRef<THREE.Group | null>(null);
	const dimMaterialRef = useRef<THREE.MeshStandardMaterial | null>(null);
	const [loadVersion, setLoadVersion] = useState(0);
	// The latest requested placement, and a function (set up by the scene
	// effect) that moves the loaded model to it.
	const placementRef = useRef(placement);
	const placeRef = useRef<(() => void) | null>(null);
	// Where the loaded model sits (before the placement offset) when centred on
	// the origin -- the whole scene, or just the shown objects of a plate.
	const centeredRef = useRef<THREE.Vector3 | null>(null);
	// Each object's own place in the file (before any row shift), and how deep the lined-up row is.
	const baseChildPos = useRef<THREE.Vector3[]>([]);
	const rowDepthRef = useRef<number | null>(null);
	const onDimensionsRef = useRef(onDimensions);
	useEffect(() => {
		onDimensionsRef.current = onDimensions;
	}, [onDimensions]);
	// Declared before the scene effect on purpose: effects run in order, and a
	// freshly built scene must see the placement of this very render.
	useEffect(() => {
		placementRef.current = placement;
	}, [placement]);

	useEffect(() => {
		const container = containerRef.current;
		if (!container) return;

		setIsRendering(!!file);

		// Cleared immediately on a new/removed file so stale dimensions from a
		// previous model don't linger in the UI while the new one loads.
		onDimensions?.(null);

		const scene = new THREE.Scene();
		scene.background = new THREE.Color(0x2a2e35);

		const camera = new THREE.PerspectiveCamera(45, container.clientWidth / container.clientHeight, 0.1, 10000);
		// STL/print convention is Z-up (Z = build height, model sits on the
		// plate at its minimum Z), not three.js's default Y-up -- without this,
		// an asymmetric model renders lying on its side. Must be set before
		// OrbitControls is constructed, which reads it to orient orbiting.
		camera.up.set(0, 0, 1);

		// preserveDrawingBuffer: capturePreview() (above) reads this canvas via
		// toDataURL() on demand -- e.g. when the user clicks Slice, not right
		// after a render call -- and without this the buffer can already be
		// cleared by then.
		const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
		renderer.setPixelRatio(window.devicePixelRatio);
		renderer.setSize(container.clientWidth, container.clientHeight);
		container.appendChild(renderer.domElement);
		canvasRef.current = renderer.domElement;

		scene.add(new THREE.AmbientLight(0xffffff, 0.6));
		const key = new THREE.DirectionalLight(0xffffff, 0.8);
		key.position.set(1, 1, 1);
		scene.add(key);
		const fill = new THREE.DirectionalLight(0xffffff, 0.4);
		fill.position.set(-1, -0.5, -1);
		scene.add(fill);

		const controls = new OrbitControls(camera, renderer.domElement);
		controls.enableDamping = true;

		liveRef.current = { renderer, scene, camera, controls, plate: null, ceiling: null, modelBox: null };

		// Not meant to be a single mesh/geometry across both loader paths:
		// STLLoader yields one BufferGeometry -> one Mesh, but 3MFLoader.parse()
		// yields a THREE.Group of meshes (one per object in the file) -- this
		// holds whichever one is currently loaded so the cleanup effect below
		// has one place to traverse-and-dispose regardless of which it is.
		let loadedObject: THREE.Object3D | null = null;
		let plate: THREE.Mesh | null = null;
		let ceiling: THREE.Mesh | null = null;
		let animationId = 0;
		let disposed = false;
		// Only instantiated for a .drc file (below) -- holds a worker pool that
		// needs explicit disposal, unlike the other loaders here.
		let dracoLoader: DRACOLoader | null = null;

		// A muted blue-gray blended into the dark background too easily. A
		// saturated, warm color (like a printed-plastic filament) reads clearly
		// against the dark viewport at any lighting angle. Shared across every
		// mesh in a .3mf's group too -- this is a geometry-only preview, not a
		// render of the file's own embedded per-object colors/materials.
		const material = new THREE.MeshStandardMaterial({
			color: 0xff6f2c,
			metalness: 0.05,
			roughness: 0.55,
		});

		// Auto-frame the model at the origin, size the reference plate/ceiling,
		// and report dimensions -- identical for both loader paths once each
		// has centered its own object and handed over its world-space box.
		const finishLoad = (object: THREE.Object3D, box: THREE.Box3) => {
			const center = new THREE.Vector3();
			box.getCenter(center);
			object.position.sub(center);

			const size = new THREE.Vector3();
			box.getSize(size);

			// A reference plate just under the model: the selected printer's
			// actual bed size once one is picked (bedSize), or just wider than
			// the model's own footprint before that -- "roughly where the build
			// surface is" rather than nothing at all.
			const plateMargin = 1.3;
			const plateWidth = bedSize?.width ?? size.x * plateMargin;
			const plateDepth = bedSize?.depth ?? size.y * plateMargin;
			const plateZ = -size.z / 2;

			// A belt printer's own slicer default (see OrcaSlicer.cpp's
			// center_instances_around_point recenter) puts a fresh object near
			// the belt's Y origin -- where the prime lines/purge blob live, close
			// enough to help first-layer adhesion -- NOT at the middle of its own
			// deliberately very long bed. The plate mesh below is already built
			// at the real bed size, so without this the model would sit at its
			// geometric center, which for a 2000mm belt bed is nowhere near
			// where it will actually print. `plate` spans [-depth/2, +depth/2]
			// in scene Y around this same object, so the belt's own Y origin is
			// at scene Y = -plateDepth / 2, regardless of the profile's own
			// absolute min-Y coordinate.
			// The user's own placement (Position panel) wins over that default;
			// both are applied by placeModel, which also runs when only the
			// placement changes.
			centeredRef.current = object.position.clone();
			const modelCenter = new THREE.Vector3(0, 0, 0);
			const placeModel = () => {
				const { x: offsetX, y: offsetY } = placementOffset(
					bedSize,
					placementRef.current,
					{ w: plateWidth, d: plateDepth },
					supportEnabled,
					rowDepthRef.current,
				);
				const centered = centeredRef.current ?? object.position;
				object.position.set(centered.x + offsetX, centered.y + offsetY, centered.z);
				modelCenter.set(offsetX, offsetY, 0);
			};
			placeModel();
			placeRef.current = () => {
				placeModel();
				controls.target.copy(modelCenter);
			};

			// Auto-frame the model itself, regardless of the plate/ceiling size --
			// those are there to check against by zooming/orbiting out manually
			// if needed, not something the default view should reframe around (a
			// small model on a large-bed printer would otherwise auto-zoom out to
			// a barely-visible speck by default).
			const radius = size.length() / 2 || 1;
			const distance = radius / Math.sin((Math.PI * camera.fov) / 360);

			camera.position.set(modelCenter.x + distance, modelCenter.y + distance, modelCenter.z + distance * 0.6);
			camera.near = distance / 100;
			camera.far = distance * 100;
			camera.updateProjectionMatrix();
			controls.target.copy(modelCenter);
			controls.update();

			// FrontSide (the default) makes the plate a one-way surface:
			// PlaneGeometry's normal points along +Z (up) with no rotation
			// needed, so orbiting underneath looks at its back face, which isn't
			// rendered -- the plate disappears instead of blocking the view of
			// the model from below.
			plate = new THREE.Mesh(
				new THREE.PlaneGeometry(plateWidth, plateDepth),
				new THREE.MeshBasicMaterial({
					color: 0xaab0bb,
					transparent: true,
					opacity: 0.25,
					side: THREE.FrontSide,
				}),
			);
			plate.position.z = plateZ;
			scene.add(plate);

			// A second plane at the printer's max build height (only once a
			// printer -- and so a real bed size -- is selected): same footprint
			// as the bed, marking the ceiling of the printable volume. Not meant
			// to be visible by default (the camera stays framed on the model, per
			// above) -- just there to check against by zooming/orbiting out
			// manually. Rotated 180° so its normal points -Z (down): with the
			// camera framed on the model rather than the whole volume, it's
			// normally positioned below the ceiling looking up/across, so this is
			// the orientation that actually shows it on a manual zoom-out, the
			// mirror image of the bed plate facing up toward a camera that's
			// normally above it.
			if (bedSize) {
				ceiling = new THREE.Mesh(
					new THREE.PlaneGeometry(plateWidth, plateDepth),
					new THREE.MeshBasicMaterial({
						color: 0xaab0bb,
						transparent: true,
						opacity: 0.12,
						side: THREE.FrontSide,
					}),
				);
				ceiling.rotation.x = Math.PI;
				ceiling.position.z = plate.position.z + bedSize.height;
				scene.add(ceiling);
			}

			if (liveRef.current) {
				liveRef.current.plate = plate;
				liveRef.current.ceiling = ceiling;
				// Post-centering world box (object.position was just shifted above)
				// -- setFromObject updates the object's world matrix itself, so this
				// is accurate regardless of whether `box` above was local or world.
				liveRef.current.modelBox = new THREE.Box3().setFromObject(object, true);
			}

			onDimensions?.({ x: size.x, y: size.y, z: size.z });
		};

		// Colors a .3mf's loaded Group by walking it in lockstep with
		// colorTree, which mirrors 3MFLoader's own build order exactly (see
		// api/app/threemf.py) -- object3D.children[i] corresponds to
		// nodes[i] at every level, whether that's a top-level <build><item>
		// or a composite object's <components>. Bails to the flat default
		// color for a whole subtree the moment the shapes stop lining up
		// (wrong child count) rather than risk coloring the wrong mesh.
		const coloredMaterials = new Map<string, THREE.MeshStandardMaterial>();
		const materialForColor = (hex: string) => {
			const existing = coloredMaterials.get(hex);
			if (existing) return existing;
			const created = new THREE.MeshStandardMaterial({ color: hex, metalness: 0.05, roughness: 0.55 });
			coloredMaterials.set(hex, created);
			return created;
		};
		const applyFlatMaterial = (object3D: THREE.Object3D, mat: THREE.Material) => {
			object3D.traverse((child) => {
				if (child instanceof THREE.Mesh) child.material = mat;
			});
		};
		// Approximates a leaf's hand-painted per-triangle colors: one flat
		// color per ORIGINAL triangle (see api/app/threemf.py's
		// _representative_extruder), not a sub-triangle-accurate repaint --
		// good enough for "does the preview roughly look like the print".
		// Converts to non-indexed geometry (every face gets its own 3 unique
		// vertices) so each face can carry its own flat vertex color, since
		// the original indexed geometry shares vertices between faces.
		const applyTriangleColors = (object3D: THREE.Object3D, baseColorHex: string | null, triangleColors: (string | null)[]) => {
			const flat = baseColorHex ? materialForColor(baseColorHex) : material;
			object3D.traverse((child) => {
				if (child instanceof THREE.Mesh) paintMesh(child, baseColorHex, triangleColors, flat);
			});
		};
		const applyColorTree = (object3D: THREE.Object3D, nodes: ColorNode[]) => {
			const children = object3D.children;
			if (nodes.length !== children.length) {
				applyFlatMaterial(object3D, material);
				return;
			}
			children.forEach((child, i) => {
				const node = nodes[i];
				if (node.children.length > 0) {
					applyColorTree(child, node.children);
				} else if (node.triangle_colors && node.triangle_colors.length > 0) {
					applyTriangleColors(child, node.color, node.triangle_colors);
				} else {
					applyFlatMaterial(child, node.color ? materialForColor(node.color) : material);
				}
			});
		};

		// One small picture per top-level build item of a .3mf, for the object
		// picker. Clones share geometry/materials with the originals (cheap) and
		// are rendered one at a time on a short-lived second renderer, framed on
		// each object's own bounding sphere.
		const renderObjectThumbnails = (group: THREE.Group) => {
			const items = group.children;
			if (!onObjectThumbnails || items.length < 2) return;
			const thumbRenderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
			try {
				thumbRenderer.setPixelRatio(1);
				thumbRenderer.setSize(THUMBNAIL_SIZE, THUMBNAIL_SIZE);
				const thumbScene = new THREE.Scene();
				thumbScene.add(new THREE.AmbientLight(0xffffff, 0.6));
				const sun = new THREE.DirectionalLight(0xffffff, 1.1);
				sun.position.set(1, -1, 2);
				thumbScene.add(sun);
				const thumbCamera = new THREE.PerspectiveCamera(35, 1, 0.1, 100000);
				thumbCamera.up.set(0, 0, 1);
				const out: Record<number, string> = {};
				items.forEach((item, i) => {
					const png = renderThumbnail(thumbRenderer, thumbScene, thumbCamera, item);
					if (png !== null) out[i] = png;
				});
				if (!disposed) onObjectThumbnails(out);
			} catch (err) {
				console.error('Failed to render object thumbnails', err);
			} finally {
				thumbRenderer.dispose();
				thumbRenderer.forceContextLoss();
			}
		};

		if (file) {
			const url = URL.createObjectURL(file);
			const lowerName = file.name.toLowerCase();
			const isThreeMf = lowerName.endsWith('.3mf');
			const isDrc = lowerName.endsWith('.drc');

			// Shared by the STL and DRC branches below: both loaders hand back a
			// single BufferGeometry (unlike 3MFLoader's Group), so wrapping it in
			// a Mesh + edge outline + auto-frame is identical either way.
			const handleGeometry = (geometry: THREE.BufferGeometry) => {
				if (disposed) return;
				geometry.computeVertexNormals();
				geometry.computeBoundingBox();

				const mesh = new THREE.Mesh(geometry, material);
				scene.add(mesh);
				loadedObject = mesh;

				// Edge lines make flat-shaded faces read as a solid shape instead
				// of a smear of color, especially for simple/low-poly models.
				const edges = new THREE.LineSegments(
					new THREE.EdgesGeometry(geometry, 30),
					new THREE.LineBasicMaterial({ color: 0x2a1508, transparent: true, opacity: 0.5 }),
				);
				mesh.add(edges);

				finishLoad(mesh, geometry.boundingBox!);
				URL.revokeObjectURL(url);
				setIsRendering(false);
			};

			if (isThreeMf) {
				new ThreeMFLoader().load(
					url,
					(group) => {
						if (disposed) {
							URL.revokeObjectURL(url);
							return;
						}
						// Colors each object/part using colorTree when it's usable
						// (see applyColorTree above); otherwise every mesh gets the
						// same flat default color, same as before per-object color
						// support existed.
						if (colorTree && colorTree.length > 0) {
							applyColorTree(group, colorTree);
						} else {
							applyFlatMaterial(group, material);
						}
						scene.add(group);
						loadedObject = group;
						loadedGroupRef.current = group;
						baseChildPos.current = group.children.map((c) => c.position.clone());
						// Measured from the vertices: the quick box of a part turned by its own transform is bigger than the part, which
						// would put the plate below the model and leave it floating.
						finishLoad(group, new THREE.Box3().setFromObject(group, true));
						renderObjectThumbnails(group);
						setLoadVersion((n) => n + 1);
						URL.revokeObjectURL(url);
						setIsRendering(false);
					},
					undefined,
					(err) => {
						URL.revokeObjectURL(url);
						if (disposed) return;
						console.error('Failed to load 3MF for preview', err);
						setIsRendering(false);
					},
				);
			} else if (isDrc) {
				// No setDecoderPath() call needed -- DRACOLoader's own default
				// decoder paths are computed relative to its own module URL
				// (`new URL(..., import.meta.url)`), which Vite resolves and
				// bundles as ordinary same-origin build assets, no CDN involved.
				dracoLoader = new DRACOLoader();
				dracoLoader.load(url, handleGeometry, undefined, (err) => {
					URL.revokeObjectURL(url);
					if (disposed) return;
					console.error('Failed to load DRC for preview', err);
					setIsRendering(false);
				});
			} else {
				new STLLoader().load(url, handleGeometry, undefined, (err) => {
					URL.revokeObjectURL(url);
					if (disposed) return;
					console.error('Failed to load STL for preview', err);
					setIsRendering(false);
				});
			}
		} else {
			camera.position.set(40, 40, 30);
			controls.update();
		}

		const animate = () => {
			animationId = requestAnimationFrame(animate);
			controls.update();
			renderer.render(scene, camera);
		};
		animate();

		const handleResize = () => {
			if (!container) return;
			camera.aspect = container.clientWidth / container.clientHeight;
			camera.updateProjectionMatrix();
			renderer.setSize(container.clientWidth, container.clientHeight);
		};
		const resizeObserver = new ResizeObserver(handleResize);
		resizeObserver.observe(container);

		return () => {
			disposed = true;
			placeRef.current = null;
			centeredRef.current = null;
			if (loadedGroupRef.current === loadedObject) loadedGroupRef.current = null;
			cancelAnimationFrame(animationId);
			resizeObserver.disconnect();
			controls.dispose();
			// Terminates DRACOLoader's decode worker pool -- the other loaders
			// here don't spin up any background workers, so only this one needs
			// an explicit dispose.
			dracoLoader?.dispose();
			// Handles both a lone STL Mesh (with its LineSegments edges child)
			// and a 3MF Group of several meshes -- traverse visits the root
			// object too, so this covers the single-mesh case without a
			// separate branch.
			loadedObject?.traverse((child) => {
				if (child instanceof THREE.Mesh) {
					child.geometry.dispose();
					const mats = Array.isArray(child.material) ? child.material : [child.material];
					for (const m of mats) m.dispose();
				} else if (child instanceof THREE.LineSegments) {
					child.geometry.dispose();
					(child.material as THREE.Material).dispose();
				}
			});
			plate?.geometry.dispose();
			(plate?.material as THREE.Material | undefined)?.dispose();
			ceiling?.geometry.dispose();
			(ceiling?.material as THREE.Material | undefined)?.dispose();
			renderer.dispose();
			container.removeChild(renderer.domElement);
			if (canvasRef.current === renderer.domElement) canvasRef.current = null;
			if (liveRef.current?.renderer === renderer) liveRef.current = null;
		};
		// bedSize is intentionally included: picking/changing a printer with a
		// model already loaded should resize the plate/ceiling to match, even
		// though the file itself hasn't changed. This does re-run the whole
		// effect (camera resets too), which is an acceptable trade-off for
		// keeping one effect rather than splitting scene setup from plate
		// sizing.
	}, [file, onDimensions, bedSize, colorTree, supportEnabled, onObjectThumbnails]);

	// Move the model when only the placement changed (the scene stays).
	const placementKey = placement ? `${placement.x},${placement.y}` : '';
	// biome-ignore lint/correctness/useExhaustiveDependencies: keyed on a string that stands for the placements, so it does not rerun on every new array
	useEffect(() => {
		placeRef.current?.();
	}, [placementKey, loadVersion]);

	// Show only some objects (one plate of a multi-plate file): hide the rest,
	// centre what is left on the bed (x/y only, so everything keeps sitting on
	// the plate), and report its size.
	const shownKey = shownObjects ? shownObjects.join(',') : '';
	const rowKey = rowShifts ? JSON.stringify(rowShifts) : '';
	// biome-ignore lint/correctness/useExhaustiveDependencies: keyed on strings that stand for the shown objects and rows
	useEffect(() => {
		const group = loadedGroupRef.current;
		const base = centeredRef.current;
		if (!group || !base) return;
		arrangeShown(group, baseChildPos.current, shownObjects ? new Set(shownObjects) : null, rowShifts);
		const box = visibleBox(group);
		if (box.isEmpty()) return;
		const centre = box.getCenter(new THREE.Vector3());
		const size = box.getSize(new THREE.Vector3());
		// finishLoad centred the full scene as position = -centre; the same here
		// for x/y, with z left alone.
		centeredRef.current = new THREE.Vector3(-centre.x, -centre.y, base.z);
		rowDepthRef.current = rowShifts ? size.y : null;
		placeRef.current?.();
		onDimensionsRef.current?.({ x: size.x, y: size.y, z: size.z });
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [shownKey, rowKey, loadVersion]);

	// Dim the objects the user excluded. Swapping materials (rather than
	// editing the shared ones) keeps every other object's color untouched, and
	// the original is remembered on the mesh so un-excluding restores it.
	const excludedKey = (excludedObjects ?? []).join(',');
	// biome-ignore lint/correctness/useExhaustiveDependencies: keyed on a string that stands for the excluded objects
	useEffect(() => {
		const group = loadedGroupRef.current;
		if (!group) return;
		const excluded = new Set(excludedObjects ?? []);
		if (!dimMaterialRef.current) {
			dimMaterialRef.current = new THREE.MeshStandardMaterial({
				color: 0x8a93a0,
				transparent: true,
				opacity: 0.18,
				depthWrite: false,
				metalness: 0,
				roughness: 1,
			});
		}
		dimExcluded(group, excluded, dimMaterialRef.current);
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [excludedKey, loadVersion]);
	useEffect(() => () => dimMaterialRef.current?.dispose(), []);

	return (
		<div className="viewer-wrap">
			{/* Pure imperative mount point -- three.js owns everything inside it,
          so nothing here is a React-rendered child. */}
			<div className="viewer" ref={containerRef} />
			{!file && <div className="viewer-placeholder">Upload a model to preview it here</div>}
			{isRendering && (
				<div className="viewer-loading">
					<div className="viewer-loading-spinner" />
					<span>Rendering preview…</span>
				</div>
			)}
			{filamentUsedGrams != null && <div className="filament-badge">{filamentUsedGrams.toFixed(2)} g filament</div>}
		</div>
	);
});

export default Viewer;
