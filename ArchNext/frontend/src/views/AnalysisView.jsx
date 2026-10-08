import { useState } from 'react'
import { AlertTriangle, ArrowRight, Minus, Plus, Scan, Wand2 } from 'lucide-react'
import BlueprintOverlay from '../components/BlueprintOverlay.jsx'
import TopologyPanel from '../components/TopologyPanel.jsx'
import ScalePanel, { ScaleBadge } from '../components/ScalePanel.jsx'
import { api } from '../lib/api.js'

const LAYERS = [
  ['walls', 'Walls'], ['rooms', 'Rooms'], ['openings', 'Doors & windows'], ['issues', 'Issues'], ['measurements', 'Dimensions'],
]

export default function AnalysisView({ result, onResult, onStudio }) {
  const [version, setVersion] = useState('corrected')
  const [layers, setLayers] = useState({ walls: true, rooms: true, openings: true, issues: true, measurements: false })
  const [panel, setPanel] = useState('topology')
  const [selected, setSelected] = useState(null)
  const [zoom, setZoom] = useState(1)
  const [pickMode, setPickMode] = useState(false)
  const [picks, setPicks] = useState([])
  const [busy, setBusy] = useState(false)
  const [calError, setCalError] = useState('')
  const [preview, setPreview] = useState(null)
  const [fixBusy, setFixBusy] = useState(false)
  const [fixNotice, setFixNotice] = useState(null)
  const [fixError, setFixError] = useState('')

  const startPreview = (issue) => {
    setPreview(issue); setSelected(issue.key); setVersion('corrected'); setFixNotice(null); setFixError('')
    setLayers((l) => ({ ...l, walls: true }))
  }
  const applyFix = async (issue) => {
    setFixBusy(true); setFixError('')
    try {
      const r = await api.applyFix(result.id, issue.key)
      onResult(r)
      setFixNotice({
        ok: r.last_fix.resolved,
        text: r.last_fix.resolved
          ? `${r.last_fix.applied} applied. Geometry, rooms, checks and the 3D model were updated.`
          : `${r.last_fix.applied} applied, but the check still reports a problem here. You can undo it.`,
      })
      setPreview(null); setSelected(null)
    } catch (e) { setFixError(e.message) } finally { setFixBusy(false) }
  }
  const undoFix = async () => {
    setFixBusy(true); setFixError(''); setPreview(null)
    try {
      onResult(await api.undoFix(result.id))
      setFixNotice({ ok: true, text: 'Last fix undone. Geometry and 3D model restored.' })
    } catch (e) { setFixError(e.message) } finally { setFixBusy(false) }
  }

  const g = result.geometry[version].stats
  const startPick = () => {
    setPreview(null)
    setPanel('scale'); setPickMode(true); setPicks([]); setCalError('')
    setLayers((l) => ({ ...l, issues: false }))
  }
  const cancelPick = () => { setPickMode(false); setPicks([]); setCalError('') }
  const onPick = (p) => setPicks((cur) => (cur.length >= 2 ? [p] : [...cur, p]))

  const apply = async (distance, unit) => {
    setBusy(true); setCalError('')
    try {
      onResult(await api.calibrate(result.id, picks[0], picks[1], distance, unit))
      setPickMode(false); setPicks([])
    } catch (e) { setCalError(e.message) } finally { setBusy(false) }
  }
  const reset = async () => {
    setBusy(true)
    try { onResult(await api.resetCalibration(result.id)) } catch (e) { setCalError(e.message) } finally { setBusy(false) }
  }

  return (
    <div className="h-full p-5 grid grid-cols-[1fr_380px] gap-5 min-h-0">
      <section className="card min-h-0 flex flex-col overflow-hidden">
        <div className="px-4 py-2.5 border-b border-line flex items-center gap-3 flex-wrap">
          <div className="seg">
            <button data-active={version === 'original'} onClick={() => { setVersion('original'); setPreview(null) }}>Detected</button>
            <button data-active={version === 'corrected'} onClick={() => setVersion('corrected')}>
              {result.topology.edited ? 'Corrected + your fixes' : 'TopologyGuard corrected'}</button>
          </div>
          <div className="flex items-center gap-1.5 flex-wrap">
            {LAYERS.map(([k, l]) => (
              <button key={k} onClick={() => setLayers((s) => ({ ...s, [k]: !s[k] }))}
                className={`chip border transition-colors ${layers[k] ? 'bg-accent-soft text-accent-dark border-accent/30' : 'bg-white text-ink-mute border-line'}`}>
                {l}
              </button>
            ))}
          </div>
          <div className="ml-auto flex items-center gap-1">
            <button className="btn-ghost btn-sm" onClick={() => setZoom((z) => Math.max(0.5, z - 0.25))} title="Zoom out"><Minus size={14} /></button>
            <button className="btn-ghost btn-sm tabular-nums w-14" onClick={() => setZoom(1)} title="Fit">{Math.round(zoom * 100)}%</button>
            <button className="btn-ghost btn-sm" onClick={() => setZoom((z) => Math.min(4, z + 0.25))} title="Zoom in"><Plus size={14} /></button>
          </div>
        </div>
        {pickMode && (
          <div className="px-4 py-2 bg-accent-soft text-accent-dark text-[12.5px] flex items-center gap-2 border-b border-accent/20">
            <Scan size={14} /> Calibration mode — click two points on the plan that are a known distance apart.
          </div>
        )}
        {preview && (
          <div className="px-4 py-2 bg-ok/10 text-ok text-[12.5px] flex items-center gap-2 border-b border-ok/20">
            <Wand2 size={14} /> <span className="text-ink-soft">Previewing <b className="font-medium text-ink">{preview.fix.label}</b>:
              red dashed = current geometry, green = after the fix. Apply or cancel in the panel.</span>
          </div>
        )}
        <div className="flex-1 min-h-0 overflow-auto scrollbar-thin bg-[#FBFAF8] p-4">
          <BlueprintOverlay result={result} version={version} layers={layers} selectedKey={selected} preview={preview}
                            onSelectIssue={(key) => { setSelected(key); setPanel('topology') }} zoom={zoom}
                            pickMode={pickMode} picks={picks} onPick={onPick} />
        </div>
        <div className="px-4 py-2.5 border-t border-line flex items-center gap-5 text-[12px] text-ink-soft">
          <span><b className="font-semibold text-ink">{g.walls}</b> walls ({g.exterior_walls} exterior)</span>
          <span><b className="font-semibold text-ink">{g.rooms}</b> rooms</span>
          <span><b className="font-semibold text-ink">{g.doors}</b> doors</span>
          <span><b className="font-semibold text-ink">{g.windows}</b> windows</span>
          {g.openings - g.doors - g.windows > 0 && <span><b className="font-semibold text-ink">{g.openings - g.doors - g.windows}</b> other openings</span>}
          <div className="ml-auto flex items-center gap-3 text-[11.5px] text-ink-mute">
            <Legend color="#2B3138" label="Exterior wall" /><Legend color="#4F6578" label="Interior wall" />
            <Legend color="#B9772B" label="Door" /><Legend color="#3D8DB8" label="Window" />
          </div>
        </div>
      </section>

      <aside className="card min-h-0 flex flex-col overflow-hidden">
        <div className="p-3 border-b border-line">
          <div className="seg w-full grid grid-cols-2">
            <button data-active={panel === 'topology'} onClick={() => setPanel('topology')}>TopologyGuard</button>
            <button data-active={panel === 'scale'} onClick={() => setPanel('scale')}>ScaleLock</button>
          </div>
        </div>
        <div className="flex-1 min-h-0 overflow-auto scrollbar-thin p-4">
          {result.warnings.length > 0 && (
            <div className="mb-4 rounded-lg bg-warn/5 border border-warn/25 p-3 space-y-1">
              {result.warnings.map((w) => (
                <p key={w} className="text-[12px] text-ink-soft flex gap-2"><AlertTriangle size={13} className="text-warn mt-0.5 shrink-0" />{w}</p>
              ))}
            </div>
          )}
          {panel === 'topology'
            ? <TopologyPanel result={result} selected={selected}
                             onSelect={(key) => { setSelected(key); setVersion('corrected'); setLayers((l) => ({ ...l, issues: true })) }}
                             preview={preview} onPreview={startPreview} onCancelPreview={() => setPreview(null)}
                             onApply={applyFix} onUndo={undoFix} busy={fixBusy} notice={fixNotice} error={fixError} />
            : <ScalePanel result={result} pickMode={pickMode} picks={picks} onStartPick={startPick} onCancelPick={cancelPick}
                          onApply={apply} onReset={reset} busy={busy} error={calError} />}
        </div>
        <div className="p-3 border-t border-line flex items-center gap-2">
          <ScaleBadge scale={result.scale} />
          <button className="btn-primary ml-auto" onClick={onStudio} disabled={pickMode || !!preview}>Open 3D Studio <ArrowRight size={15} /></button>
        </div>
      </aside>
    </div>
  )
}

function Legend({ color, label }) {
  return <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-sm" style={{ background: color }} />{label}</span>
}
