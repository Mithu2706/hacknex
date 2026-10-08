import { useEffect, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import * as THREE from 'three'

const EYE = 1.6
const RADIUS = 0.22
const SPEED = 2.2

function blocked(x, z, rects) {
  for (const r of rects) {
    const dx = r.bx - r.ax, dz = r.bz - r.az
    const L2 = dx * dx + dz * dz || 1
    let t = ((x - r.ax) * dx + (z - r.az) * dz) / L2
    t = Math.max(0, Math.min(1, t))
    const px = r.ax + dx * t, pz = r.az + dz * t
    if (Math.hypot(x - px, z - pz) < r.half + RADIUS) return true
  }
  return false
}

/** First-person walkthrough: WASD / arrow keys to move, drag to look. Walls block movement. */
export default function Walkthrough({ start, rects, height = EYE }) {
  const { camera, gl } = useThree()
  const keys = useRef({})
  const look = useRef({ yaw: 0, pitch: 0, drag: false, lx: 0, ly: 0 })

  useEffect(() => {
    camera.position.set(start[0], height, start[1])
    look.current.yaw = 0
    look.current.pitch = 0
    const el = gl.domElement
    const down = (e) => { look.current.drag = true; look.current.lx = e.clientX; look.current.ly = e.clientY }
    const up = () => { look.current.drag = false }
    const move = (e) => {
      if (!look.current.drag) return
      look.current.yaw -= (e.clientX - look.current.lx) * 0.004
      look.current.pitch = THREE.MathUtils.clamp(look.current.pitch - (e.clientY - look.current.ly) * 0.004, -1.2, 1.2)
      look.current.lx = e.clientX; look.current.ly = e.clientY
    }
    const kd = (e) => { keys.current[e.code] = true; if (e.code.startsWith('Arrow')) e.preventDefault() }
    const ku = (e) => { keys.current[e.code] = false }
    el.addEventListener('pointerdown', down)
    window.addEventListener('pointerup', up)
    window.addEventListener('pointermove', move)
    window.addEventListener('keydown', kd)
    window.addEventListener('keyup', ku)
    return () => {
      el.removeEventListener('pointerdown', down)
      window.removeEventListener('pointerup', up)
      window.removeEventListener('pointermove', move)
      window.removeEventListener('keydown', kd)
      window.removeEventListener('keyup', ku)
    }
  }, [camera, gl, start, height])

  useFrame((_, dt) => {
    const k = keys.current
    const { yaw, pitch } = look.current
    const fwd = (k.KeyW || k.ArrowUp ? 1 : 0) - (k.KeyS || k.ArrowDown ? 1 : 0)
    const side = (k.KeyD || k.ArrowRight ? 1 : 0) - (k.KeyA || k.ArrowLeft ? 1 : 0)
    if (fwd || side) {
      const step = SPEED * Math.min(dt, 0.05)
      const dx = (-Math.sin(yaw) * fwd + Math.cos(yaw) * side) * step
      const dz = (-Math.cos(yaw) * fwd - Math.sin(yaw) * side) * step
      const p = camera.position
      if (!blocked(p.x + dx, p.z, rects)) p.x += dx
      if (!blocked(p.x, p.z + dz, rects)) p.z += dz
    }
    camera.rotation.set(pitch, yaw, 0, 'YXZ')
  })
  return null
}
