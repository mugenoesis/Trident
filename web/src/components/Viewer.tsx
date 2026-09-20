import { useEffect, useRef } from 'react'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader.js'
import { ThreeMFLoader } from 'three/examples/jsm/loaders/3MFLoader.js'
import { DRACOLoader } from 'three/examples/jsm/loaders/DRACOLoader.js'
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
      }

      if (isThreeMf) {
        new ThreeMFLoader().load(
          url,
          (group) => {
            if (disposed) {
              URL.revokeObjectURL(url)
              return
            }
            // Deliberately overrides whatever per-object colors/materials
            // the .3mf itself embeds -- geometry-only preview, not a render
            // of the file's actual multi-material assignments.
            group.traverse((child) => {
              if (child instanceof THREE.Mesh) child.material = material
            })
            scene.add(group)
            loadedObject = group
            finishLoad(group, new THREE.Box3().setFromObject(group))
            URL.revokeObjectURL(url)
          },
          undefined,
          (err) => {
            console.error('Failed to load 3MF for preview', err)
            URL.revokeObjectURL(url)
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
            console.error('Failed to load DRC for preview', err)
            URL.revokeObjectURL(url)
          },
        )
      } else {
        new STLLoader().load(
          url,
          handleGeometry,
          undefined,
          (err) => {
            console.error('Failed to load STL for preview', err)
            URL.revokeObjectURL(url)
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
