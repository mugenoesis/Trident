import { useEffect, useRef } from 'react'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader.js'

interface ViewerProps {
  file: File | null
}

// Basic model preview: not meant to be a full slicer viewport (no layer
// preview, no plate/gizmos) -- just enough to confirm "yes, that's the
// object I uploaded" before slicing. Drag-to-rotate/zoom via OrbitControls
// comes along for free with three.js and costs nothing extra, but nothing
// here depends on interaction actually happening.
export default function Viewer({ file }: ViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const scene = new THREE.Scene()
    scene.background = new THREE.Color(0x2a2e35)

    const camera = new THREE.PerspectiveCamera(
      45,
      container.clientWidth / container.clientHeight,
      0.1,
      10000,
    )

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

          const material = new THREE.MeshStandardMaterial({
            color: 0x7e8aa0,
            metalness: 0.1,
            roughness: 0.7,
          })
          mesh = new THREE.Mesh(geometry, material)
          scene.add(mesh)

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

          camera.position.set(distance, distance * 0.6, distance)
          camera.near = distance / 100
          camera.far = distance * 100
          camera.updateProjectionMatrix()
          controls.target.set(0, 0, 0)
          controls.update()

          URL.revokeObjectURL(url)
        },
        undefined,
        (err) => {
          console.error('Failed to load STL for preview', err)
          URL.revokeObjectURL(url)
        },
      )
    } else {
      camera.position.set(40, 30, 40)
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
      renderer.dispose()
      container.removeChild(renderer.domElement)
    }
  }, [file])

  return (
    <div className="viewer-wrap">
      {/* Pure imperative mount point -- three.js owns everything inside it,
          so nothing here is a React-rendered child. */}
      <div className="viewer" ref={containerRef} />
      {!file && <div className="viewer-placeholder">Upload a model to preview it here</div>}
    </div>
  )
}
