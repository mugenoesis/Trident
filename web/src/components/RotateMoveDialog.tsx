import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { BELT_TRAVEL_MM, defaultPlacement, slideRange, type BedSize } from '../dimensions'
import { largestRestableFace } from '../modelFaces'
import { loadObject, rotationQuaternion, rotationToLayOnFace, splitObjects, type Rotation } from '../modelLoading'
import type { ObjectEdit, Placement, TransformStep } from '../types'
import AxisSlider from './AxisSlider'
import FacePickerDialog from './FacePickerDialog'

interface RotateMoveDialogProps {
  file: File
  bedSize: BedSize
  supportEnabled: boolean
  // Where the model sits now; null = the slicer's default spot.
  placement: Placement | null
  // Names and little pictures of the file's objects (by file index), when there are several.
  objectNames: string[]
  thumbnails: Record<number, string>
  // A file with several plates: the file indices of the objects on the chosen plate. Only those are
  // shown and changed; objects on other plates are left exactly as they are.
  plateObjects?: number[]
  busyOp: 'orient' | 'arrange' | null
  onClose: () => void
  // Keep a new position without turning anything.
  onPlace: (placement: Placement) => void
  // One object: run the steps in the slicer, then keep the position. Resolves true when it worked.
  onTransform: (steps: TransformStep[], placement: Placement) => Promise<boolean>
  // Several objects: write each object's turn and position into the model, then keep the group's centre.
  onTransformObjects: (edits: ObjectEdit[], groupCentre: Placement) => Promise<boolean>
  onAutoOrient: () => void
  onAutoArrange: () => void
}

type Axis = 'x' | 'y' | 'z'
type View = '3d' | 'top'
interface Footprint {
  w: number
  d: number
  h: number
}
// What the window holds for one object: how far it is turned and where its footprint centre is.
interface ObjectState {
  rot: Rotation
  pos: Placement
}

const ZERO: Rotation = { x: 0, y: 0, z: 0 }
const AXES: { axis: Axis; label: string; hint: string }[] = [
  { axis: 'x', label: 'Tip forward / back', hint: 'X' },
  { axis: 'y', label: 'Tip left / right', hint: 'Y' },
  { axis: 'z', label: 'Spin on the plate', hint: 'Z' },
]
// More objects than this are picked from a list instead of a row of pictures.
const MAX_CHIPS = 8
const OVERLAP_MARGIN_MM = 0.5

const clamp = (v: number, lo: number, hi: number) => Math.min(Math.max(v, lo), hi)
// An angle brought into (-180, 180].
const wrapAngle = (deg: number) => {
  const wrapped = ((((deg + 180) % 360) + 360) % 360) - 180
  return wrapped === -180 ? 180 : wrapped
}
const round1 = (v: number) => Math.round(v * 10) / 10
const isTurned = (r: Rotation) => r.x !== 0 || r.y !== 0 || r.z !== 0
const moved = (a: Placement, b: Placement) => Math.abs(a.x - b.x) > 0.05 || Math.abs(a.y - b.y) > 0.05

function rotationSteps(rotation: Rotation): TransformStep[] {
  const steps: TransformStep[] = []
  // The slicer is given one rotation at a time, X then Y then Z, each about the plate's own
  // axes -- the same order the preview applies them in (Euler 'ZYX').
  if (rotation.x !== 0) steps.push({ op: 'rotate_x', degrees: rotation.x })
  if (rotation.y !== 0) steps.push({ op: 'rotate_y', degrees: rotation.y })
  if (rotation.z !== 0) steps.push({ op: 'rotate_z', degrees: rotation.z })
  return steps
}

// What the scene lets the React side do. Everything inside is three.js state.
interface SceneApi {
  // Turn object i and put its footprint centre on pos; returns its footprint.
  setObject: (index: number, rotation: Rotation, pos: Placement) => Footprint
  // The object with the sliders is drawn in colour, the others greyed out (a single object always is).
  select: (index: number) => void
  setView: (view: View) => void
  // The turn that lays object i on its largest flat face, or null when it has none.
  layFlat: (index: number, current: Rotation) => Rotation | null
  dispose: () => void
}

