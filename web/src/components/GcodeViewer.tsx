import { useEffect, useRef, useState } from 'react'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { gcodeDownloadUrl } from '../api'
import { parseGcode } from '../gcodeParser'

interface GcodeViewerProps {
  jobId: string
  onClose: () => void
}

// Real toolpath preview, not just "here's the file": fetches the sliced
// G-code, parses out the extruding moves (gcodeParser.ts), and renders them
// as colored line segments layer by layer, with a slider to scrub through
// how much of the print has been "drawn" -- the same idea as a slicer's own
// preview tab, just without per-feature (wall/infill/support) coloring.
export default function GcodeViewer({ jobId, onClose }: GcodeViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [status, setStatus] = useState<'loading' | 'error' | 'ready'>('loading')
  const [layerCount, setLayerCount] = useState(0)
  const [visibleLayers, setVisibleLayers] = useState(0)
  // Set by the render effect once geometry exists, read by the slider effect
  // -- avoids re-parsing/rebuilding the whole scene on every slider tick.
  const layerEndVertexRef = useRef<number[]>([])
  const geometryRef = useRef<THREE.BufferGeometry | null>(null)

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
    const renderer = new THREE.WebGLRenderer({ antialias: true })
    renderer.setPixelRatio(window.devicePixelRatio)
    renderer.setSize(container.clientWidth, container.clientHeight)
    container.appendChild(renderer.domElement)

    const controls = new OrbitControls(camera, renderer.domElement)
    controls.enableDamping = true

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

    fetch(gcodeDownloadUrl(jobId))
      .then((res) => {
        if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
        return res.text()
      })
      .then((text) => {
        if (disposed) return
        const { layers } = parseGcode(text)
        if (layers.length === 0) throw new Error('No extrusion moves found in this G-code')

        const positions: number[] = []
        const colors: number[] = []
        const layerEndVertex: number[] = []
        const bounds = new THREE.Box3()
        const point = new THREE.Vector3()

        layers.forEach((layer, layerIndex) => {
          const color = new THREE.Color().setHSL(
            0.72 - 0.72 * (layerIndex / Math.max(1, layers.length - 1)),
            0.7,
            0.55,
          )
          for (const seg of layer.segments) {
            positions.push(seg.x1, seg.y1, seg.z1, seg.x2, seg.y2, seg.z2)
            colors.push(color.r, color.g, color.b, color.r, color.g, color.b)
            bounds.expandByPoint(point.set(seg.x1, seg.y1, seg.z1))
            bounds.expandByPoint(point.set(seg.x2, seg.y2, seg.z2))
          }
          layerEndVertex.push(positions.length / 3)
        })

        const geometry = new THREE.BufferGeometry()
        geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3))
        geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3))
        const lines = new THREE.LineSegments(
          geometry,
          new THREE.LineBasicMaterial({ vertexColors: true }),
        )
        scene.add(lines)
        geometryRef.current = geometry
        layerEndVertexRef.current = layerEndVertex

        const center = new THREE.Vector3()
        bounds.getCenter(center)
        lines.position.sub(center)

        const size = new THREE.Vector3()
        bounds.getSize(size)
        const radius = size.length() / 2 || 1
        const distance = radius / Math.sin((Math.PI * camera.fov) / 360)
        camera.position.set(distance, distance, distance * 0.6)
        camera.near = distance / 1000
        camera.far = distance * 100
        camera.updateProjectionMatrix()
        controls.target.set(0, 0, 0)
        controls.update()

        setLayerCount(layers.length)
        setVisibleLayers(layers.length)
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
      geometryRef.current?.dispose()
      renderer.dispose()
      container.removeChild(renderer.domElement)
    }
    // jobId only: this scene is built once per preview open, not re-run on
    // the slider's own state changes (that's handled imperatively below).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId])

  // Cheap layer scrubbing: adjust the existing geometry's drawRange instead
  // of re-parsing/rebuilding the scene on every slider tick.
  useEffect(() => {
    const geometry = geometryRef.current
    const layerEndVertex = layerEndVertexRef.current
    if (!geometry || layerEndVertex.length === 0) return
    const vertexCount = visibleLayers > 0 ? layerEndVertex[visibleLayers - 1] : 0
    geometry.setDrawRange(0, vertexCount)
  }, [visibleLayers])

  return (
    <div className="gcode-modal-backdrop" onClick={onClose}>
      <div className="gcode-modal" onClick={(e) => e.stopPropagation()}>
        <div className="gcode-modal-header">
          <h2>G-code preview</h2>
          <button type="button" className="toast-dismiss" onClick={onClose}>
            Close
          </button>
        </div>

        <div className="gcode-viewer-wrap">
          <div ref={containerRef} className="gcode-viewer" />
          {status === 'loading' && <div className="viewer-placeholder">Loading G-code…</div>}
          {status === 'error' && (
            <div className="viewer-placeholder">Couldn&rsquo;t load a preview for this file.</div>
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

        <a className="download-button" href={gcodeDownloadUrl(jobId)} download>
          Download G-code
        </a>
      </div>
    </div>
  )
}
