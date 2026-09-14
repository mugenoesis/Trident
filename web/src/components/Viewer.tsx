import { useEffect, useRef } from 'react'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader.js'
import type { Dimensions } from '../dimensions'

interface ViewerProps {
  file: File | null
  onDimensions?: (dims: Dimensions | null) => void
}

// Basic model preview: not meant to be a full slicer viewport (no layer
// preview, no plate/gizmos) -- just enough to confirm "yes, that's the
// object I uploaded" before slicing. Drag-to-rotate/zoom via OrbitControls
// comes along for free with three.js and costs nothing extra, but nothing
// here depends on interaction actually happening.
export default function Viewer({ file, onDimensions }: ViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

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

    let mesh: THREE.Mesh | null = null
    let plate: THREE.Mesh | null = null
    let animationId = 0
    let disposed = false

    if (file) {
      const url = URL.createObjectURL(file)
      new STLLoader().load(
        url,
        (geometry) => {
          if (disposed) return
          geometry.computeVertexNormals()
          geometry.computeBoundingBox()

          // A muted blue-gray blended into the dark background too easily.
          // A saturated, warm color (like a printed-plastic filament) reads
          // clearly against the dark viewport at any lighting angle.
          const material = new THREE.MeshStandardMaterial({
            color: 0xff6f2c,
            metalness: 0.05,
            roughness: 0.55,
          })
          mesh = new THREE.Mesh(geometry, material)
          scene.add(mesh)

          // Edge lines make flat-shaded faces read as a solid shape instead
          // of a smear of color, especially for simple/low-poly models.
          const edges = new THREE.LineSegments(
            new THREE.EdgesGeometry(geometry, 30),
            new THREE.LineBasicMaterial({ color: 0x2a1508, transparent: true, opacity: 0.5 }),
          )
          mesh.add(edges)

          // Auto-frame: center the model at the origin and back the camera
          // off far enough to see the whole bounding sphere.
          const box = geometry.boundingBox!
          const center = new THREE.Vector3()
          box.getCenter(center)
          mesh.position.sub(center)

          const size = new THREE.Vector3()
          box.getSize(size)
          const radius = size.length() / 2 || 1
          const distance = radius / Math.sin((Math.PI * camera.fov) / 360)

          camera.position.set(distance, distance, distance * 0.6)
          camera.near = distance / 100
          camera.far = distance * 100
          camera.updateProjectionMatrix()
          controls.target.set(0, 0, 0)
          controls.update()

          // A small reference plate just under the model, sized to its
          // footprint rather than any real printer's bed -- just enough to
          // show "this is roughly where the build surface is", not a
          // to-scale plate. FrontSide (the default) makes it a one-way
          // surface: PlaneGeometry's normal points along +Z (up) with no
          // rotation needed, so orbiting underneath looks at its back face,
          // which isn't rendered -- the plate disappears instead of
          // blocking the view of the model from below.
          const plateMargin = 1.3
          plate = new THREE.Mesh(
            new THREE.PlaneGeometry(size.x * plateMargin, size.y * plateMargin),
            new THREE.MeshBasicMaterial({
              color: 0xaab0bb,
              transparent: true,
              opacity: 0.25,
              side: THREE.FrontSide,
            }),
          )
          plate.position.z = -size.z / 2
          scene.add(plate)

          onDimensions?.({ x: size.x, y: size.y, z: size.z })
          URL.revokeObjectURL(url)
        },
        undefined,
        (err) => {
          console.error('Failed to load STL for preview', err)
          URL.revokeObjectURL(url)
        },
      )
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
      mesh?.geometry.dispose()
      if (mesh?.material) {
        const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material]
        mats.forEach((m) => m.dispose())
      }
      const edges = mesh?.children.find((c) => c instanceof THREE.LineSegments)
      if (edges instanceof THREE.LineSegments) {
        edges.geometry.dispose()
        ;(edges.material as THREE.Material).dispose()
      }
      plate?.geometry.dispose()
      ;(plate?.material as THREE.Material | undefined)?.dispose()
      renderer.dispose()
      container.removeChild(renderer.domElement)
    }
  }, [file, onDimensions])

  return (
    <div className="viewer-wrap">
      {/* Pure imperative mount point -- three.js owns everything inside it,
          so nothing here is a React-rendered child. */}
      <div className="viewer" ref={containerRef} />
      {!file && <div className="viewer-placeholder">Upload a model to preview it here</div>}
    </div>
  )
}