interface SceneOptions {
  container: HTMLDivElement
  file: File
  bed: BedSize
  // Only these objects (file indices) are shown; undefined shows them all.
  only?: number[]
  onLoaded: (objects: { fileIndex: number; centre: Placement; footprint: Footprint }[]) => void
  onError: (message: string) => void
  onPickObject: (index: number) => void
}

interface SceneObject {
  rotator: THREE.Group // turned by the sliders, then moved onto the plate
  meshes: THREE.Mesh[]
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

  const objects: SceneObject[] = []
  const allMeshes: THREE.Mesh[] = []
  const ghost = new THREE.MeshStandardMaterial({ color: 0x6b7480, transparent: true, opacity: 0.55, metalness: 0.05, roughness: 0.8 })

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

  // Clicking an object (without dragging, which turns the view) selects it.
  const raycaster = new THREE.Raycaster()
  const pointer = new THREE.Vector2()
  let down: { x: number; y: number } | null = null
  const canvas = renderer.domElement
  const handleDown = (event: PointerEvent) => {
    down = { x: event.clientX, y: event.clientY }
  }
  const handleUp = (event: PointerEvent) => {
    const start = down
    down = null
    if (!start || objects.length < 2 || Math.hypot(event.clientX - start.x, event.clientY - start.y) > 6) return
    const rect = canvas.getBoundingClientRect()
    pointer.set(((event.clientX - rect.left) / rect.width) * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1)
    raycaster.setFromCamera(pointer, camera)
    const first = raycaster.intersectObjects(allMeshes, false)[0]
    const index = first ? (first.object.userData.objectIndex as number | undefined) : undefined
    if (index !== undefined) options.onPickObject(index)
  }
  canvas.addEventListener('pointerdown', handleDown)
  canvas.addEventListener('pointerup', handleUp)

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

  const settle = (item: SceneObject, rotation: Rotation, pos: Placement): Footprint => {
    const { rotator } = item
    rotator.quaternion.copy(rotationQuaternion(rotation))
    rotator.position.set(0, 0, 0)
    rotator.updateMatrixWorld(true)
    const box = new THREE.Box3().setFromObject(rotator, true)
    if (box.isEmpty()) return { w: 0, d: 0, h: 0 }
    const centre = box.getCenter(new THREE.Vector3())
    // Footprint centre on the position, lowest point on the plate.
    rotator.position.set(pos.x - centre.x, pos.y - centre.y, -box.min.z)
    rotator.updateMatrixWorld(true)
    const size = box.getSize(new THREE.Vector3())
    return { w: size.x, d: size.y, h: size.z }
  }

  loadObject(file)
    .then((loaded) => {
      if (disposed) return
      const info: { fileIndex: number; centre: Placement; footprint: Footprint }[] = []
      splitObjects(loaded).forEach((part, fileIndex) => {
        if (options.only && !options.only.includes(fileIndex)) {
          // Not on this plate: not shown, and its memory given back.
          part.traverse((child) => {
            if (child instanceof THREE.Mesh) {
              child.geometry.dispose()
              const mats = Array.isArray(child.material) ? child.material : [child.material]
              mats.forEach((m) => m.dispose())
            }
          })
          return
        }
        const index = objects.length
        // Centre the object on the origin inside its own rotator, remembering where it started.
        const box = new THREE.Box3().setFromObject(part, true)
        const centre0 = box.getCenter(new THREE.Vector3())
        const centred = new THREE.Group()
        centred.position.set(-centre0.x, -centre0.y, -centre0.z)
        centred.add(part)
        const rotator = new THREE.Group()
        rotator.add(centred)
        scene.add(rotator)
        const meshes: THREE.Mesh[] = []
        part.traverse((child) => {
          if (child instanceof THREE.Mesh) {
            child.userData.objectIndex = index
            child.userData.original = child.material
            meshes.push(child)
          }
        })
        allMeshes.push(...meshes)
        objects.push({ rotator, meshes })
        const size = box.getSize(new THREE.Vector3())
        info.push({ fileIndex, centre: { x: centre0.x, y: centre0.y }, footprint: { w: size.x, d: size.y, h: size.z } })
      })
      let triangles = 0
      allMeshes.forEach((m) => {
        const g = m.geometry
        triangles += g.index ? g.index.count / 3 : g.getAttribute('position').count / 3
      })
      if (triangles < 200_000) {
        allMeshes.forEach((m) =>
          m.add(
            new THREE.LineSegments(
              new THREE.EdgesGeometry(m.geometry, 30),
              new THREE.LineBasicMaterial({ color: 0x2a1508, transparent: true, opacity: 0.5 }),
            ),
          ),
        )
      }
      options.onLoaded(info)
      requestRender()
    })
    .catch((err: unknown) => {
      if (!disposed) options.onError(err instanceof Error ? err.message : 'The model could not be shown')
    })

