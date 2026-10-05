import * as THREE from 'three'

// Faces that are flat: neighbouring triangles whose normals differ by less than
// this angle belong to the same face. A smooth curved surface is made of tiny
// triangles each turned a little from the next, so it never grows into one big
// "face" -- which matches the slicer, that only offers flat faces to rest on.
const FLAT_TOLERANCE_DEGREES = 1.5
const MAX_TRIANGLES_FOR_REGIONS = 800_000

export interface FaceRegion {
  // Triangle indices of the flat face, in the geometry's own order.
  triangles: number[]
  // Outward normal in the geometry's own coordinates.
  normal: THREE.Vector3
  // Surface area in the geometry's units squared (mm²).
  area: number
}

/**
 * Finds the flat face a triangle belongs to (the connected triangles around it
 * that lie in one plane). Built once per mesh when face picking starts.
 */
export class FaceIndex {
  private readonly position: THREE.BufferAttribute | THREE.InterleavedBufferAttribute
  private readonly index: THREE.BufferAttribute | null
  private readonly normals: Float32Array
  private readonly areas: Float32Array
  private readonly neighbours: Int32Array // 3 per triangle, -1 where an edge has no partner
  readonly triangleCount: number

  constructor(geometry: THREE.BufferGeometry) {
    this.position = geometry.getAttribute('position')
    this.index = geometry.index
    this.triangleCount = this.index ? this.index.count / 3 : this.position.count / 3
    this.normals = new Float32Array(this.triangleCount * 3)
    this.areas = new Float32Array(this.triangleCount)
    this.neighbours = new Int32Array(this.triangleCount * 3).fill(-1)
    if (this.triangleCount > MAX_TRIANGLES_FOR_REGIONS) return
    this.build()
  }

  private vertex(triangle: number, corner: number): number {
    const slot = triangle * 3 + corner
    return this.index ? this.index.getX(slot) : slot
  }

  private build() {
    const a = new THREE.Vector3()
    const b = new THREE.Vector3()
    const c = new THREE.Vector3()
    const ab = new THREE.Vector3()
    const ac = new THREE.Vector3()
    // Vertices with the same position (an STL repeats them per triangle) share an id,
    // so triangles meeting along an edge can find each other.
    const ids = new Map<string, number>()
    const idOf = (v: number) => {
      const key = `${Math.round(this.position.getX(v) * 1000)},${Math.round(this.position.getY(v) * 1000)},${Math.round(this.position.getZ(v) * 1000)}`
      let id = ids.get(key)
      if (id === undefined) {
        id = ids.size
        ids.set(key, id)
      }
      return id
    }
    const edgeOwners = new Map<number, number>() // edge key -> first triangle seen with it
    const EDGE_BASE = 2 ** 26
    for (let t = 0; t < this.triangleCount; t++) {
      const v = [this.vertex(t, 0), this.vertex(t, 1), this.vertex(t, 2)]
      a.fromBufferAttribute(this.position, v[0])
      b.fromBufferAttribute(this.position, v[1])
      c.fromBufferAttribute(this.position, v[2])
      ab.subVectors(b, a)
      ac.subVectors(c, a)
      ab.cross(ac)
      const length = ab.length()
      this.areas[t] = length / 2
      if (length > 0) ab.divideScalar(length)
      this.normals[t * 3] = ab.x
      this.normals[t * 3 + 1] = ab.y
      this.normals[t * 3 + 2] = ab.z
      const id = v.map(idOf)
      for (let corner = 0; corner < 3; corner++) {
        const p = id[corner]
        const q = id[(corner + 1) % 3]
        if (p === q) continue
        const key = Math.min(p, q) * EDGE_BASE + Math.max(p, q)
        const other = edgeOwners.get(key)
        if (other === undefined) {
          edgeOwners.set(key, t)
        } else {
          // The first free slot on each side.
          this.link(t, other)
          this.link(other, t)
        }
      }
    }
  }

  private link(from: number, to: number) {
    for (let slot = 0; slot < 3; slot++) {
      if (this.neighbours[from * 3 + slot] === -1) {
        this.neighbours[from * 3 + slot] = to
        return
      }
    }
  }

  regionAt(seed: number): FaceRegion {
    const n = this.normals
    const nx = n[seed * 3]
    const ny = n[seed * 3 + 1]
    const nz = n[seed * 3 + 2]
    const minDot = Math.cos((FLAT_TOLERANCE_DEGREES * Math.PI) / 180)
    const seen = new Set<number>([seed])
    const stack = [seed]
    let area = 0
    while (stack.length > 0) {
      const t = stack.pop() as number
      area += this.areas[t]
      for (let slot = 0; slot < 3; slot++) {
        const next = this.neighbours[t * 3 + slot]
        if (next < 0 || seen.has(next)) continue
        // Compared with the face's first triangle, not the neighbour, so a gentle
        // curve cannot drift into a "flat" face one small step at a time.
        if (n[next * 3] * nx + n[next * 3 + 1] * ny + n[next * 3 + 2] * nz >= minDot) {
          seen.add(next)
          stack.push(next)
        }
      }
    }
    return { triangles: [...seen], normal: new THREE.Vector3(nx, ny, nz), area }
  }

  /** A mesh of just the given triangles, for drawing the highlighted face. */
  highlightGeometry(triangles: number[]): THREE.BufferGeometry {
    const out = new Float32Array(triangles.length * 9)
    triangles.forEach((t, i) => {
      for (let corner = 0; corner < 3; corner++) {
        const v = this.vertex(t, corner)
        out[i * 9 + corner * 3] = this.position.getX(v)
        out[i * 9 + corner * 3 + 1] = this.position.getY(v)
        out[i * 9 + corner * 3 + 2] = this.position.getZ(v)
      }
    })
    const geometry = new THREE.BufferGeometry()
    geometry.setAttribute('position', new THREE.BufferAttribute(out, 3))
    return geometry
  }
}
