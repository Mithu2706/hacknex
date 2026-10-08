import { Suspense, useEffect, useMemo, useRef, useState } from 'react'
import { Canvas, useThree } from '@react-three/fiber'
import { Html, OrbitControls } from '@react-three/drei'
import * as THREE from 'three'
import { GLTFExporter } from 'three/examples/jsm/exporters/GLTFExporter.js'
import { Box, Download, Footprints, Loader2, Map as MapIcon, RotateCcw, Ruler, Tag } from 'lucide-react'
import { buildModel, collisionRects } from '../lib/buildModel.js'
import { ROOM_TYPE_LABEL, fmtM, fmtM2 } from '../lib/format.js'
import { ScaleBadge } from '../components/ScalePanel.jsx'
import Walkthrough from '../components/Walkthrough.jsx'

function CameraRig({ mode, frame, resetKey, controls }) {
  const { camera, size } = useThree()
  useEffect(() => {
    if (mode === 'walk') return
    const span = Math.max(frame.sizeX, frame.sizeZ, 4)
    const tan = Math.tan(THREE.MathUtils.degToRad(camera.fov / 2))
    const aspect = size.width / Math.max(size.height, 1)
    const fit = Math.max(frame.sizeZ, frame.sizeX / aspect) / (2 * tan)
    if (mode === 'top') {
      camera.position.set(0, fit * 1.12 + 3, 0.001)
    } else {
      const d = Math.max(fit, span / (2 * tan)) * 1.25
      camera.position.set(d * 0.5, d * 0.72, d * 0.78)
    }
    camera.near = 0.05
    camera.far = span * 30
    camera.updateProjectionMatrix()
    if (controls.current) {
      controls.current.target.set(0, 0, 0)
      controls.current.update()
    }
  }, [mode, frame, resetKey, camera, controls, size.width, size.height])
  return null
}

function Scene({ model, frame, mode, labels, result, resetKey, walkStart, rects }) {
  const controls = useRef()
  const span = Math.max(frame.sizeX, frame.sizeZ, 4)
  const rooms = result.geometry.corrected.rooms
  return (
    <>
      <color attach="background" args={['#F2F0EB']} />
      <hemisphereLight args={['#ffffff', '#e2dbcf', 1.25]} />
      <ambientLight intensity={0.25} />
      <directionalLight position={[span * 0.35, span * 1.4, span * 0.25]} intensity={1.7} castShadow
        shadow-mapSize={[2048, 2048]} shadow-bias={-0.0004} shadow-normalBias={0.02}
        shadow-camera-left={-span} shadow-camera-right={span} shadow-camera-top={span} shadow-camera-bottom={-span}
        shadow-camera-near={0.5} shadow-camera-far={span * 4} />
      <directionalLight position={[-span * 0.6, span * 0.6, -span * 0.4]} intensity={0.45} />
      <mesh rotation-x={-Math.PI / 2} position-y={-0.11} receiveShadow>
        <planeGeometry args={[span * 8, span * 8]} />
        <meshStandardMaterial color="#E7E3DB" roughness={1} />
      </mesh>
      <gridHelper args={[span * 4, Math.round(span * 4), '#D9D4CA', '#E2DED6']} position-y={-0.105} />
      <primitive object={model} />
      {labels && mode !== 'walk' && rooms.map((r) => {
        const [x, z] = frame.toWorld(r.centroid[0], r.centroid[1])
        return (
          <Html key={r.id} position={[x, 0.15, z]} center distanceFactor={span * 0.9} zIndexRange={[10, 0]} style={{ pointerEvents: 'none' }}>
            <div className="px-2 py-1 rounded-md bg-white/90 border border-line shadow-card text-center whitespace-nowrap">
              <div className="text-[11px] font-semibold text-ink leading-tight">{r.name}</div>
              <div className="text-[10px] text-ink-mute leading-tight">{r.length_m.toFixed(1)} × {r.width_m.toFixed(1)} m · {r.area_m2.toFixed(1)} m²</div>
            </div>
          </Html>
        )
      })}
      {mode === 'walk'
        ? <Walkthrough start={walkStart} rects={rects} />
        : <OrbitControls ref={controls} makeDefault enableDamping dampingFactor={0.12} maxPolarAngle={Math.PI / 2 - 0.02}
                         minDistance={1} maxDistance={span * 6} />}
      <CameraRig mode={mode} frame={frame} resetKey={resetKey} controls={controls} />
    </>
  )
}

