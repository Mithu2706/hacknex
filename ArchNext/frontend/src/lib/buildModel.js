import * as THREE from 'three'
import { ROOM_COLORS } from './format.js'

/**
 * Build a THREE.Group of the reconstructed building from detected (TopologyGuard-corrected)
 * geometry. Units are metres; the plan x axis maps to X and the plan y axis maps to Z.
 */
export function planFrame(result) {
  const walls = result.geometry.corrected.walls
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
  for (const w of walls) {
    minX = Math.min(minX, w.x1, w.x2); maxX = Math.max(maxX, w.x1, w.x2)
    minY = Math.min(minY, w.y1, w.y2); maxY = Math.max(maxY, w.y1, w.y2)
  }
  const s = result.scale.meters_per_px
  return {
    s, cx: (minX + maxX) / 2, cy: (minY + maxY) / 2,
    sizeX: (maxX - minX) * s, sizeZ: (maxY - minY) * s,
    toWorld: (x, y) => [(x - (minX + maxX) / 2) * s, (y - (minY + maxY) / 2) * s],
  }
}

const MAT = {
  wallInt: () => new THREE.MeshStandardMaterial({ name: 'Interior wall', color: '#F7F5F0', roughness: 0.92 }),
  wallExt: () => new THREE.MeshStandardMaterial({ name: 'Exterior wall', color: '#ECE7DF', roughness: 0.95 }),
  lintel: () => new THREE.MeshStandardMaterial({ name: 'Lintel', color: '#ECE8E1', roughness: 0.9 }),
  glass: () => new THREE.MeshStandardMaterial({ name: 'Glass', color: '#BFD6E4', roughness: 0.08, metalness: 0.1, transparent: true, opacity: 0.38 }),
  frame: () => new THREE.MeshStandardMaterial({ name: 'Frame', color: '#8C857A', roughness: 0.6 }),
  door: () => new THREE.MeshStandardMaterial({ name: 'Door', color: '#B89B76', roughness: 0.7 }),
}

function boxAlong(frame, x1, y1, x2, y2, thickness, y0, y1h, material, name) {
  const [ax, az] = frame.toWorld(x1, y1)
  const [bx, bz] = frame.toWorld(x2, y2)
  const len = Math.hypot(bx - ax, bz - az)
  const h = y1h - y0
  if (len < 1e-3 || h <= 1e-3) return null
  const geo = new THREE.BoxGeometry(len, h, Math.max(thickness * frame.s, 0.02))
  const mesh = new THREE.Mesh(geo, material)
  mesh.position.set((ax + bx) / 2, y0 + h / 2, (az + bz) / 2)
  mesh.rotation.y = -Math.atan2(bz - az, bx - ax)
  mesh.castShadow = true
  mesh.receiveShadow = true
  mesh.name = name
  return mesh
}

