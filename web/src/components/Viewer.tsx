import { useEffect, useRef } from 'react'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader.js'
import type { BedSize, Dimensions } from '../dimensions'

interface ViewerProps {
  file: File | null
  onDimensions?: (dims: Dimensions | null) => void
  bedSize?: BedSize | null
}

// Basic model preview: not meant to be a full slicer viewport (no layer
// preview, no plate/gizmos) -- just enough to confirm "yes, that's the
// object I uploaded" before slicing. Drag-to-rotate/zoom via OrbitControls
// comes along for free with three.js and costs nothing extra, but nothing
// here depends on interaction actually happening.
export default function Viewer({ file, onDimensions, bedSize }: ViewerProps) {
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
    let ceiling: THREE.Mesh | null = null
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

          // A reference plate just under the model: the selected printer's
          // actual bed size once one is picked (bedSize), or just wider
          // than the model's own footprint before that -- "roughly where
          // the build surface is" rather than nothing at all.
          const plateMargin = 1.3
          const plateWidth = bedSize?.width ?? size.x * plateMargin
          const plateDepth = bedSize?.depth ?? size.y * plateMargin
          const plateZ = -size.z / 2

          // Auto-frame: fit the model's own bounding sphere by default, or
          // the whole print volume (bed footprint + ceiling height) once a
          // printer is selected, whichever needs the camera further back --
          // otherwise a small model on a large-bed, tall-ceiling printer
          // left the bed/ceiling just out of frame, needing a manual zoom
          // to see the very thing this is meant to show at a glance.
          const modelRadius = size.length() / 2 || 1
          let effectiveRadius = modelRadius
          if (bedSize) {
            const farZ = Math.max(Math.abs(plateZ), Math.abs(plateZ + bedSize.height))
            const printVolumeRadius = Math.sqrt(
              (plateWidth / 2) ** 2 + (plateDepth / 2) ** 2 + farZ ** 2,
            )
            effectiveRadius = Math.max(modelRadius, printVolumeRadius)
          }
          const distance = effectiveRadius / Math.sin((Math.PI * camera.fov) / 360)

          camera.position.set(distance, distance, distance * 0.6)
          camera.near = distance / 100
          camera.far = distance * 100
          camera.updateProjectionMatrix()
          controls.target.set(0, 0, 0)
          controls.update()

          // FrontSide (the default) makes the plate a one-way surface:
          // PlaneGeometry's normal points along +Z (up) with no rotation
          // needed, so orbiting underneath looks at its back face, which
          // isn't rendered -- the plate disappears instead of blocking the
          // view of the model from below.
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
          // printer -- and so a real bed size -- is selected): same
          // footprint as the bed, marking the ceiling of the printable
          // volume. Same default +Z-facing normal as the bed (no rotation):
          // the auto-framed camera above ends up *above* the ceiling height
          // when fitting the whole print volume (confirmed empirically --
          // the printable_height term in effectiveRadius pushes the camera
          // well past it), so FrontSide is visible from that default
          // overview angle. It then self-hides on zooming in close to the
          // model for a normal below-the-ceiling inspection view, which is
          // a reasonable bonus rather than a downside.
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
            ceiling.position.z = plate.position.z + bedSize.height
            scene.add(ceiling)
          }

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
  }, [file, onDimensions, bedSize])

  return (
    <div className="viewer-wrap">
      {/* Pure imperative mount point -- three.js owns everything inside it,
          so nothing here is a React-rendered child. */}
      <div className="viewer" ref={containerRef} />
      {!file && <div className="viewer-placeholder">Upload a model to preview it here</div>}
    </div>
  )
}
