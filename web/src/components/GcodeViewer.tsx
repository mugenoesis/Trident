import { useEffect, useRef, useState } from 'react'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { gcodeDownloadUrl } from '../api'
import { parseGcode, type GcodeLayer } from '../gcodeParser'
import type { BeltTransform } from '../beltTransform'

// Fallback only for a gcode flavor without a `;HEIGHT:` comment (see
// GcodeLayer.height, gcodeParser.ts, which buildSolid prefers below) --
// averaging the Z each layer's segments were actually drawn at. This breaks
// down for a belt printer's real (post-back-transform) coordinates: one
// nominal slicing layer maps to a DIAGONAL plane through the object's
// upright shape, not a horizontal one, so consecutive layers' average
// upright Z isn't monotonic (confirmed against a real IdeaFormer IR3 V2
// slice: layer-to-layer average deltas ranged from -1.7mm to +3.0mm once the
// belt back-transform was applied) -- `;HEIGHT:` is unaffected by any of
// this since it's the slicer's own nominal per-layer value, not derived from
// coordinates.
function averageLayerZ(layer: GcodeLayer): number {
  let sum = 0
  for (const seg of layer.segments) sum += seg.z1
  return sum / layer.segments.length
}

interface GcodeViewerProps {
  jobId: string
  // This job's total filament weight (api/app/gcode_stats.py), shown as a
  // small badge over the toolpath view -- null/undefined hides it.
  filamentUsedGrams?: number | null
  // Non-null only for a belt printer with a real machine-frame tilt (see
  // beltTransform.ts) -- un-shears the raw G-code back into the object's
  // upright shape before rendering. null/undefined renders G-code as-is,
  // same as any normal printer.
  beltTransform?: BeltTransform | null
  onBackToModel: () => void
}

type RenderMode = 'solid' | 'lines'

// Approximate extrusion width used to give toolpath segments real thickness
// in "solid" mode. The parser doesn't know the actual line width (that's
// derived from flow, not present in the G-code moves themselves), so this is
// a visual stand-in, not a dimensionally exact value.
const EXTRUSION_WIDTH_MM = 0.42

// REVERTED (see git history for the attempt): a belt printer's full-history
// render can look like an early support column is "disconnected" from later
// structure once consecutive slicing layers sweep past it -- but windowing
// by a fixed trailing G-code-Z span was WORSE, not better: a support tower's
// own height can climb tens of mm within the first few physical layers (a
// 45-degree diagonal slice through a fast-rising structure), so a 60mm
// window dropped genuinely current, still-printing geometry -- confirmed on
// a real IdeaFormer IR3 V2 job where the viewer showed the purge line and
// support as already disconnected by layer 4 of 260, while the raw G-code
// proves the support's own extrusion never lifts off the belt (constant
// ~0.14mm minimum height from layer 0 onward). Full cumulative history is
// occasionally confusing to look at, but never wrong; a "recent window" that
// silently deletes real toolpath is a strictly worse trade.