export function buildModel(result, { wallHeight = 2.7, doorHeight = 2.1, sill = 0.9, head = 2.1 } = {}) {
  const frame = planFrame(result)
  const g = result.geometry.corrected
  const root = new THREE.Group()
  root.name = 'ArchNext building'
  const mats = Object.fromEntries(Object.entries(MAT).map(([k, f]) => [k, f()]))
  const wallsGroup = new THREE.Group(); wallsGroup.name = 'Walls'
  const openGroup = new THREE.Group(); openGroup.name = 'Openings'
  const floorGroup = new THREE.Group(); floorGroup.name = 'Floors'

  for (const w of g.walls) {
    const m = boxAlong(frame, w.x1, w.y1, w.x2, w.y2, w.thickness, 0, wallHeight,
      w.exterior ? mats.wallExt : mats.wallInt, `${w.exterior ? 'Exterior' : 'Interior'} wall ${w.id}`)
    if (m) wallsGroup.add(m)
  }
  for (const s of g.solids || []) {
    const m = boxAlong(frame, s.x0, (s.y0 + s.y1) / 2, s.x1, (s.y0 + s.y1) / 2, s.y1 - s.y0, 0, wallHeight, mats.wallExt, 'Solid')
    if (m) wallsGroup.add(m)
  }

  const dh = Math.min(doorHeight, wallHeight - 0.05)
  const hh = Math.min(head, wallHeight - 0.05)
  for (const o of g.openings) {
    if (o.type === 'window') {
      const sill0 = Math.min(sill, hh - 0.3)
      const parts = [
        boxAlong(frame, o.x1, o.y1, o.x2, o.y2, o.thickness, 0, sill0, mats.lintel, `Window sill ${o.id}`),
        boxAlong(frame, o.x1, o.y1, o.x2, o.y2, o.thickness, hh, wallHeight, mats.lintel, `Window head ${o.id}`),
        boxAlong(frame, o.x1, o.y1, o.x2, o.y2, o.thickness * 0.15, sill0, hh, mats.glass, `Glass ${o.id}`),
        boxAlong(frame, o.x1, o.y1, o.x2, o.y2, o.thickness * 1.02, sill0 - 0.03, sill0, mats.frame, `Window frame ${o.id}`),
      ]
      parts.forEach((p) => { if (p) { if (p.name.startsWith('Glass')) p.castShadow = false; openGroup.add(p) } })
    } else {
      const lintel = boxAlong(frame, o.x1, o.y1, o.x2, o.y2, o.thickness, dh, wallHeight, mats.lintel, `${o.type === 'door' ? 'Door' : 'Opening'} head ${o.id}`)
      if (lintel) openGroup.add(lintel)
      if (o.type === 'door') {
        // Door leaf shown slightly open from the first jamb.
        const [ax, az] = frame.toWorld(o.x1, o.y1)
        const [bx, bz] = frame.toWorld(o.x2, o.y2)
        const width = Math.hypot(bx - ax, bz - az)
        const leaf = new THREE.Mesh(new THREE.BoxGeometry(width * 0.96, dh - 0.02, 0.04), mats.door)
        const pivot = new THREE.Group()
        pivot.position.set(ax, 0, az)
        pivot.rotation.y = -Math.atan2(bz - az, bx - ax) + THREE.MathUtils.degToRad(35)
        leaf.position.set(width * 0.48, (dh - 0.02) / 2, 0)
        leaf.castShadow = true
        leaf.name = `Door leaf ${o.id}`
        pivot.add(leaf)
        pivot.name = `Door ${o.id}`
        openGroup.add(pivot)
      }
    }
  }

  for (const r of g.rooms) {
    if (r.polygon.length < 3) continue
    let pts2 = r.polygon.map(([x, y]) => {
      const [X, Z] = frame.toWorld(x, y)
      return new THREE.Vector2(X, -Z)
    })
    if (THREE.ShapeUtils.isClockWise(pts2)) pts2 = pts2.reverse()
    const shape = new THREE.Shape(pts2)
    const geo = new THREE.ShapeGeometry(shape)
    geo.rotateX(-Math.PI / 2)
    const mat = new THREE.MeshStandardMaterial({ name: `Floor ${r.type}`, color: ROOM_COLORS[r.type] || ROOM_COLORS.unknown, roughness: 0.85 })
    const mesh = new THREE.Mesh(geo, mat)
    mesh.position.y = 0.012
    mesh.receiveShadow = true
    mesh.name = `Floor ${r.name}`
    mesh.userData = { room: r.name, area_m2: r.area_m2 }
    floorGroup.add(mesh)
  }

  root.add(floorGroup, wallsGroup, openGroup)
  return { group: root, frame }
}

/** 2D wall rectangles in metres for walkthrough collision. */
export function collisionRects(result, frame) {
  return result.geometry.corrected.walls.map((w) => {
    const [ax, az] = frame.toWorld(w.x1, w.y1)
    const [bx, bz] = frame.toWorld(w.x2, w.y2)
    return { ax, az, bx, bz, half: (w.thickness * frame.s) / 2 }
  })
}
