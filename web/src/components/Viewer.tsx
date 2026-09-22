import { useEffect, useRef, useState } from 'react'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader.js'
import { ThreeMFLoader } from 'three/examples/jsm/loaders/3MFLoader.js'
import { DRACOLoader } from 'three/examples/jsm/loaders/DRACOLoader.js'
import type { BedSize, Dimensions } from '../dimensions'
import type { ColorNode } from '../types'

interface ViewerProps {
  file: File | null
  onDimensions?: (dims: Dimensions | null) => void
  bedSize?: BedSize | null
  // Per-object/part colors for a .3mf, in the exact tree shape 3MFLoader
  // itself builds (see api/app/threemf.py) -- applied by walking the
  // loaded Group in lockstep with this tree. Ignored for STL/DRC (which
  // never produce a Group) or when empty/absent, in which case every mesh
  // gets the same flat default color as before this existed.
  colorTree?: ColorNode[]
}

// Basic model preview: not meant to be a full slicer viewport (no layer
// preview, no plate/gizmos) -- just enough to confirm "yes, that's the
// object I uploaded" before slicing. Drag-to-rotate/zoom via OrbitControls
// comes along for free with three.js and costs nothing extra, but nothing
// here depends on interaction actually happening.
export default function Viewer({ file, onDimensions, bedSize, colorTree }: ViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  // Geometry loading (a fresh .3mf/.stl/.drc) and per-triangle color
  // application (toNonIndexed() + a fresh vertex-color buffer per painted
  // mesh, see applyTriangleColors below) can both take a noticeable moment
  // on a large model -- this whole effect re-runs on every colorTree change
  // too (a nozzle reassignment), re-fetching and re-parsing the file from
  // scratch, not just recoloring in place. Surfaced as a loading overlay
  // rather than left silent so a slow model/reassignment doesn't look hung.
  const [isRendering, setIsRendering] = useState(false)

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    setIsRendering(!!file)

    // Cleared immediately on a new/removed file so stale dimensions from a
    // previous model don't linger in the UI while the new one loads.
    onDimensions?.(null)

    const scene = new THREE.Scene()
    scene.background = new THREE.Color(0x2a2e35)

    const camera = new THREE.PerspectiveCamera(
      45,
      container.clientWidth / container.clientHeight,
      0.1,
      10000,
    )
    // STL/print convention is Z-up (Z = build height, model sits on the
    // plate at its minimum Z), not three.js's default Y-up -- without this,
    // an asymmetric model renders lying on its side. Must be set before
    // OrbitControls is constructed, which reads it to orient orbiting.
    camera.up.set(0, 0, 1)

    const renderer = new THREE.WebGLRenderer({ antialias: true })
    renderer.setPixelRatio(window.devicePixelRatio)
    renderer.setSize(container.clientWidth, container.clientHeight)
    container.appendChild(renderer.domElement)

    scene.add(new THREE.AmbientLight(0xffffff, 0.6))
    const key = new THREE.DirectionalLight(0xffffff, 0.8)
    key.position.set(1, 1, 1)
    scene.add(key)
    const fill = new THREE.DirectionalLight(0xffffff, 0.4)
    fill.position.set(-1, -0.5, -1)
    scene.add(fill)

    const controls = new OrbitControls(camera, renderer.domElement)
    controls.enableDamping = true

    // Not meant to be a single mesh/geometry across both loader paths:
    // STLLoader yields one BufferGeometry -> one Mesh, but 3MFLoader.parse()
    // yields a THREE.Group of meshes (one per object in the file) -- this
    // holds whichever one is currently loaded so the cleanup effect below
    // has one place to traverse-and-dispose regardless of which it is.
    let loadedObject: THREE.Object3D | null = null
    let plate: THREE.Mesh | null = null
    let ceiling: THREE.Mesh | null = null
    let animationId = 0
    let disposed = false
    // Only instantiated for a .drc file (below) -- holds a worker pool that
    // needs explicit disposal, unlike the other loaders here.
    let dracoLoader: DRACOLoader | null = null

    // A muted blue-gray blended into the dark background too easily. A
    // saturated, warm color (like a printed-plastic filament) reads clearly
    // against the dark viewport at any lighting angle. Shared across every
    // mesh in a .3mf's group too -- this is a geometry-only preview, not a
    // render of the file's own embedded per-object colors/materials.
    const material = new THREE.MeshStandardMaterial({
      color: 0xff6f2c,
      metalness: 0.05,
      roughness: 0.55,
    })

    // Auto-frame the model at the origin, size the reference plate/ceiling,
    // and report dimensions -- identical for both loader paths once each
    // has centered its own object and handed over its world-space box.
    const finishLoad = (object: THREE.Object3D, box: THREE.Box3) => {
      const center = new THREE.Vector3()
      box.getCenter(center)
      object.position.sub(center)

      const size = new THREE.Vector3()
      box.getSize(size)

      // A reference plate just under the model: the selected printer's
      // actual bed size once one is picked (bedSize), or just wider than
      // the model's own footprint before that -- "roughly where the build
      // surface is" rather than nothing at all.
      const plateMargin = 1.3
      const plateWidth = bedSize?.width ?? size.x * plateMargin
      const plateDepth = bedSize?.depth ?? size.y * plateMargin
      const plateZ = -size.z / 2

      // Auto-frame the model itself, regardless of the plate/ceiling size --
      // those are there to check against by zooming/orbiting out manually
      // if needed, not something the default view should reframe around (a
      // small model on a large-bed printer would otherwise auto-zoom out to
      // a barely-visible speck by default).
      const radius = size.length() / 2 || 1
      const distance = radius / Math.sin((Math.PI * camera.fov) / 360)

      camera.position.set(distance, distance, distance * 0.6)
      camera.near = distance / 100
      camera.far = distance * 100
      camera.updateProjectionMatrix()
      controls.target.set(0, 0, 0)
      controls.update()

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
      )
      plate.position.z = plateZ
      scene.add(plate)

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
        )
        ceiling.rotation.x = Math.PI
        ceiling.position.z = plate.position.z + bedSize.height
        scene.add(ceiling)
      }

      onDimensions?.({ x: size.x, y: size.y, z: size.z })
    }

    // Colors a .3mf's loaded Group by walking it in lockstep with
    // colorTree, which mirrors 3MFLoader's own build order exactly (see
    // api/app/threemf.py) -- object3D.children[i] corresponds to
    // nodes[i] at every level, whether that's a top-level <build><item>
    // or a composite object's <components>. Bails to the flat default
    // color for a whole subtree the moment the shapes stop lining up
    // (wrong child count) rather than risk coloring the wrong mesh.
    const coloredMaterials = new Map<string, THREE.MeshStandardMaterial>()
    const materialForColor = (hex: string) => {
      const existing = coloredMaterials.get(hex)
      if (existing) return existing
      const created = new THREE.MeshStandardMaterial({ color: hex, metalness: 0.05, roughness: 0.55 })
      coloredMaterials.set(hex, created)
      return created
    }
    const applyFlatMaterial = (object3D: THREE.Object3D, mat: THREE.Material) => {
      object3D.traverse((child) => {
        if (child instanceof THREE.Mesh) child.material = mat
      })
    }
    // Approximates a leaf's hand-painted per-triangle colors: one flat
    // color per ORIGINAL triangle (see api/app/threemf.py's
    // _representative_extruder), not a sub-triangle-accurate repaint --
    // good enough for "does the preview roughly look like the print".
    // Converts to non-indexed geometry (every face gets its own 3 unique
    // vertices) so each face can carry its own flat vertex color, since
    // the original indexed geometry shares vertices between faces.
    const applyTriangleColors = (
      object3D: THREE.Object3D,
      baseColorHex: string | null,
      triangleColors: (string | null)[],
    ) => {
      object3D.traverse((child) => {
        if (!(child instanceof THREE.Mesh)) return
        const geometry = child.geometry
        const faceCount = geometry.index ? geometry.index.count / 3 : geometry.attributes.position.count / 3
        if (faceCount !== triangleColors.length) {
          // Shape mismatch -- bail to this mesh's flat default rather than
          // risk coloring the wrong faces.
          child.material = baseColorHex ? materialForColor(baseColorHex) : material
          return
        }
        const nonIndexed = geometry.toNonIndexed()
        const colors = new Float32Array(nonIndexed.attributes.position.count * 3)
        const fallback = new THREE.Color(baseColorHex ?? '#ffffff')
        const tmp = new THREE.Color()
        triangleColors.forEach((hex, i) => {
          const c = hex ? tmp.set(hex) : fallback
          for (let vertex = 0; vertex < 3; vertex++) {
            const base = (i * 3 + vertex) * 3
            colors[base] = c.r
            colors[base + 1] = c.g
            colors[base + 2] = c.b
          }
        })
        nonIndexed.setAttribute('color', new THREE.BufferAttribute(colors, 3))
        geometry.dispose()
        child.geometry = nonIndexed
        child.material = new THREE.MeshStandardMaterial({ vertexColors: true, metalness: 0.05, roughness: 0.55 })
      })
    }
    const applyColorTree = (object3D: THREE.Object3D, nodes: ColorNode[]) => {
      const children = object3D.children
      if (nodes.length !== children.length) {
        applyFlatMaterial(object3D, material)
        return
      }
      children.forEach((child, i) => {
        const node = nodes[i]
        if (node.children.length > 0) {
          applyColorTree(child, node.children)
        } else if (node.triangle_colors && node.triangle_colors.length > 0) {
          applyTriangleColors(child, node.color, node.triangle_colors)
        } else {
          applyFlatMaterial(child, node.color ? materialForColor(node.color) : material)
        }
      })
    }

    if (file) {
      const url = URL.createObjectURL(file)
      const lowerName = file.name.toLowerCase()
      const isThreeMf = lowerName.endsWith('.3mf')
      const isDrc = lowerName.endsWith('.drc')

      // Shared by the STL and DRC branches below: both loaders hand back a
      // single BufferGeometry (unlike 3MFLoader's Group), so wrapping it in
      // a Mesh + edge outline + auto-frame is identical either way.
      const handleGeometry = (geometry: THREE.BufferGeometry) => {
        if (disposed) return
        geometry.computeVertexNormals()
        geometry.computeBoundingBox()

        const mesh = new THREE.Mesh(geometry, material)
        scene.add(mesh)
        loadedObject = mesh

        // Edge lines make flat-shaded faces read as a solid shape instead
        // of a smear of color, especially for simple/low-poly models.
        const edges = new THREE.LineSegments(
          new THREE.EdgesGeometry(geometry, 30),
          new THREE.LineBasicMaterial({ color: 0x2a1508, transparent: true, opacity: 0.5 }),
        )
        mesh.add(edges)

        finishLoad(mesh, geometry.boundingBox!)
        URL.revokeObjectURL(url)
        setIsRendering(false)
      }

      if (isThreeMf) {
        new ThreeMFLoader().load(
          url,
          (group) => {
            if (disposed) {
              URL.revokeObjectURL(url)
              return
            }
            // Colors each object/part using colorTree when it's usable
            // (see applyColorTree above); otherwise every mesh gets the
            // same flat default color, same as before per-object color
            // support existed.
            if (colorTree && colorTree.length > 0) {
              applyColorTree(group, colorTree)
            } else {
              applyFlatMaterial(group, material)
            }
            scene.add(group)
            loadedObject = group
            finishLoad(group, new THREE.Box3().setFromObject(group))
            URL.revokeObjectURL(url)
            setIsRendering(false)
          },
          undefined,
          (err) => {
            URL.revokeObjectURL(url)
            if (disposed) return
            console.error('Failed to load 3MF for preview', err)
            setIsRendering(false)
          },
        )
      } else if (isDrc) {
        // No setDecoderPath() call needed -- DRACOLoader's own default
        // decoder paths are computed relative to its own module URL
        // (`new URL(..., import.meta.url)`), which Vite resolves and
        // bundles as ordinary same-origin build assets, no CDN involved.
        dracoLoader = new DRACOLoader()
        dracoLoader.load(
          url,
          handleGeometry,
          undefined,
          (err) => {
            URL.revokeObjectURL(url)
            if (disposed) return
            console.error('Failed to load DRC for preview', err)
            setIsRendering(false)
          },
        )
      } else {
        new STLLoader().load(
          url,
          handleGeometry,
          undefined,
          (err) => {
            URL.revokeObjectURL(url)
            if (disposed) return
            console.error('Failed to load STL for preview', err)
            setIsRendering(false)
          },
        )
      }
    } else {
      camera.position.set(40, 40, 30)
      controls.update()
    }

    const animate = () => {
      animationId = requestAnimationFrame(animate)
      controls.update()
      renderer.render(scene, camera)
    }
    animate()

    const handleResize = () => {
      if (!container) return
      camera.aspect = container.clientWidth / container.clientHeight
      camera.updateProjectionMatrix()
      renderer.setSize(container.clientWidth, container.clientHeight)
    }
    const resizeObserver = new ResizeObserver(handleResize)
    resizeObserver.observe(container)

    return () => {
      disposed = true
      cancelAnimationFrame(animationId)
      resizeObserver.disconnect()
      controls.dispose()
      // Terminates DRACOLoader's decode worker pool -- the other loaders
      // here don't spin up any background workers, so only this one needs
      // an explicit dispose.
      dracoLoader?.dispose()
      // Handles both a lone STL Mesh (with its LineSegments edges child)
      // and a 3MF Group of several meshes -- traverse visits the root
      // object too, so this covers the single-mesh case without a
      // separate branch.
      loadedObject?.traverse((child) => {
        if (child instanceof THREE.Mesh) {
          child.geometry.dispose()
          const mats = Array.isArray(child.material) ? child.material : [child.material]
          mats.forEach((m) => m.dispose())
        } else if (child instanceof THREE.LineSegments) {
          child.geometry.dispose()
          ;(child.material as THREE.Material).dispose()
        }
      })
      plate?.geometry.dispose()
      ;(plate?.material as THREE.Material | undefined)?.dispose()
      ceiling?.geometry.dispose()
      ;(ceiling?.material as THREE.Material | undefined)?.dispose()
      renderer.dispose()
      container.removeChild(renderer.domElement)
    }
    // bedSize is intentionally included: picking/changing a printer with a
    // model already loaded should resize the plate/ceiling to match, even
    // though the file itself hasn't changed. This does re-run the whole
    // effect (camera resets too), which is an acceptable trade-off for
    // keeping one effect rather than splitting scene setup from plate
    // sizing.
  }, [file, onDimensions, bedSize, colorTree])

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
    </div>
  )
}
