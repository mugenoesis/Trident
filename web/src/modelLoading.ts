import * as THREE from 'three'
import { DRACOLoader } from 'three/examples/jsm/loaders/DRACOLoader.js'
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader.js'
import { ThreeMFLoader } from 'three/examples/jsm/loaders/3MFLoader.js'

export const MODEL_COLOUR = 0xff6f2c

/** Reads an STL, 3MF or Draco (.drc) model into a three.js object, in the file's own coordinates. */
export function loadObject(file: File): Promise<THREE.Object3D> {
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

/** The rotation (degrees) the sliders hold: turned about X, then Y, then Z, each about the plate's own axes. */
export interface Rotation {
  x: number
  y: number
  z: number
}

const deg = THREE.MathUtils.radToDeg
const rad = THREE.MathUtils.degToRad

/** The quaternion for a rotation: Euler order 'ZYX' is X first, then Y, then Z about the fixed axes. */
export function rotationQuaternion(r: Rotation): THREE.Quaternion {
  return new THREE.Quaternion().setFromEuler(new THREE.Euler(rad(r.x), rad(r.y), rad(r.z), 'ZYX'))
}

/**
 * The rotation that turns the model so a face ends up on the plate. `normal` is the face's outward
 * direction with `current` already applied; the extra turn is the shortest one that points it
 * straight down, and the result is expressed as the same three angles the sliders use.
 */
export function rotationToLayOnFace(current: Rotation, normal: THREE.Vector3): Rotation {
  const extra = new THREE.Quaternion().setFromUnitVectors(normal.clone().normalize(), new THREE.Vector3(0, 0, -1))
  const e = new THREE.Euler().setFromQuaternion(extra.multiply(rotationQuaternion(current)), 'ZYX')
  const clean = (v: number) => {
    const rounded = Math.round(deg(v) * 1000) / 1000
    return Object.is(rounded, -0) ? 0 : rounded
  }
  return { x: clean(e.x), y: clean(e.y), z: clean(e.z) }
}
