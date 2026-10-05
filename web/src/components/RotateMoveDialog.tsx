import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { DRACOLoader } from 'three/examples/jsm/loaders/DRACOLoader.js'
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader.js'
import { ThreeMFLoader } from 'three/examples/jsm/loaders/3MFLoader.js'
import { BELT_TRAVEL_MM, defaultPlacement, slideRange, type BedSize } from '../dimensions'
import { FaceIndex } from '../modelFaces'
import type { Placement, TransformStep } from '../types'
import AxisSlider from './AxisSlider'

interface RotateMoveDialogProps {
  file: File
  bedSize: BedSize
  supportEnabled: boolean
  // Where the model sits now; null = the slicer's default spot.
  placement: Placement | null
  // Set when rotating is not available (a file with several objects): the rotate controls are disabled.
  rotateDisabledReason?: string
  busyOp: 'orient' | 'arrange' | null
  onClose: () => void
  // Keep a new position without turning the model.
  onPlace: (placement: Placement) => void
  // Run the steps in the slicer, then keep the position. Resolves true when it worked.
  onTransform: (steps: TransformStep[], placement: Placement) => Promise<boolean>
  onAutoOrient: () => void
  onAutoArrange: () => void
}

type Axis = 'x' | 'y' | 'z'
type Rotation = Record<Axis, number>
type View = '3d' | 'top'
interface Footprint {
  w: number
  d: number
  h: number
}

const ZERO: Rotation = { x: 0, y: 0, z: 0 }
const AXES: { axis: Axis; label: string; hint: string }[] = [
  { axis: 'x', label: 'Tip forward / back', hint: 'X' },
  { axis: 'y', label: 'Tip left / right', hint: 'Y' },
  { axis: 'z', label: 'Spin on the plate', hint: 'Z' },
]
const MODEL_COLOUR = 0xff6f2c
const HIGHLIGHT_COLOUR = 0xffd24a

const clamp = (v: number, lo: number, hi: number) => Math.min(Math.max(v, lo), hi)
// An angle brought into (-180, 180].
const wrapAngle = (deg: number) => {
  const wrapped = ((((deg + 180) % 360) + 360) % 360) - 180
  return wrapped === -180 ? 180 : wrapped
}
const round1 = (v: number) => Math.round(v * 10) / 10

function rotationSteps(rotation: Rotation): TransformStep[] {
  const steps: TransformStep[] = []
  // The slicer is given one rotation at a time, X then Y then Z, each about the plate's own
  // axes -- the same order the preview applies them in (Euler 'ZYX' below).
  if (rotation.x !== 0) steps.push({ op: 'rotate_x', degrees: rotation.x })
  if (rotation.y !== 0) steps.push({ op: 'rotate_y', degrees: rotation.y })
  if (rotation.z !== 0) steps.push({ op: 'rotate_z', degrees: rotation.z })
  return steps
}

// What the scene lets the React side do. Everything inside is three.js state.
interface SceneApi {
  setRotation: (rotation: Rotation) => Footprint
  setPosition: (x: number, y: number) => void
  setView: (view: View) => void
  setPicking: (on: boolean) => void
  dispose: () => void
}

interface SceneOptions {
  container: HTMLDivElement
  file: File
  bed: BedSize
  onLoaded: () => void
  onError: (message: string) => void
  onHoverFace: (info: { area: number } | null) => void
  onPickFace: (normal: [number, number, number]) => void
}