  return {
    setObject(index, rotation, pos) {
      const item = objects[index]
      if (!item) return { w: 0, d: 0, h: 0 }
      const footprint = settle(item, rotation, pos)
      requestRender()
      return footprint
    },
    select(index) {
      objects.forEach((item, i) => {
        item.meshes.forEach((m) => {
          m.material = objects.length < 2 || i === index ? (m.userData.original as THREE.Material) : ghost
        })
      })
      requestRender()
    },
    setView: frame,
    layFlat(index, current) {
      const item = objects[index]
      if (!item) return null
      const normal = largestRestableFace(item.meshes)
      return normal ? rotationToLayOnFace(current, normal) : null
    },
    dispose() {
      disposed = true
      cancelAnimationFrame(animation)
      observer.disconnect()
      canvas.removeEventListener('pointerdown', handleDown)
      canvas.removeEventListener('pointerup', handleUp)
      controls.dispose()
      ghost.dispose()
      scene.traverse((child) => {
        if (child instanceof THREE.Mesh || child instanceof THREE.LineSegments || child instanceof THREE.LineLoop) {
          child.geometry.dispose()
          const mats = Array.isArray(child.material) ? child.material : [child.material]
          mats.forEach((m) => m.dispose())
          const original = child.userData.original as THREE.Material | undefined
          original?.dispose()
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
 * it. Turning and placing only change the preview until Apply. "Lay flat" on a single object asks
 * the slicer straight away since it works out which face is flat.
 *
 * A file with several objects works one object at a time: pick one (chips, or click it) and the
 * sliders act on it while the others stay greyed out. Apply writes every object's turn and
 * position into the model together.
 */
export default function RotateMoveDialog({
  file,
  bedSize,
  supportEnabled,
  placement,
  objectNames,
  thumbnails,
  busyOp,
  onClose,
  onPlace,
  onTransform,
  plateObjects,
  onTransformObjects,
  onAutoOrient,
  onAutoArrange,
}: RotateMoveDialogProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const sceneRef = useRef<SceneApi | null>(null)
  const appliedRef = useRef<ObjectState[]>([])
  const [loaded, setLoaded] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [view, setView] = useState<View>('3d')
  const startPosition = useMemo(() => placement ?? defaultPlacement(bedSize, supportEnabled), [placement, bedSize, supportEnabled])
  const startRef = useRef(startPosition)
  useEffect(() => {
    startRef.current = startPosition
  }, [startPosition])
  // Where each object was when the window opened (shifted so the group is centred on the current
  // position), and where it is now.
  const [initial, setInitial] = useState<ObjectState[]>([])
  // Each shown object's place in the file, and where it started in the file's own coordinates.
  const [fileIndexes, setFileIndexes] = useState<number[]>([])
  const [origins, setOrigins] = useState<Placement[]>([])
  const [objs, setObjs] = useState<ObjectState[]>([])
  const [footprints, setFootprints] = useState<Footprint[]>([])
  const [selected, setSelected] = useState(0)
  const [pickerOpen, setPickerOpen] = useState(false)
  const [note, setNote] = useState<string | null>(null)
  const [working, setWorking] = useState<'apply' | 'lay_flat' | null>(null)

  const count = objs.length
  const several = count > 1
  // One object at a time through the file's own object placements; the slicer's rotate turns every
  // object of every plate, so it is only used for a file with a single object.
  const perObject = several || Boolean(plateObjects)
  const locked = working !== null || busyOp !== null
  const canRotate = loaded && !loadError
  const current: ObjectState = objs[selected] ?? { rot: ZERO, pos: startPosition }
  const footprint: Footprint = footprints[selected] ?? { w: 0, d: 0, h: 0 }

  // A different file (after Lay flat, Auto-orient, Apply ...) rebuilds the scene and starts over.
  useEffect(() => {
    const container = containerRef.current
    if (!container) return
    setLoaded(false)
    setLoadError(null)
    setPickerOpen(false)
    setNote(null)
    appliedRef.current = []
    const api = buildScene({
      container,
      file,
      bed: bedSize,
      only: plateObjects,
      onLoaded: (info) => {
        // Put the whole group's centre on the current position; each object keeps its place within it.
        const minX = Math.min(...info.map((o) => o.centre.x - o.footprint.w / 2))
        const maxX = Math.max(...info.map((o) => o.centre.x + o.footprint.w / 2))
        const minY = Math.min(...info.map((o) => o.centre.y - o.footprint.d / 2))
        const maxY = Math.max(...info.map((o) => o.centre.y + o.footprint.d / 2))
        const shiftX = startRef.current.x - (minX + maxX) / 2
        const shiftY = startRef.current.y - (minY + maxY) / 2
        const start = info.map((o) => ({ rot: ZERO, pos: { x: o.centre.x + shiftX, y: o.centre.y + shiftY } }))
        setInitial(start)
        setObjs(start)
        setFileIndexes(info.map((o) => o.fileIndex))
        setOrigins(info.map((o) => o.centre))
        setFootprints(info.map((o) => o.footprint))
        setSelected(0)
        setLoaded(true)
      },
      onError: setLoadError,
      onPickObject: setSelected,
    })
    sceneRef.current = api
    return () => {
      api.dispose()
      if (sceneRef.current === api) sceneRef.current = null
    }
    // plateObjects only changes with the file.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [file, bedSize])

  useEffect(() => {
    if (loaded) sceneRef.current?.setView(view)
  }, [view, loaded])

  useEffect(() => {
    if (loaded) sceneRef.current?.select(selected)
  }, [selected, loaded, count])

  // Push whatever changed to the scene and read back each object's footprint.
  useEffect(() => {
    const api = sceneRef.current
    if (!loaded || !api) return
    let changed = false
    const next = footprints.slice()
    objs.forEach((o, i) => {
      const before = appliedRef.current[i]
      if (before && before.rot.x === o.rot.x && before.rot.y === o.rot.y && before.rot.z === o.rot.z && !moved(before.pos, o.pos)) return
      next[i] = api.setObject(i, o.rot, o.pos)
      appliedRef.current[i] = o
      changed = true
    })
    if (changed) setFootprints(next)
    // footprints is read, not a trigger: it only changes here.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [objs, loaded])

  // The centre can go anywhere the turned object still fits on the plate.
  const yTop = bedSize.beltPrinterInfiniteY ? bedSize.minY + BELT_TRAVEL_MM + footprint.d : bedSize.minY + bedSize.depth
  const [xMin, xMax] = slideRange(bedSize.minX, bedSize.minX + bedSize.width, footprint.w / 2)
  const [yMin, yMax] = slideRange(bedSize.minY, yTop, footprint.d / 2)
  const shown: Placement = { x: clamp(current.pos.x, xMin, xMax), y: clamp(current.pos.y, yMin, yMax) }
  // Turning can leave the selected object hanging past the plate; pull it back.
  useEffect(() => {
    if (!loaded || footprint.w === 0) return
    if (moved(shown, current.pos)) {
      setObjs((prev) => prev.map((o, i) => (i === selected ? { ...o, pos: shown } : o)))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [footprint.w, footprint.d, selected, loaded])

  const update = useCallback(
    (patch: (o: ObjectState) => ObjectState) => {
      setObjs((prev) => prev.map((o, i) => (i === selected ? patch(o) : o)))
      setNote(null)
    },
    [selected],
  )
  const setAxis = useCallback(
    (axis: Axis, degrees: number) => update((o) => ({ ...o, rot: { ...o.rot, [axis]: wrapAngle(Math.round(degrees * 10) / 10) } })),
    [update],
  )

  // Which objects are pending changes, and which overlap.
  const changedFlags = objs.map((o, i) => isTurned(o.rot) || (initial[i] ? moved(o.pos, initial[i].pos) : false))
  const changedCount = changedFlags.filter(Boolean).length
  const overlaps = useMemo(() => {
    const found = new Map<number, { other: number; mm: number }>()
    for (let i = 0; i < objs.length; i++) {
      for (let j = i + 1; j < objs.length; j++) {
        const a = footprints[i]
        const b = footprints[j]
        if (!a || !b) continue
        const ox = Math.min(objs[i].pos.x + a.w / 2, objs[j].pos.x + b.w / 2) - Math.max(objs[i].pos.x - a.w / 2, objs[j].pos.x - b.w / 2)
        const oy = Math.min(objs[i].pos.y + a.d / 2, objs[j].pos.y + b.d / 2) - Math.max(objs[i].pos.y - a.d / 2, objs[j].pos.y - b.d / 2)
        if (ox > OVERLAP_MARGIN_MM && oy > OVERLAP_MARGIN_MM) {
          const mm = Math.min(ox, oy)
          if (!found.has(i)) found.set(i, { other: j, mm })
          if (!found.has(j)) found.set(j, { other: i, mm })
        }
      }
    }
    return found
  }, [objs, footprints])
  const tooTall = footprint.h > bedSize.height + 0.05
  // A file's objects often share one name (several copies of a part); number them so each is distinct.
  const nameOf = (i: number) => {
    const fileIndex = fileIndexes[i] ?? i
    const name = objectNames[fileIndex]
    const shown = fileIndexes.map((f) => objectNames[f])
    const shared = !name || shown.filter((n) => n === name).length > 1
    return shared ? `${name || 'Object'} ${fileIndex + 1}` : name
  }

  const groupCentre = (): Placement => {
    const minX = Math.min(...objs.map((o, i) => o.pos.x - (footprints[i]?.w ?? 0) / 2))
    const maxX = Math.max(...objs.map((o, i) => o.pos.x + (footprints[i]?.w ?? 0) / 2))
    const minY = Math.min(...objs.map((o, i) => o.pos.y - (footprints[i]?.d ?? 0) / 2))
    const maxY = Math.max(...objs.map((o, i) => o.pos.y + (footprints[i]?.d ?? 0) / 2))
    return { x: (minX + maxX) / 2, y: (minY + maxY) / 2 }
  }

  const run = (kind: 'apply' | 'lay_flat', task: Promise<boolean>) => {
    setWorking(kind)
    setNote(null)
    task
      .then((ok) => {
        if (ok && kind === 'apply') onClose()
      })
      .finally(() => setWorking(null))
  }

  const apply = () => {
    if (!perObject) {
      const steps = rotationSteps(current.rot)
      if (steps.length === 0) {
        onPlace(shown)
        onClose()
        return
      }
      run('apply', onTransform(steps, shown))
      return
    }
    if (changedCount === 0) {
      onClose()
      return
    }
    // One plate of several: only what was changed is written, as a move from where the object was in
    // the file, so its place on the plate and every other plate stay as they are. Otherwise every
    // object is written at its place on the bed.
    const edits: ObjectEdit[] = objs
      .map((o, i) => ({ o, i }))
      .filter(({ i }) => !plateObjects || changedFlags[i])
      .map(({ o, i }) => ({
        index: fileIndexes[i] ?? i,
        x_deg: o.rot.x,
        y_deg: o.rot.y,
        z_deg: o.rot.z,
        x: plateObjects ? (origins[i]?.x ?? 0) + (o.pos.x - initial[i].pos.x) : o.pos.x,
        y: plateObjects ? (origins[i]?.y ?? 0) + (o.pos.y - initial[i].pos.y) : o.pos.y,
      }))
    run('apply', onTransformObjects(edits, groupCentre()))
  }

  const layFlat = () => {
    if (!perObject) {
      run('lay_flat', onTransform([...rotationSteps(current.rot), { op: 'lay_flat' }], shown))
      return
    }
    // Several objects: worked out here, so it is instant and touches only the selected one.
    const turn = sceneRef.current?.layFlat(selected, current.rot)
    if (turn) update((o) => ({ ...o, rot: turn }))
    else setNote(`${nameOf(selected)} has no flat face to lie on.`)
  }

  const resetSelected = () => {
    const start = initial[selected]
    if (start) update(() => start)
    setNote(null)
  }
  const resetAll = () => {
    setObjs(initial)
    setNote(null)
  }
  const confirmDiscard = () => changedCount === 0 || window.confirm('Discard the changes you have not applied?')

  return (
    <div className="object-picker rotate-move" role="dialog" aria-modal="true" aria-label="Rotate and move">
      <div className="object-picker-header">
        <strong>Rotate and move</strong>
        <button type="button" className="link-button" onClick={onClose} disabled={working !== null}>
          Close ✕
        </button>
      </div>
      <div className="object-picker-scroll rotate-move-body">
        {several && (
          <div className="rm-objects" role="group" aria-label="Object to move">
            <span className="rm-objects-label">Moving</span>
            {count > MAX_CHIPS ? (
              <select value={selected} aria-label="Object to move" onChange={(e) => setSelected(Number(e.target.value))}>
                {objs.map((_, i) => (
                  <option key={i} value={i}>
                    {nameOf(i)}
                    {changedFlags[i] ? ' (changed)' : ''}
                  </option>
                ))}
              </select>
            ) : (
              objs.map((o, i) => {
                const overlap = overlaps.get(i)
                const status = overlap
                  ? `overlaps ${nameOf(overlap.other)}`
                  : isTurned(o.rot) && initial[i] && moved(o.pos, initial[i].pos)
                    ? 'turned and moved'
                    : isTurned(o.rot)
                      ? 'turned'
                      : initial[i] && moved(o.pos, initial[i].pos)
                        ? 'moved'
                        : 'unchanged'
                return (
                  <button
                    key={i}
                    type="button"
                    className={`rm-chip${i === selected ? ' sel' : ''}${overlap ? ' warn' : ''}`}
                    aria-pressed={i === selected}
                    onClick={() => setSelected(i)}
                  >
                    {thumbnails[fileIndexes[i] ?? i] ? <img src={thumbnails[fileIndexes[i] ?? i]} alt="" /> : <span className="rm-chip-blank" aria-hidden="true" />}
                    <span>
                      {nameOf(i)}
                      <small>{status}</small>
                    </span>
                  </button>
                )
              })
            )}
          </div>
        )}

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
              onChange={(y) => update((o) => ({ ...o, pos: { ...shown, y } }))}
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
            {several && overlaps.has(selected) && (
              <div className="rm-tip rm-tip-bad">
                {nameOf(selected)} overlaps {nameOf(overlaps.get(selected)!.other)} by about {overlaps.get(selected)!.mm.toFixed(0)} mm
              </div>
            )}
            {!loaded && !loadError && <div className="rm-overlay">Loading the model…</div>}
            {loadError && <div className="rm-overlay rm-error">This file can&rsquo;t be shown here ({loadError}).</div>}
            {working && <div className="rm-overlay">{working === 'apply' ? 'Applying…' : 'Laying it flat…'}</div>}
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
              onChange={(x) => update((o) => ({ ...o, pos: { ...shown, x } }))}
            />
            <span>Right</span>
            <span className="rm-readout">
              {several ? `${nameOf(selected)} · ` : ''}X {(shown.x - bedSize.minX).toFixed(1)} · Y {(shown.y - bedSize.minY).toFixed(1)} mm
            </span>
          </div>
        </div>

        <div className="rm-size" aria-live="polite">
          {footprint.w > 0 && (
            <>
              {several ? `${nameOf(selected)}: ` : ''}
              {footprint.w.toFixed(1)} × {footprint.d.toFixed(1)} × {footprint.h.toFixed(1)} mm
              {tooTall && <span className="field-error"> · taller than the printer ({bedSize.height} mm)</span>}
            </>
          )}
        </div>

        <div className="rm-rotate">
          {AXES.map(({ axis, label, hint }) => (
            <div className="rm-row" key={axis}>
              <span className="rm-row-name">
                {label}
                <small>{hint}</small>
              </span>
              <AxisSlider
                ariaLabel={`${label}, degrees`}
                valueText={`${current.rot[axis]} degrees`}
                value={current.rot[axis]}
                min={-180}
                max={180}
                step={1}
                tick={0}
                disabled={locked || !canRotate}
                onChange={(v) => setAxis(axis, v)}
              />
              <AngleField label={`${label}, angle`} value={current.rot[axis]} disabled={locked || !canRotate} onChange={(v) => setAxis(axis, v)} />
              <span className="rm-quarter">
                <button type="button" className="preview-button" disabled={locked || !canRotate} onClick={() => setAxis(axis, current.rot[axis] - 90)}>
                  −90
                </button>
                <button type="button" className="preview-button" disabled={locked || !canRotate} onClick={() => setAxis(axis, current.rot[axis] + 90)}>
                  +90
                </button>
              </span>
            </div>
          ))}
        </div>

        <div className="rm-tools">
          <button type="button" className="preview-button" disabled={locked || !canRotate} onClick={layFlat}>
            Lay flat
          </button>
          <button type="button" className="preview-button" disabled={locked || !canRotate} onClick={() => setPickerOpen(true)}>
            Pick a face…
          </button>
          <button
            type="button"
            className="preview-button"
            disabled={locked || !(several ? changedFlags[selected] : changedCount > 0)}
            onClick={resetSelected}
          >
            {several ? 'Reset this object' : 'Reset'}
          </button>
          {several && (
            <button type="button" className="preview-button" disabled={locked || changedCount === 0} onClick={resetAll}>
              Reset all
            </button>
          )}
          <span className="auth-hint rm-tools-note">
            {note ??
              (several
                ? 'Turning, moving and the face tools act on the selected object.'
                : plateObjects
                  ? 'Only the objects on this plate are shown; the other plates stay as they are.'
                  : 'Lay flat runs in the slicer and takes a second or two.')}
          </span>
        </div>
      </div>
      <div className="rm-footer">
        <span className="rm-footer-left">
          {!plateObjects && (
            <>
          <button
            type="button"
            className="preview-button"
            disabled={locked || !loaded}
            onClick={() => confirmDiscard() && onAutoOrient()}
          >
            {busyOp === 'orient' ? 'Orienting…' : several ? 'Auto-orient all' : 'Auto-orient'}
          </button>
          <button
            type="button"
            className="preview-button"
            disabled={locked || !loaded}
            onClick={() => confirmDiscard() && onAutoArrange()}
          >
            {busyOp === 'arrange' ? 'Arranging…' : several ? 'Auto-arrange all' : 'Auto-arrange'}
          </button>
            </>
          )}
        </span>
        <span className="rm-footer-right">
          <button type="button" className="preview-button" onClick={onClose} disabled={working !== null}>
            Cancel
          </button>
          <button type="button" onClick={apply} disabled={locked || !loaded}>
            {working === 'apply' ? 'Applying…' : several && changedCount > 0 ? `Apply ${changedCount} change${changedCount === 1 ? '' : 's'}` : 'Apply'}
          </button>
        </span>
      </div>
      {pickerOpen && (
        <FacePickerDialog
          file={file}
          rotation={current.rot}
          objectIndex={fileIndexes[selected] ?? selected}
          onCancel={() => setPickerOpen(false)}
          onChoose={(next) => {
            update((o) => ({ ...o, rot: next }))
            setNote('Turned to put the chosen face down. Press Apply to keep it.')
            setPickerOpen(false)
          }}
        />
      )}
    </div>
  )
}
