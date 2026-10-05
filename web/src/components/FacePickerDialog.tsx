import { useEffect, useRef, useState } from 'react'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { FaceIndex } from '../modelFaces'
import { loadObject, rotationQuaternion, rotationToLayOnFace, type Rotation } from '../modelLoading'

interface FacePickerDialogProps {
  file: File
  // The turn already set in the Rotate and move window; the model is shown with it applied.
  rotation: Rotation
  onCancel: () => void
  onChoose: (rotation: Rotation) => void
}

interface Picked {
  area: number
  // A face the model can rest on: nothing sticks out past it.
  restable: boolean
  normal: THREE.Vector3
}

interface PickerScene {
  clearSelection: () => void
  dispose: () => void
}

const HOVER_COLOUR = 0xffd24a
const SELECT_COLOUR = 0xffb020
const BAD_COLOUR = 0xff5c5c
// How far past a face's plane the rest of the model may reach and still count as resting on it.
const REST_TOLERANCE_MM = 0.05

function buildScene(
  container: HTMLDivElement,
  file: File,
  rotation: Rotation,
  callbacks: {
    onReady: () => void
    onError: (message: string) => void
    onHover: (area: number | null) => void
    onSelect: (picked: Picked | null) => void
  },
): PickerScene {
  const scene = new THREE.Scene()
  scene.background = new THREE.Color(0x14171b)
  const camera = new THREE.PerspectiveCamera(40, container.clientWidth / Math.max(container.clientHeight, 1), 0.1, 20000)
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

  const controls = new OrbitControls(camera, renderer.domElement)
  controls.enableDamping = false
  let dirty = true
  controls.addEventListener('change', () => {
    dirty = true
  })

  const rotator = new THREE.Group()
  rotator.quaternion.copy(rotationQuaternion(rotation))
  scene.add(rotator)
  const meshes: THREE.Mesh[] = []
  const faceIndexes = new Map<THREE.Mesh, FaceIndex>()
  const extras: THREE.Object3D[] = []

  const makeHighlight = (colour: number, opacity: number) => {
    const mesh = new THREE.Mesh(
      new THREE.BufferGeometry(),
      new THREE.MeshBasicMaterial({
        color: colour,
        transparent: true,
        opacity,
        side: THREE.DoubleSide,
        polygonOffset: true,
        polygonOffsetFactor: -2,
        polygonOffsetUnits: -2,
      }),
    )
    mesh.visible = false
    return mesh
  }
  const hoverMark = makeHighlight(HOVER_COLOUR, 0.4)
  const selectMark = makeHighlight(SELECT_COLOUR, 0.85)

  const raycaster = new THREE.Raycaster()
  const pointer = new THREE.Vector2()
  let hoverKey = ''
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
  const show = (mark: THREE.Mesh, mesh: THREE.Mesh, index: FaceIndex, triangles: number[]) => {
    mark.geometry.dispose()
    mark.geometry = index.highlightGeometry(triangles)
    mesh.add(mark)
    mark.visible = true
    dirty = true
  }

  // True when no vertex of the model reaches out past the plane of the face: the face is part of the
  // model's outer hull, so the model can stand on it.
  const canRestOn = (normal: THREE.Vector3, pointOnFace: THREE.Vector3): boolean => {
    const offset = normal.dot(pointOnFace)
    const m = new THREE.Matrix4()
    const local = new THREE.Vector3()
    for (const mesh of meshes) {
      mesh.updateWorldMatrix(true, false)
      m.copy(mesh.matrixWorld)
      // n . (M v + t) = (M^T n) . v + n . t, so each vertex costs one dot product.
      const e = m.elements
      local.set(
        e[0] * normal.x + e[1] * normal.y + e[2] * normal.z,
        e[4] * normal.x + e[5] * normal.y + e[6] * normal.z,
        e[8] * normal.x + e[9] * normal.y + e[10] * normal.z,
      )
      const shift = e[12] * normal.x + e[13] * normal.y + e[14] * normal.z
      const position = mesh.geometry.getAttribute('position')
      for (let i = 0; i < position.count; i++) {
        if (local.x * position.getX(i) + local.y * position.getY(i) + local.z * position.getZ(i) + shift > offset + REST_TOLERANCE_MM) {
          return false
        }
      }
    }
    return true
  }

  const handleMove = (event: PointerEvent) => {
    if (down) return
    const first = hit(event)
    if (!first) {
      if (hoverMark.visible) {
        hoverMark.visible = false
        hoverKey = ''
        callbacks.onHover(null)
        dirty = true
      }
      return
    }
    const mesh = first.object as THREE.Mesh
    const index = faceIndexFor(mesh)
    const region = index.regionAt(first.faceIndex as number)
    const key = `${meshes.indexOf(mesh)}:${Math.min(...region.triangles.slice(0, 50))}:${region.triangles.length}`
    if (key === hoverKey) return
    hoverKey = key
    show(hoverMark, mesh, index, region.triangles)
    callbacks.onHover(region.area)
  }
  const handleDown = (event: PointerEvent) => {
    down = { x: event.clientX, y: event.clientY }
  }
  const handleUp = (event: PointerEvent) => {
    const start = down
    down = null
    // A drag is turning the view, not choosing a face.
    if (!start || Math.hypot(event.clientX - start.x, event.clientY - start.y) > 6) return
    const first = hit(event)
    if (!first) return
    const mesh = first.object as THREE.Mesh
    const index = faceIndexFor(mesh)
    const region = index.regionAt(first.faceIndex as number)
    mesh.updateWorldMatrix(true, false)
    const normal = region.normal.clone().transformDirection(mesh.matrixWorld)
    const triangle = region.triangles[0]
    const position = mesh.geometry.getAttribute('position')
    const vertexIndex = mesh.geometry.index ? mesh.geometry.index.getX(triangle * 3) : triangle * 3
    const pointOnFace = new THREE.Vector3(position.getX(vertexIndex), position.getY(vertexIndex), position.getZ(vertexIndex)).applyMatrix4(
      mesh.matrixWorld,
    )
    const restable = canRestOn(normal, pointOnFace)
    ;(selectMark.material as THREE.MeshBasicMaterial).color.setHex(restable ? SELECT_COLOUR : BAD_COLOUR)
    show(selectMark, mesh, index, region.triangles)
    hoverMark.visible = false
    callbacks.onSelect({ area: region.area, restable, normal })
  }
  const handleLeave = () => {
    if (hoverMark.visible) {
      hoverMark.visible = false
      hoverKey = ''
      callbacks.onHover(null)
      dirty = true
    }
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
    dirty = true
  }
  const observer = new ResizeObserver(resize)
  observer.observe(container)

  loadObject(file)
    .then((object) => {
      if (disposed) return
      rotator.add(object)
      scene.updateMatrixWorld(true)
      // Centre the turned model on the origin and rest it on a ground grid, so "down" is obvious.
      const box = new THREE.Box3().setFromObject(rotator, true)
      const centre = box.getCenter(new THREE.Vector3())
      rotator.position.set(-centre.x, -centre.y, -box.min.z)
      scene.updateMatrixWorld(true)
      const size = box.getSize(new THREE.Vector3())
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
      const span = Math.max(size.x, size.y, size.z)
      const gridSize = Math.max(span * 2.4, 40)
      // See-through, so the underside of the model can be seen and picked from below.
      const ground = new THREE.Mesh(
        new THREE.PlaneGeometry(gridSize, gridSize),
        new THREE.MeshBasicMaterial({ color: 0x8a95a5, transparent: true, opacity: 0.16, depthWrite: false, side: THREE.DoubleSide }),
      )
      ground.position.z = -0.3
      const grid = new THREE.GridHelper(gridSize, Math.round(gridSize / 10), 0x3a414b, 0x2a3038)
      grid.rotation.x = Math.PI / 2
      grid.position.z = -0.2
      scene.add(ground, grid)
      extras.push(ground, grid)
      // Build the neighbour tables now (a big mesh takes a moment) rather than on the first hover.
      meshes.forEach((m) => faceIndexFor(m))
      const target = new THREE.Vector3(0, 0, size.z / 2)
      const distance = (span * 1.1) / Math.tan((camera.fov * Math.PI) / 360)
      camera.position.set(target.x + distance * 0.55, target.y - distance * 0.8, target.z + distance * 0.55)
      camera.near = distance / 100
      camera.far = distance * 100
      camera.updateProjectionMatrix()
      controls.target.copy(target)
      controls.update()
      dirty = true
      callbacks.onReady()
    })
    .catch((err: unknown) => {
      if (!disposed) callbacks.onError(err instanceof Error ? err.message : 'The model could not be shown')
    })

  return {
    clearSelection() {
      selectMark.visible = false
      dirty = true
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
      for (const mark of [hoverMark, selectMark]) {
        mark.geometry.dispose()
        ;(mark.material as THREE.Material).dispose()
      }
      extras.forEach((e) => {
        if (e instanceof THREE.Mesh || e instanceof THREE.LineSegments) {
          e.geometry.dispose()
          const mats = Array.isArray(e.material) ? e.material : [e.material]
          mats.forEach((m) => m.dispose())
        }
      })
      rotator.traverse((child) => {
        if (child instanceof THREE.Mesh || child instanceof THREE.LineSegments) {
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

/**
 * A window of its own for choosing the face that should sit on the plate: just the model, big, so
 * it works on a phone without scrolling anywhere. Click a face to select it (it stays highlighted),
 * then confirm. The turn that puts that face down is worked out here, so the slicer cannot end up
 * resting the model on a different face.
 */
export default function FacePickerDialog({ file, rotation, onCancel, onChoose }: FacePickerDialogProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const sceneRef = useRef<PickerScene | null>(null)
  const [ready, setReady] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [hoverArea, setHoverArea] = useState<number | null>(null)
  const [picked, setPicked] = useState<Picked | null>(null)

  useEffect(() => {
    const container = containerRef.current
    if (!container) return
    const api = buildScene(container, file, rotation, {
      onReady: () => setReady(true),
      onError: setError,
      onHover: setHoverArea,
      onSelect: setPicked,
    })
    sceneRef.current = api
    return () => {
      api.dispose()
      if (sceneRef.current === api) sceneRef.current = null
    }
    // The picker opens on one fixed state of the model; it is remounted for another.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [file])

  const confirm = () => {
    if (picked?.restable) onChoose(rotationToLayOnFace(rotation, picked.normal))
  }

  let status: string
  if (error) status = `This file can't be shown here (${error}).`
  else if (!ready) status = 'Loading the model…'
  else if (picked && !picked.restable) status = "The model can't rest on this face: part of it sticks out past it. Choose another."
  else if (picked) status = `Face selected · ${picked.area.toFixed(0)} mm². Press the button to put it on the plate.`
  else if (hoverArea !== null) status = `${hoverArea.toFixed(0)} mm² · click to select this face`
  else status = 'Drag to turn the model, then click the face that should sit on the plate.'

  return (
    <div className="object-picker face-picker" role="dialog" aria-modal="true" aria-label="Pick a face">
      <div className="object-picker-header">
        <strong>Pick a face</strong>
        <button type="button" className="link-button" onClick={onCancel}>
          Close ✕
        </button>
      </div>
      <div className="fp-scene">
        <div ref={containerRef} className="fp-canvas" />
      </div>
      <div className={`fp-status${picked && !picked.restable ? ' field-error' : ''}`} aria-live="polite">
        {status}
      </div>
      <div className="fp-footer">
        <button
          type="button"
          className="preview-button"
          disabled={!picked}
          onClick={() => {
            setPicked(null)
            sceneRef.current?.clearSelection()
          }}
        >
          Clear selection
        </button>
        <span className="fp-footer-right">
          <button type="button" className="preview-button" onClick={onCancel}>
            Cancel
          </button>
          <button type="button" onClick={confirm} disabled={!picked?.restable}>
            Put this face on the plate
          </button>
        </span>
      </div>
    </div>
  )
}