function loadObject(file: File): Promise<THREE.Object3D> {
  const lower = file.name.toLowerCase()
  return file.arrayBuffer().then(
    (buffer) =>
      new Promise<THREE.Object3D>((resolve, reject) => {
        const material = new THREE.MeshStandardMaterial({ color: MODEL_COLOUR, metalness: 0.05, roughness: 0.55 })
        const fromGeometry = (geometry: THREE.BufferGeometry) => {
          geometry.computeVertexNormals()
          resolve(new THREE.Mesh(geometry, material))
        }
        try {
          if (lower.endsWith('.3mf')) {
            const group = new ThreeMFLoader().parse(buffer)
            group.traverse((child) => {
              if (child instanceof THREE.Mesh) child.material = material
            })
            resolve(group)
          } else if (lower.endsWith('.drc')) {
            const loader = new DRACOLoader()
            loader.parse(
              buffer,
              (geometry) => {
                loader.dispose()
                fromGeometry(geometry)
              },
              (err) => {
                loader.dispose()
                reject(err)
              },
            )
          } else {
            fromGeometry(new STLLoader().parse(buffer))
          }
        } catch (err) {
          reject(err)
        }
      }),
  )
}

function buildScene(options: SceneOptions): SceneApi {
  const { container, file, bed } = options
  const scene = new THREE.Scene()
  scene.background = new THREE.Color(0x14171b)
  const camera = new THREE.PerspectiveCamera(40, container.clientWidth / Math.max(container.clientHeight, 1), 0.5, 20000)
  camera.up.set(0, 0, 1)
  const renderer = new THREE.WebGLRenderer({ antialias: true })
  renderer.setPixelRatio(window.devicePixelRatio)
  renderer.setSize(container.clientWidth, container.clientHeight)
  container.appendChild(renderer.domElement)
  scene.add(new THREE.AmbientLight(0xffffff, 0.65))
  const key = new THREE.DirectionalLight(0xffffff, 0.8)
  key.position.set(1, -1, 2)
  scene.add(key)
  const fill = new THREE.DirectionalLight(0xffffff, 0.35)
  fill.position.set(-1, 1, -0.5)
  scene.add(fill)

  // Everything is in plate coordinates (mm from the bed's front-left corner at bed.minX/minY,
  // Z up), so a placement is simply where the footprint centre goes.
  const showDepth = bed.beltPrinterInfiniteY ? Math.min(bed.depth, BELT_TRAVEL_MM + 120) : bed.depth
  const bedCentre = new THREE.Vector3(bed.minX + bed.width / 2, bed.minY + showDepth / 2, 0)
  const bedGroup = new THREE.Group()
  const plane = new THREE.Mesh(
    new THREE.PlaneGeometry(bed.width, showDepth),
    new THREE.MeshBasicMaterial({ color: 0x1d2228, side: THREE.DoubleSide }),
  )
  plane.position.set(bedCentre.x, bedCentre.y, -0.3)
  bedGroup.add(plane)
  const gridPoints: number[] = []
  for (let x = 10; x < bed.width; x += 10) gridPoints.push(bed.minX + x, bed.minY, -0.2, bed.minX + x, bed.minY + showDepth, -0.2)
  for (let y = 10; y < showDepth; y += 10) gridPoints.push(bed.minX, bed.minY + y, -0.2, bed.minX + bed.width, bed.minY + y, -0.2)
  const gridGeometry = new THREE.BufferGeometry()
  gridGeometry.setAttribute('position', new THREE.Float32BufferAttribute(gridPoints, 3))
  bedGroup.add(new THREE.LineSegments(gridGeometry, new THREE.LineBasicMaterial({ color: 0x2a3038 })))
  const outline = new THREE.BufferGeometry().setFromPoints([
    new THREE.Vector3(bed.minX, bed.minY, -0.1),
    new THREE.Vector3(bed.minX + bed.width, bed.minY, -0.1),
    new THREE.Vector3(bed.minX + bed.width, bed.minY + showDepth, -0.1),
    new THREE.Vector3(bed.minX, bed.minY + showDepth, -0.1),
  ])
  bedGroup.add(new THREE.LineLoop(outline, new THREE.LineBasicMaterial({ color: 0x6b7480 })))
  scene.add(bedGroup)

  const rotator = new THREE.Group() // turned by the sliders, then moved onto the plate
  scene.add(rotator)
  let model: THREE.Object3D | null = null
  const meshes: THREE.Mesh[] = []
  const faceIndexes = new Map<THREE.Mesh, FaceIndex>()

  const controls = new OrbitControls(camera, renderer.domElement)
  controls.enableDamping = false
  let view: View = '3d'
  let dirty = true
  const requestRender = () => {
    dirty = true
  }
  controls.addEventListener('change', requestRender)

  const frame = (which: View) => {
    view = which
    const aspect = camera.aspect
    controls.target.copy(bedCentre)
    if (which === 'top') {
      const half = Math.tan((camera.fov * Math.PI) / 360)
      const distance = Math.max(showDepth / (2 * half), bed.width / (2 * half * aspect)) * 1.06
      // A hair south of straight above, so Z-up still means "back of the plate is up the screen".
      camera.position.set(bedCentre.x, bedCentre.y - 0.01, distance)
      controls.enabled = false
    } else {
      const span = Math.max(bed.width, showDepth)
      camera.position.set(bedCentre.x + span * 0.35, bedCentre.y - span * 0.95, span * 0.8)
      controls.enabled = true
    }
    camera.lookAt(bedCentre)
    controls.update()
    requestRender()
  }
  frame('3d')

  // Face picking.
  let picking = false
  let hover: THREE.Mesh | null = null
  const highlight = new THREE.Mesh(
    new THREE.BufferGeometry(),
    new THREE.MeshBasicMaterial({
      color: HIGHLIGHT_COLOUR,
      transparent: true,
      opacity: 0.75,
      side: THREE.DoubleSide,
      polygonOffset: true,
      polygonOffsetFactor: -2,
      polygonOffsetUnits: -2,
    }),
  )
  highlight.visible = false
  const raycaster = new THREE.Raycaster()
  const pointer = new THREE.Vector2()
  let lastTriangle = -1
  let lastMesh: THREE.Mesh | null = null
  let down: { x: number; y: number } | null = null

  const faceIndexFor = (mesh: THREE.Mesh) => {
    let found = faceIndexes.get(mesh)
    if (!found) {
      found = new FaceIndex(mesh.geometry)
      faceIndexes.set(mesh, found)
    }
    return found
  }
  const hit = (event: PointerEvent) => {
    const rect = renderer.domElement.getBoundingClientRect()
    pointer.set(((event.clientX - rect.left) / rect.width) * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1)
    raycaster.setFromCamera(pointer, camera)
    const first = raycaster.intersectObjects(meshes, false)[0]
    return first && first.faceIndex !== undefined && first.faceIndex !== null ? first : null
  }
  const clearHighlight = () => {
    highlight.visible = false
    hover = null
    lastTriangle = -1
    lastMesh = null
    options.onHoverFace(null)
    requestRender()
  }
  const handleMove = (event: PointerEvent) => {
    if (!picking || down) return
    const first = hit(event)
    if (!first) {
      if (highlight.visible) clearHighlight()
      return
    }
    const mesh = first.object as THREE.Mesh
    const triangle = first.faceIndex as number
    if (mesh === lastMesh && triangle === lastTriangle) return
    const index = faceIndexFor(mesh)
    const region = index.regionAt(triangle)
    // Triangles of one flat face already lit need no rebuild.
    highlight.geometry.dispose()
    highlight.geometry = index.highlightGeometry(region.triangles)
    mesh.add(highlight)
    highlight.visible = true
    hover = mesh
    lastMesh = mesh
    lastTriangle = triangle
    options.onHoverFace({ area: region.area })
    requestRender()
  }
  const handleDown = (event: PointerEvent) => {
    down = { x: event.clientX, y: event.clientY }
  }
  const handleUp = (event: PointerEvent) => {
    const start = down
    down = null
    if (!picking || !start) return
    // A drag is orbiting, not a pick.
    if (Math.hypot(event.clientX - start.x, event.clientY - start.y) > 5) return
    const first = hit(event)
    if (!first) return
    const mesh = first.object as THREE.Mesh
    const region = faceIndexFor(mesh).regionAt(first.faceIndex as number)
    const normal = region.normal.clone().transformDirection(mesh.matrixWorld)
    options.onPickFace([normal.x, normal.y, normal.z])
  }
  const handleLeave = () => {
    if (picking && highlight.visible) clearHighlight()
  }
  const canvas = renderer.domElement
  canvas.addEventListener('pointermove', handleMove)
  canvas.addEventListener('pointerdown', handleDown)
  canvas.addEventListener('pointerup', handleUp)
  canvas.addEventListener('pointerleave', handleLeave)

  let disposed = false
  let animation = 0
  const animate = () => {
    animation = requestAnimationFrame(animate)
    if (!dirty) return
    dirty = false
    renderer.render(scene, camera)
  }
  animate()

  const resize = () => {
    if (!container.clientWidth || !container.clientHeight) return
    camera.aspect = container.clientWidth / container.clientHeight
    camera.updateProjectionMatrix()
    renderer.setSize(container.clientWidth, container.clientHeight)
    if (view === 'top') frame('top')
    requestRender()
  }
  const observer = new ResizeObserver(resize)
  observer.observe(container)

  loadObject(file)
    .then((object) => {
      if (disposed) return
      object.updateMatrixWorld(true)
      const box = new THREE.Box3().setFromObject(object, true)
      object.position.sub(box.getCenter(new THREE.Vector3()))
      model = new THREE.Group()
      model.add(object)
      rotator.add(model)
      object.traverse((child) => {
        if (child instanceof THREE.Mesh) meshes.push(child)
      })
      let triangles = 0
      meshes.forEach((m) => {
        const g = m.geometry
        triangles += g.index ? g.index.count / 3 : g.getAttribute('position').count / 3
      })
      if (triangles < 200_000) {
        meshes.forEach((m) =>
          m.add(
            new THREE.LineSegments(
              new THREE.EdgesGeometry(m.geometry, 30),
              new THREE.LineBasicMaterial({ color: 0x2a1508, transparent: true, opacity: 0.5 }),
            ),
          ),
        )
      }
      options.onLoaded()
      requestRender()
    })
    .catch((err: unknown) => {
      if (!disposed) options.onError(err instanceof Error ? err.message : 'The model could not be shown')
    })

  const place = { x: bedCentre.x, y: bedCentre.y }
  const settle = (): Footprint => {
    const box = new THREE.Box3()
    rotator.position.set(0, 0, 0)
    rotator.updateMatrixWorld(true)
    box.setFromObject(rotator, true)
    if (box.isEmpty()) return { w: 0, d: 0, h: 0 }
    const centre = box.getCenter(new THREE.Vector3())
    // Footprint centre on the placement, lowest point on the plate.
    rotator.position.set(place.x - centre.x, place.y - centre.y, -box.min.z)
    rotator.updateMatrixWorld(true)
    const size = box.getSize(new THREE.Vector3())
    return { w: size.x, d: size.y, h: size.z }
  }

  return {
    setRotation(rotation) {
      // Extrinsic X, then Y, then Z about the plate axes: Euler order 'ZYX' in three.js.
      rotator.rotation.set(
        THREE.MathUtils.degToRad(rotation.x),
        THREE.MathUtils.degToRad(rotation.y),
        THREE.MathUtils.degToRad(rotation.z),
        'ZYX',
      )
      const footprint = settle()
      requestRender()
      return footprint
    },
    setPosition(x, y) {
      place.x = x
      place.y = y
      settle()
      requestRender()
    },
    setView: frame,
    setPicking(on) {
      picking = on
      renderer.domElement.style.cursor = on ? 'crosshair' : ''
      if (!on) clearHighlight()
      else
        // Building the neighbour tables takes a moment on a big mesh; do it before the first hover.
        meshes.forEach((m) => faceIndexFor(m))
    },
    dispose() {
      disposed = true
      cancelAnimationFrame(animation)
      observer.disconnect()
      canvas.removeEventListener('pointermove', handleMove)
      canvas.removeEventListener('pointerdown', handleDown)
      canvas.removeEventListener('pointerup', handleUp)
      canvas.removeEventListener('pointerleave', handleLeave)
      controls.dispose()
      if (hover) hover.remove(highlight)
      highlight.geometry.dispose()
      ;(highlight.material as THREE.Material).dispose()
      scene.traverse((child) => {
        if (child instanceof THREE.Mesh || child instanceof THREE.LineSegments || child instanceof THREE.LineLoop) {
          child.geometry.dispose()
          const mats = Array.isArray(child.material) ? child.material : [child.material]
          mats.forEach((m) => m.dispose())
        }
      })
      renderer.dispose()
      container.removeChild(renderer.domElement)
    },
  }
}