export default function StudioView({ result, onCalibrate }) {
  const [mode, setMode] = useState('perspective')
  const [labels, setLabels] = useState(true)
  const [wallHeight, setWallHeight] = useState(result.scale.assumptions.wall_height_m)
  const [resetKey, setResetKey] = useState(0)
  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState('')

  const { group, frame } = useMemo(() => buildModel(result, {
    wallHeight, doorHeight: result.scale.assumptions.door_height_m,
    sill: result.scale.assumptions.window_sill_m, head: result.scale.assumptions.window_head_m,
  }), [result, wallHeight])
  const rects = useMemo(() => collisionRects(result, frame), [result, frame])
  const walkStart = useMemo(() => {
    const rooms = [...result.geometry.corrected.rooms].sort((a, b) => b.area_m2 - a.area_m2)
    return rooms.length ? frame.toWorld(rooms[0].centroid[0], rooms[0].centroid[1]) : [0, 0]
  }, [result, frame])

  useEffect(() => () => {
    group.traverse((o) => { if (o.isMesh) { o.geometry.dispose(); o.material.dispose() } })
  }, [group])

  const exportGLB = () => {
    setExporting(true); setExportError('')
    const exporter = new GLTFExporter()
    exporter.parse(group, (glb) => {
      const blob = new Blob([glb], { type: 'model/gltf-binary' })
      const a = document.createElement('a')
      a.href = URL.createObjectURL(blob)
      a.download = `${(result.filename || 'plan').replace(/\.[^.]+$/, '')}-archnext.glb`
      a.click()
      setTimeout(() => URL.revokeObjectURL(a.href), 2000)
      setExporting(false)
    }, (err) => { setExportError(String(err?.message || err)); setExporting(false) }, { binary: true })
  }

  const g = result.geometry.corrected
  const scale = result.scale
  return (
    <div className="h-full p-5 grid grid-cols-[1fr_320px] gap-5 min-h-0">
      <section className="card min-h-0 flex flex-col overflow-hidden">
        <div className="px-4 py-2.5 border-b border-line flex items-center gap-3">
          <div className="seg">
            <button data-active={mode === 'perspective'} onClick={() => setMode('perspective')}><span className="flex items-center gap-1.5"><Box size={13} />Perspective</span></button>
            <button data-active={mode === 'top'} onClick={() => setMode('top')}><span className="flex items-center gap-1.5"><MapIcon size={13} />Top view</span></button>
            <button data-active={mode === 'walk'} onClick={() => setMode('walk')}><span className="flex items-center gap-1.5"><Footprints size={13} />Walkthrough</span></button>
          </div>
          <button className="btn-ghost btn-sm" onClick={() => { if (mode === 'walk') setMode('perspective'); setResetKey((k) => k + 1) }}><RotateCcw size={13} />Reset camera</button>
          <button className={`chip border ${labels ? 'bg-accent-soft text-accent-dark border-accent/30' : 'bg-white text-ink-mute border-line'}`}
                  onClick={() => setLabels((v) => !v)}><Tag size={12} />Room labels</button>
          <div className="ml-auto flex items-center gap-2 text-[12px] text-ink-soft">
            <span>Wall height</span>
            <input type="range" min="2.2" max="4" step="0.05" value={wallHeight} onChange={(e) => setWallHeight(parseFloat(e.target.value))} className="w-24 accent-[#3F6A8F]" />
            <span className="tabular-nums w-12">{wallHeight.toFixed(2)} m</span>
          </div>
        </div>
        <div className="flex-1 min-h-0 relative">
          <Canvas shadows="soft" dpr={[1, 2]} camera={{ fov: 45, position: [10, 10, 10] }} gl={{ preserveDrawingBuffer: true, antialias: true }}>
            <Suspense fallback={null}>
              <Scene model={group} frame={frame} mode={mode} labels={labels} result={result} resetKey={resetKey} walkStart={walkStart} rects={rects} />
            </Suspense>
          </Canvas>
          <div className="absolute left-3 bottom-3 text-[11.5px] text-ink-soft bg-white/85 border border-line rounded-md px-2.5 py-1.5">
            {mode === 'walk' ? 'W A S D or arrow keys to move · drag to look around' : 'Drag to orbit · right-drag to pan · scroll to zoom'}
          </div>
        </div>
      </section>

      <aside className="card min-h-0 flex flex-col overflow-hidden">
        <div className="flex-1 min-h-0 overflow-auto scrollbar-thin p-4 space-y-4">
          <div>
            <div className="label mb-2">Scale</div>
            <ScaleBadge scale={scale} />
            {scale.status === 'estimated' && (
              <p className="text-[12px] text-ink-mute mt-2">Dimensions below are estimates. <button className="text-accent hover:underline" onClick={onCalibrate}>Calibrate the scale</button> for accurate sizes.</p>
            )}
          </div>
          <div className="grid grid-cols-2 gap-2">
            {[
              ['Footprint', `${frame.sizeX.toFixed(1)} × ${frame.sizeZ.toFixed(1)} m`],
              ['Floor area', fmtM2(g.rooms.reduce((a, r) => a + r.area_m2, 0))],
              ['Rooms', g.rooms.length],
              ['Doors / windows', `${g.stats.doors} / ${g.stats.windows}`],
            ].map(([l, v]) => (
              <div key={l} className="rounded-lg border border-line p-2.5">
                <div className="text-[11px] text-ink-mute">{l}</div>
                <div className="text-[13.5px] font-semibold tabular-nums">{v}</div>
              </div>
            ))}
          </div>
          <div>
            <div className="label mb-2">Rooms</div>
            {g.rooms.length === 0 ? <p className="text-[12.5px] text-ink-mute">No enclosed rooms were detected; walls are shown without floors.</p> : (
              <ul className="divide-y divide-line border border-line rounded-lg">
                {[...g.rooms].sort((a, b) => b.area_m2 - a.area_m2).map((r) => (
                  <li key={r.id} className="px-3 py-2 flex items-center gap-2">
                    <div className="min-w-0 flex-1">
                      <div className="text-[12.5px] font-medium truncate">{r.name}</div>
                      <div className="text-[11px] text-ink-mute">{ROOM_TYPE_LABEL[r.type]}</div>
                    </div>
                    <div className="text-right text-[11.5px] tabular-nums">
                      <div className="text-ink">{r.length_m.toFixed(2)} × {r.width_m.toFixed(2)} m</div>
                      <div className="text-ink-mute">{r.area_m2.toFixed(1)} m²</div>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div>
            <div className="label mb-2 flex items-center gap-1.5"><Ruler size={12} />Construction values</div>
            <dl className="text-[12px] grid grid-cols-[1fr_auto] gap-y-1">
              <dt className="text-ink-soft">Wall thickness</dt><dd className="tabular-nums">{fmtM(scale.wall_thickness_m)} <span className="text-ink-mute">(from plan)</span></dd>
              <dt className="text-ink-soft">Wall height</dt><dd className="tabular-nums">{fmtM(wallHeight)} <span className="text-ink-mute">(assumed)</span></dd>
              <dt className="text-ink-soft">Door height</dt><dd className="tabular-nums">{fmtM(scale.assumptions.door_height_m, 1)} <span className="text-ink-mute">(assumed)</span></dd>
              <dt className="text-ink-soft">Window sill / head</dt><dd className="tabular-nums">{scale.assumptions.window_sill_m.toFixed(1)} / {scale.assumptions.window_head_m.toFixed(1)} m <span className="text-ink-mute">(assumed)</span></dd>
            </dl>
          </div>
        </div>
        <div className="p-3 border-t border-line">
          <button className="btn-primary w-full h-10" onClick={exportGLB} disabled={exporting}>
            {exporting ? <Loader2 size={15} className="animate-spin" /> : <Download size={15} />}Export GLB
          </button>
          {exportError && <p className="text-[12px] text-bad mt-2">Export failed: {exportError}</p>}
        </div>
      </aside>
    </div>
  )
}