// Real toolpath preview, not just "here's the file": fetches the sliced
// G-code, parses out the extruding moves (gcodeParser.ts), and renders them
// two ways, toggleable:
//  - "lines": every move as a thin colored line, hued by layer -- cheap and
//    shows the raw path/order, but hard to read as an actual object.
//  - "solid": every move as a small lit, shadowed box (oriented + scaled to
//    the segment), giving something that reads like the printed part itself.
// Both share a layer slider (drawRange for lines, instance count for solid)
// so scrubbing works identically in either mode.
// Rendered inline in place of the 3D model Viewer (App.tsx), not a modal --
// swapped in automatically once a slice succeeds.
export default function GcodeViewer({
  jobId,
  filamentUsedGrams,
  beltTransform,
  onBackToModel,
}: GcodeViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [status, setStatus] = useState<'loading' | 'error' | 'ready'>('loading')
  const [layerCount, setLayerCount] = useState(0)
  const [visibleLayers, setVisibleLayers] = useState(0)
  const [renderMode, setRenderMode] = useState<RenderMode>('lines')

  const layersRef = useRef<GcodeLayer[]>([])
  const renderModeRef = useRef<RenderMode>(renderMode)
  // Set by the main effect once the scene exists; called by the mode-toggle
  // and visible-layers effects so they can act on the live scene without
  // re-fetching/re-parsing or re-framing the camera.
  const rebuildRef = useRef<((mode: RenderMode, visible: number) => void) | null>(null)
  const applyVisibleRef = useRef<((visible: number) => void) | null>(null)

  useEffect(() => {
    const container = containerRef.current
    if (!container) return
    let disposed = false

    const scene = new THREE.Scene()
    scene.background = new THREE.Color(0x2a2e35)
    const camera = new THREE.PerspectiveCamera(
      45,
      container.clientWidth / container.clientHeight,
      0.1,
      100000,
    )
    camera.up.set(0, 0, 1)
    // Solid mode's shadow-mapped, per-fragment-lit InstancedMesh is the
    // heaviest thing this app renders, and its cost scales with actual
    // pixel count -- a high-DPR phone screen (Galaxy Fold-class devices
    // report 2.6-3x) asks the GPU to shade several times as many fragments
    // as a capped ratio would. Capping this is the single biggest lever
    // for keeping it usable on mobile; MSAA (antialias) is the other
    // meaningful cost on mobile tile-based GPUs, so it's off too.
    const renderer = new THREE.WebGLRenderer({ antialias: false })
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    renderer.setSize(container.clientWidth, container.clientHeight)
    renderer.shadowMap.enabled = true
    renderer.shadowMap.type = THREE.PCFShadowMap
    container.appendChild(renderer.domElement)

    const controls = new OrbitControls(camera, renderer.domElement)
    controls.enableDamping = true

    scene.add(new THREE.AmbientLight(0xffffff, 0.55))
    // Key light: positioned to roughly match the camera's viewing direction
    // (same X/Y sign, higher elevation) so the faces the camera actually
    // sees are the ones getting lit, instead of being side- or back-lit.
    const keyLight = new THREE.DirectionalLight(0xffffff, 1.2)
    keyLight.castShadow = true
    keyLight.shadow.mapSize.set(512, 512)
    keyLight.shadow.bias = -0.0005
    scene.add(keyLight)
    scene.add(keyLight.target)
    // Fill light: soft, no shadow, from the opposite side -- keeps the
    // faces away from the key light from going fully black.
    const fillLight = new THREE.DirectionalLight(0xffffff, 0.35)
    scene.add(fillLight)
    scene.add(fillLight.target)

    // Only shown/lit in "solid" mode -- catches shadows to make layer/wall
    // detail readable, but would just clutter the raw path view.
    const ground = new THREE.Mesh(
      new THREE.PlaneGeometry(1, 1),
      new THREE.MeshStandardMaterial({ color: 0x3a3f47, roughness: 1 }),
    )
    ground.receiveShadow = true
    ground.visible = false
    scene.add(ground)

    let animationId = 0
    const animate = () => {
      animationId = requestAnimationFrame(animate)
      controls.update()
      renderer.render(scene, camera)
    }
    animate()

    const handleResize = () => {
      camera.aspect = container.clientWidth / container.clientHeight
      camera.updateProjectionMatrix()
      renderer.setSize(container.clientWidth, container.clientHeight)
    }
    const resizeObserver = new ResizeObserver(handleResize)
    resizeObserver.observe(container)

    let activeObject: THREE.LineSegments | THREE.InstancedMesh | null = null
    let layerEnds: number[] = []
    const center = new THREE.Vector3()
    let groundZ = 0

    const disposeActive = () => {
      if (!activeObject) return
      scene.remove(activeObject)
      activeObject.geometry.dispose()
      ;(activeObject.material as THREE.Material).dispose()
      activeObject = null
    }

    const buildLines = (layers: GcodeLayer[]) => {
      const positions: number[] = []
      const colors: number[] = []
      const ends: number[] = []
      layers.forEach((layer, layerIndex) => {
        const color = new THREE.Color().setHSL(
          0.72 - 0.72 * (layerIndex / Math.max(1, layers.length - 1)),
          0.7,
          0.55,
        )
        for (const seg of layer.segments) {
          positions.push(seg.x1, seg.y1, seg.z1, seg.x2, seg.y2, seg.z2)
          colors.push(color.r, color.g, color.b, color.r, color.g, color.b)
        }
        ends.push(positions.length / 3)
      })
      const geometry = new THREE.BufferGeometry()
      geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3))
      geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3))
      const object = new THREE.LineSegments(geometry, new THREE.LineBasicMaterial({ vertexColors: true }))
      return { object, layerEnds: ends }
    }

    // Orients+positions `dummy` for a segment, picking the "width" axis as
    // perpendicular to both the travel direction and world-up: this keeps
    // the box's height axis pointing as close to true vertical as possible
    // for the (near-universal) case of horizontal-ish extrusion moves,
    // instead of the arbitrary/discontinuous roll you get from a plain
    // quaternion-between-two-vectors rotation. Returns segment length, or 0
    // for a degenerate (zero-length) move.
    const worldUp = new THREE.Vector3(0, 0, 1)
    const dummy = new THREE.Object3D()
    const dirVec = new THREE.Vector3()
    const widthAxis = new THREE.Vector3()
    const heightAxis = new THREE.Vector3()
    const basis = new THREE.Matrix4()
    const orientDummy = (x1: number, y1: number, z1: number, x2: number, y2: number, z2: number) => {
      dirVec.set(x2 - x1, y2 - y1, z2 - z1)
      const length = dirVec.length()
      if (length < 1e-6) return 0
      dirVec.normalize()
      widthAxis.crossVectors(worldUp, dirVec)
      if (widthAxis.lengthSq() < 1e-8) {
        widthAxis.set(1, 0, 0).cross(dirVec)
        if (widthAxis.lengthSq() < 1e-8) widthAxis.set(0, 1, 0)
      }
      widthAxis.normalize()
      heightAxis.crossVectors(dirVec, widthAxis).normalize()
      basis.makeBasis(dirVec, widthAxis, heightAxis)
      dummy.quaternion.setFromRotationMatrix(basis)
      dummy.position.set((x1 + x2) / 2, (y1 + y2) / 2, (z1 + z2) / 2)
      return length
    }

    const buildSolid = (layers: GcodeLayer[]) => {
      const total = layers.reduce((n, layer) => n + layer.segments.length, 0)
      const geometry = new THREE.BoxGeometry(1, 1, 1)
      const material = new THREE.MeshStandardMaterial({ color: 0xff6f2c, roughness: 0.65, metalness: 0.05 })
      const object = new THREE.InstancedMesh(geometry, material, Math.max(total, 1))
      object.castShadow = true
      object.receiveShadow = true
      let index = 0
      const ends: number[] = []
      const layerZs = layers.map(averageLayerZ)
      layers.forEach((layer, layerIndex) => {
        const fallbackHeight =
          layerIndex === 0
            ? Math.max(0.05, layerZs[0])
            : Math.max(0.05, Math.abs(layerZs[layerIndex] - layerZs[layerIndex - 1]))
        const layerHeight = layer.height !== undefined ? Math.max(0.05, layer.height) : fallbackHeight
        for (const seg of layer.segments) {
          const length = orientDummy(seg.x1, seg.y1, seg.z1, seg.x2, seg.y2, seg.z2)
          if (length <= 0) continue
          dummy.scale.set(length, EXTRUSION_WIDTH_MM, layerHeight)
          dummy.updateMatrix()
          object.setMatrixAt(index++, dummy.matrix)
        }
        ends.push(index)
      })
      object.count = index
      object.instanceMatrix.needsUpdate = true
      return { object, layerEnds: ends }
    }

    const applyVisible = (visible: number) => {
      if (!activeObject) return
      const end = visible > 0 && layerEnds.length > 0 ? layerEnds[Math.min(visible, layerEnds.length) - 1] : 0
      if (activeObject instanceof THREE.LineSegments) {
        activeObject.geometry.setDrawRange(0, end)
      } else {
        activeObject.count = end
      }
    }
    applyVisibleRef.current = applyVisible

    const rebuild = (mode: RenderMode, visible: number) => {
      disposeActive()
      const built = mode === 'lines' ? buildLines(layersRef.current) : buildSolid(layersRef.current)
      activeObject = built.object
      layerEnds = built.layerEnds
      activeObject.position.set(-center.x, -center.y, -center.z)
      scene.add(activeObject)
      ground.visible = mode === 'solid'
      applyVisible(visible)
    }
    rebuildRef.current = rebuild

    fetch(gcodeDownloadUrl(jobId))
      .then((res) => {
        if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
        return res.text()
      })
      .then((text) => {
        if (disposed) return
        const { layers } = parseGcode(text, beltTransform)
        if (layers.length === 0) throw new Error('No extrusion moves found in this G-code')
        layersRef.current = layers

        const bounds = new THREE.Box3()
        const point = new THREE.Vector3()
        for (const layer of layers) {
          for (const seg of layer.segments) {
            bounds.expandByPoint(point.set(seg.x1, seg.y1, seg.z1))
            bounds.expandByPoint(point.set(seg.x2, seg.y2, seg.z2))
          }
        }
        bounds.getCenter(center)
        const size = new THREE.Vector3()
        bounds.getSize(size)
        groundZ = bounds.min.z - center.z

        const planeSize = Math.max(size.x, size.y) * 2.5 || 100
        ground.geometry.dispose()
        ground.geometry = new THREE.PlaneGeometry(planeSize, planeSize)
        ground.position.set(0, 0, groundZ)

        const radius = size.length() / 2 || 1
        // Same X/Y sign as the camera (set just below) so the key light
        // shines from roughly the direction the camera is looking from,
        // just higher overhead -- lights the visible faces instead of
        // grazing/back-lighting them.
        keyLight.position.set(radius * 1.3, radius * 1.6, radius * 1.8)
        keyLight.shadow.camera.left = -radius * 1.5
        keyLight.shadow.camera.right = radius * 1.5
        keyLight.shadow.camera.top = radius * 1.5
        keyLight.shadow.camera.bottom = -radius * 1.5
        keyLight.shadow.camera.near = 0.1
        keyLight.shadow.camera.far = radius * 6
        keyLight.shadow.camera.updateProjectionMatrix()
        fillLight.position.set(-radius * 1.2, -radius * 0.8, radius * 1.0)

        const distance = radius / Math.sin((Math.PI * camera.fov) / 360)
        camera.position.set(distance, distance, distance * 0.6)
        camera.near = distance / 1000
        camera.far = distance * 100
        camera.updateProjectionMatrix()
        controls.target.set(0, 0, 0)
        controls.update()

        setLayerCount(layers.length)
        setVisibleLayers(layers.length)
        rebuild(renderModeRef.current, layers.length)
        setStatus('ready')
      })
      .catch((err: Error) => {
        if (!disposed) {
          console.error('Failed to load G-code preview', err)
          setStatus('error')
        }
      })

    return () => {
      disposed = true
      cancelAnimationFrame(animationId)
      resizeObserver.disconnect()
      controls.dispose()
      disposeActive()
      ground.geometry.dispose()
      ;(ground.material as THREE.Material).dispose()
      renderer.dispose()
      container.removeChild(renderer.domElement)
    }
    // jobId + beltTransform only: this scene is built once per preview open
    // (or belt-transform change), not re-run on the slider/mode toggle's own
    // state changes (handled imperatively via the refs above).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId, beltTransform])

  // Rebuild the displayed object when the render mode is toggled, once a
  // scene actually exists to rebuild into.
  useEffect(() => {
    renderModeRef.current = renderMode
    if (status === 'ready') rebuildRef.current?.(renderMode, visibleLayers)
    // visibleLayers intentionally omitted: this effect should only fire on
    // a mode toggle, using whatever visibleLayers currently is, not re-run
    // every time the slider moves (that's the effect below).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [renderMode, status])

  // Cheap layer scrubbing: adjust the existing object's visible range
  // instead of re-parsing/rebuilding the scene on every slider tick.
  useEffect(() => {
    applyVisibleRef.current?.(visibleLayers)
  }, [visibleLayers])

  return (
    <>
      <div className="gcode-viewer-wrap">
        <div ref={containerRef} className="gcode-viewer" />
        {status === 'loading' && <div className="viewer-placeholder">Loading G-code…</div>}
        {status === 'error' && (
          <div className="viewer-placeholder">Couldn&rsquo;t load a preview for this file.</div>
        )}
        {status === 'ready' && (
          <div className="gcode-mode-toggle">
            <button
              type="button"
              className={renderMode === 'solid' ? 'active' : ''}
              onClick={() => setRenderMode('solid')}
            >
              Solid
            </button>
            <button
              type="button"
              className={renderMode === 'lines' ? 'active' : ''}
              onClick={() => setRenderMode('lines')}
            >
              Lines
            </button>
          </div>
        )}
        {filamentUsedGrams != null && (
          <div className="filament-badge">{filamentUsedGrams.toFixed(2)} g filament</div>
        )}
      </div>

      {status === 'ready' && (
        <div className="gcode-layer-slider">
          <input
            type="range"
            min={1}
            max={layerCount}
            value={visibleLayers}
            onChange={(e) => setVisibleLayers(Number(e.target.value))}
          />
          <span>
            Layer {visibleLayers} / {layerCount}
          </span>
        </div>
      )}

      <div className="gcode-actions">
        <a className="download-button" href={gcodeDownloadUrl(jobId)} download>
          Download G-code
        </a>
        <button type="button" className="preview-button" onClick={onBackToModel}>
          Back to 3D view
        </button>
      </div>
    </>
  )
}