// A number box that lets you type "-", "12." and so on without snapping back.
function AngleField({ value, disabled, label, onChange }: { value: number; disabled: boolean; label: string; onChange: (v: number) => void }) {
  const [text, setText] = useState(String(value))
  const [editing, setEditing] = useState(false)
  useEffect(() => {
    if (!editing) setText(String(round1(value)))
  }, [value, editing])
  return (
    <span className="angle-field">
      <input
        type="text"
        inputMode="decimal"
        aria-label={label}
        disabled={disabled}
        value={text}
        onFocus={() => setEditing(true)}
        onBlur={() => {
          setEditing(false)
          setText(String(round1(value)))
        }}
        onChange={(e) => {
          setText(e.target.value)
          const n = Number(e.target.value)
          if (e.target.value.trim() !== '' && Number.isFinite(n)) onChange(wrapAngle(n))
        }}
      />
      <span aria-hidden="true">°</span>
    </span>
  )
}

/**
 * The "Rotate and move" window: a preview of the model on the printer's plate, a slider along
 * the left edge (front to back) and the bottom (left to right) to place it, and sliders to turn
 * it. Turning and placing only change the preview until Apply; "Lay flat" and "Pick a face"
 * ask the slicer straight away since it works out which face is flat.
 */
export default function RotateMoveDialog({
  file,
  bedSize,
  supportEnabled,
  placement,
  rotateDisabledReason,
  busyOp,
  onClose,
  onPlace,
  onTransform,
  onAutoOrient,
  onAutoArrange,
}: RotateMoveDialogProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const sceneRef = useRef<SceneApi | null>(null)
  const pickHandlerRef = useRef<(normal: [number, number, number]) => void>(() => undefined)
  const [loaded, setLoaded] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [view, setView] = useState<View>('3d')
  const [rotation, setRotation] = useState<Rotation>(ZERO)
  const startPosition = useMemo(() => placement ?? defaultPlacement(bedSize, supportEnabled), [placement, bedSize, supportEnabled])
  const [position, setPosition] = useState<Placement>(startPosition)
  const [footprint, setFootprint] = useState<Footprint>({ w: 0, d: 0, h: 0 })
  const [picking, setPicking] = useState(false)
  const [hoverArea, setHoverArea] = useState<number | null>(null)
  const [working, setWorking] = useState<'apply' | 'lay_flat' | 'face' | null>(null)

  const canRotate = !rotateDisabledReason && loaded
  const locked = working !== null || busyOp !== null

  // A different file (after Lay flat, Auto-orient, ...) or a placement set elsewhere starts over.
  useEffect(() => {
    setRotation(ZERO)
    setPosition(startPosition)
    setPicking(false)
  }, [file, startPosition])

  useEffect(() => {
    const container = containerRef.current
    if (!container) return
    setLoaded(false)
    setLoadError(null)
    const api = buildScene({
      container,
      file,
      bed: bedSize,
      onLoaded: () => setLoaded(true),
      onError: setLoadError,
      onHoverFace: (info) => setHoverArea(info ? info.area : null),
      onPickFace: (normal) => pickHandlerRef.current(normal),
    })
    sceneRef.current = api
    return () => {
      api.dispose()
      if (sceneRef.current === api) sceneRef.current = null
    }
  }, [file, bedSize])

  useEffect(() => {
    if (loaded) sceneRef.current?.setView(view)
  }, [view, loaded])

  useEffect(() => {
    if (loaded) setFootprint(sceneRef.current?.setRotation(rotation) ?? footprint)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rotation, loaded])

  useEffect(() => {
    sceneRef.current?.setPicking(picking && loaded)
    if (!picking) setHoverArea(null)
  }, [picking, loaded])

  // The centre can go anywhere the turned model still fits on the plate.
  const yTop = bedSize.beltPrinterInfiniteY ? bedSize.minY + BELT_TRAVEL_MM + footprint.d : bedSize.minY + bedSize.depth
  const [xMin, xMax] = slideRange(bedSize.minX, bedSize.minX + bedSize.width, footprint.w / 2)
  const [yMin, yMax] = slideRange(bedSize.minY, yTop, footprint.d / 2)
  const shown: Placement = { x: clamp(position.x, xMin, xMax), y: clamp(position.y, yMin, yMax) }

  useEffect(() => {
    if (loaded) sceneRef.current?.setPosition(shown.x, shown.y)
  }, [shown.x, shown.y, loaded, footprint.w, footprint.d]) // eslint-disable-line react-hooks/exhaustive-deps

  const pending = rotationSteps(rotation)
  const changed = pending.length > 0 || Math.abs(shown.x - startPosition.x) > 0.05 || Math.abs(shown.y - startPosition.y) > 0.05
  const tooTall = footprint.h > bedSize.height + 0.05

  const setAxis = useCallback((axis: Axis, degrees: number) => {
    setRotation((prev) => ({ ...prev, [axis]: wrapAngle(Math.round(degrees * 10) / 10) }))
  }, [])

  const run = (kind: 'apply' | 'lay_flat' | 'face', steps: TransformStep[]) => {
    setWorking(kind)
    setPicking(false)
    onTransform(steps, shown)
      .then((ok) => {
        if (ok && kind === 'apply') onClose()
      })
      .finally(() => setWorking(null))
  }

  const apply = () => {
    if (pending.length === 0) {
      onPlace(shown)
      onClose()
      return
    }
    run('apply', pending)
  }

  pickHandlerRef.current = (normal) => run('face', [...pending, { op: 'face_normal', normal }])

  const reset = () => {
    setRotation(ZERO)
    setPosition(startPosition)
    setPicking(false)
  }

  return (
    <div className="object-picker rotate-move" role="dialog" aria-modal="true" aria-label="Rotate and move">
      <div className="object-picker-header">
        <strong>Rotate and move</strong>
        <button type="button" className="link-button" onClick={onClose} disabled={working !== null}>
          Close ✕
        </button>
      </div>
      <div className="object-picker-scroll rotate-move-body">
        <div className="rm-stage">
          <div className="rm-vslider">
            <span>Back</span>
            <AxisSlider
              orientation="vertical"
              ariaLabel="Front to back position"
              valueText={`${(shown.y - bedSize.minY).toFixed(1)} millimetres from the front`}
              value={shown.y}
              min={yMin}
              max={yMax}
              step={0.5}
              disabled={locked || !loaded}
              onChange={(y) => setPosition({ ...shown, y })}
            />
            <span>Front</span>
          </div>
          <div className="rm-scene">
            <div ref={containerRef} className="rm-canvas" />
            <div className="rm-chips" role="group" aria-label="View">
              {(['3d', 'top'] as View[]).map((v) => (
                <button key={v} type="button" className={view === v ? 'on' : ''} aria-pressed={view === v} onClick={() => setView(v)}>
                  {v === '3d' ? '3D' : 'Top'}
                </button>
              ))}
            </div>
            {picking && (
              <div className="rm-banner">
                Click the face that should sit on the plate
                {hoverArea !== null && <strong> · {hoverArea.toFixed(0)} mm²</strong>}
                <button type="button" className="link-button" onClick={() => setPicking(false)}>
                  Cancel
                </button>
              </div>
            )}
            {!loaded && !loadError && <div className="rm-overlay">Loading the model…</div>}
            {loadError && <div className="rm-overlay rm-error">This file can&rsquo;t be shown here ({loadError}).</div>}
            {working && <div className="rm-overlay">{working === 'apply' ? 'Rotating…' : 'Laying it flat…'}</div>}
          </div>
          <div className="rm-hslider">
            <span>Left</span>
            <AxisSlider
              ariaLabel="Left to right position"
              valueText={`${(shown.x - bedSize.minX).toFixed(1)} millimetres from the left`}
              value={shown.x}
              min={xMin}
              max={xMax}
              step={0.5}
              disabled={locked || !loaded}
              onChange={(x) => setPosition({ ...shown, x })}
            />
            <span>Right</span>
            <span className="rm-readout">
              X {(shown.x - bedSize.minX).toFixed(1)} · Y {(shown.y - bedSize.minY).toFixed(1)} mm
            </span>
          </div>
        </div>

        <div className="rm-size" aria-live="polite">
          {footprint.w > 0 && (
            <>
              {footprint.w.toFixed(1)} × {footprint.d.toFixed(1)} × {footprint.h.toFixed(1)} mm
              {tooTall && <span className="field-error"> · taller than the printer ({bedSize.height} mm)</span>}
            </>
          )}
        </div>

        <div className={`rm-rotate${picking ? ' rm-dim' : ''}`}>
          {AXES.map(({ axis, label, hint }) => (
            <div className="rm-row" key={axis}>
              <span className="rm-row-name">
                {label}
                <small>{hint}</small>
              </span>
              <AxisSlider
                ariaLabel={`${label}, degrees`}
                valueText={`${rotation[axis]} degrees`}
                value={rotation[axis]}
                min={-180}
                max={180}
                step={1}
                tick={0}
                disabled={locked || !canRotate || picking}
                onChange={(v) => setAxis(axis, v)}
              />
              <AngleField label={`${label}, angle`} value={rotation[axis]} disabled={locked || !canRotate || picking} onChange={(v) => setAxis(axis, v)} />
              <span className="rm-quarter">
                <button type="button" className="preview-button" disabled={locked || !canRotate || picking} onClick={() => setAxis(axis, rotation[axis] - 90)}>
                  −90
                </button>
                <button type="button" className="preview-button" disabled={locked || !canRotate || picking} onClick={() => setAxis(axis, rotation[axis] + 90)}>
                  +90
                </button>
              </span>
            </div>
          ))}
        </div>
        {rotateDisabledReason && <p className="auth-hint">{rotateDisabledReason}</p>}

        <div className="rm-tools">
          <button
            type="button"
            className="preview-button"
            disabled={locked || !canRotate}
            onClick={() => run('lay_flat', [...pending, { op: 'lay_flat' }])}
          >
            Lay flat
          </button>
          <button
            type="button"
            className={`preview-button${picking ? ' active' : ''}`}
            disabled={locked || !canRotate}
            aria-pressed={picking}
            onClick={() => setPicking((p) => !p)}
          >
            Pick a face…
          </button>
          <button type="button" className="preview-button" disabled={locked || !changed} onClick={reset}>
            Reset
          </button>
          <span className="auth-hint rm-tools-note">Lay flat and Pick a face run in the slicer and take a second or two.</span>
        </div>
      </div>
      <div className="rm-footer">
        <span className="rm-footer-left">
          <button type="button" className="preview-button" disabled={locked || !loaded} onClick={onAutoOrient}>
            {busyOp === 'orient' ? 'Orienting…' : 'Auto-orient'}
          </button>
          <button type="button" className="preview-button" disabled={locked || !loaded} onClick={onAutoArrange}>
            {busyOp === 'arrange' ? 'Arranging…' : 'Auto-arrange'}
          </button>
        </span>
        <span className="rm-footer-right">
          <button type="button" className="preview-button" onClick={onClose} disabled={working !== null}>
            Cancel
          </button>
          <button type="button" onClick={apply} disabled={locked || !loaded}>
            {working === 'apply' ? 'Rotating…' : 'Apply'}
          </button>
        </span>
      </div>
    </div>
  )
}
