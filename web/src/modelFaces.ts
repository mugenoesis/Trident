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

  /** The outward normal of one triangle, in the geometry's own coordinates. */
  normalAt(triangle: number): THREE.Vector3 {
    return new THREE.Vector3(this.normals[triangle * 3], this.normals[triangle * 3 + 1], this.normals[triangle * 3 + 2])
  }

  /** The first corner of a triangle, in the geometry's own coordinates. */
  cornerOf(triangle: number, out: THREE.Vector3): THREE.Vector3 {
    return out.fromBufferAttribute(this.position, this.vertex(triangle, 0))
  }

  /** Every flat face of the mesh (a seed triangle and the area), largest first. */
  regions(): { seed: number; area: number }[] {
    const visited = new Uint8Array(this.triangleCount)
    const minDot = Math.cos((FLAT_TOLERANCE_DEGREES * Math.PI) / 180)
    const found: { seed: number; area: number }[] = []
    for (let seed = 0; seed < this.triangleCount; seed++) {
      if (visited[seed]) continue
      visited[seed] = 1
      const nx = this.normals[seed * 3]
      const ny = this.normals[seed * 3 + 1]
      const nz = this.normals[seed * 3 + 2]
      const stack = [seed]
      let area = 0
      while (stack.length > 0) {
        const t = stack.pop() as number
        area += this.areas[t]
        for (let slot = 0; slot < 3; slot++) {
          const next = this.neighbours[t * 3 + slot]
          if (next < 0 || visited[next]) continue
          if (this.normals[next * 3] * nx + this.normals[next * 3 + 1] * ny + this.normals[next * 3 + 2] * nz >= minDot) {
            visited[next] = 1
            stack.push(next)
          }
        }
      }
      found.push({ seed, area })
    }
    return found.sort((a, b) => b.area - a.area)
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

// How far past a face's plane the rest of the model may reach and still count as resting on it.
const REST_TOLERANCE_MM = 0.05

/**
 * True when no vertex of the meshes reaches out past the plane through `pointOnFace` with outward
 * `normal` (both in world coordinates): the face is part of the model's outer hull, so the model can
 * stand on it.
 */
export function canRestOn(meshes: THREE.Mesh[], normal: THREE.Vector3, pointOnFace: THREE.Vector3): boolean {
  const offset = normal.dot(pointOnFace)
  const local = new THREE.Vector3()
  for (const mesh of meshes) {
    mesh.updateWorldMatrix(true, false)
    // n . (M v + t) = (M^T n) . v + n . t, so each vertex costs one dot product.
    const e = mesh.matrixWorld.elements
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

/**
 * The outward direction (world coordinates) of the largest flat face the meshes can rest on, or null
 * when there is none (a smooth sphere). Used for "Lay flat" on one object of several.
 */
export function largestRestableFace(meshes: THREE.Mesh[]): THREE.Vector3 | null {
  const candidates: { mesh: THREE.Mesh; index: FaceIndex; seed: number; area: number }[] = []
  for (const mesh of meshes) {
    const index = new FaceIndex(mesh.geometry)
    for (const r of index.regions()) candidates.push({ mesh, index, ...r })
  }
  candidates.sort((a, b) => b.area - a.area)
  const corner = new THREE.Vector3()
  for (const c of candidates.slice(0, 40)) {
    c.mesh.updateWorldMatrix(true, false)
    const normal = c.index.normalAt(c.seed).transformDirection(c.mesh.matrixWorld)
    const point = c.index.cornerOf(c.seed, corner).clone().applyMatrix4(c.mesh.matrixWorld)
    if (canRestOn(meshes, normal, point)) return normal
  }
  return null
}
