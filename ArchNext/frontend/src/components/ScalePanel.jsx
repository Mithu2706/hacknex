import { useState } from 'react'
import { CheckCircle2, Crosshair, Loader2, RotateCcw, Ruler, XCircle } from 'lucide-react'
import { SCALE_STATUS, TONE, fmtM } from '../lib/format.js'

export function ScaleBadge({ scale, className = '' }) {
  const s = SCALE_STATUS[scale.status]
  return <span className={`chip ${TONE[s.tone]} ${className}`}><Ruler size={12} />{s.label}</span>
}

export default function ScalePanel({ result, pickMode, picks, onStartPick, onCancelPick, onApply, onReset, busy, error }) {
  const { scale } = result
  const [distance, setDistance] = useState('')
  const [unit, setUnit] = useState('m')
  const accepted = scale.measurements.filter((m) => m.status === 'accepted')
  const rejected = scale.measurements.filter((m) => m.status !== 'accepted')
  const pxDist = picks.length === 2 ? Math.hypot(picks[1][0] - picks[0][0], picks[1][1] - picks[0][1]) : 0

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-line p-3">
        <ScaleBadge scale={scale} />
        <p className="text-[12.5px] text-ink-soft mt-2 leading-relaxed">
          {scale.status === 'auto' && <>Scale read from {accepted.length} dimension label{accepted.length === 1 ? '' : 's'} that agree with each other
            {scale.confidence && <> (confidence: <b className="font-medium">{scale.confidence}</b>)</>}.</>}
          {scale.status === 'manual' && <>Scale set from a reference distance you marked on the plan ({fmtM(scale.meters, 3)}).</>}
          {scale.status === 'estimated' && <>No reliable dimension labels were found. Sizes are an estimate based on {scale.basis.replace(/ applied.*/, '')}; mark a known distance for accurate dimensions.</>}
        </p>
        <div className="grid grid-cols-2 gap-2 mt-3 text-[12px]">
          <div><div className="text-ink-mute">Plan extent</div><div className="font-medium">{scale.extent_m[0].toFixed(1)} × {scale.extent_m[1].toFixed(1)} m</div></div>
          <div><div className="text-ink-mute">Wall thickness</div><div className="font-medium">{fmtM(scale.wall_thickness_m)}</div></div>
          <div><div className="text-ink-mute">1 metre</div><div className="font-medium">{(1 / scale.meters_per_px).toFixed(1)} px</div></div>
          <div><div className="text-ink-mute">Wall height</div><div className="font-medium">{fmtM(scale.assumptions.wall_height_m, 1)} <span className="text-ink-mute font-normal">(assumed)</span></div></div>
        </div>
      </div>

      <div className="rounded-lg border border-line p-3">
        <div className="flex items-center justify-between">
          <div className="card-title">Manual calibration</div>
          {scale.status === 'manual' && (
            <button className="btn-ghost btn-sm" onClick={onReset} disabled={busy}><RotateCcw size={13} />
              {scale.auto_available ? 'Use automatic' : 'Clear'}</button>
          )}
        </div>
        {!pickMode ? (
          <>
            <p className="text-[12px] text-ink-mute mt-1">Mark two points on the blueprint whose real distance you know, such as the length of a wall.</p>
            <button className="btn-secondary w-full mt-3" onClick={onStartPick}><Crosshair size={14} />Mark reference distance</button>
          </>
        ) : (
          <div className="mt-2">
            <p className="text-[12px] text-ink-soft">
              {picks.length < 2 ? `Click point ${picks.length + 1} of 2 on the blueprint.` : `Selected distance: ${pxDist.toFixed(0)} px. Enter its real length:`}
            </p>
            {picks.length === 2 && (
              <div className="flex gap-2 mt-2">
                <input className="input flex-1 min-w-0" type="number" min="0" step="any" placeholder="Distance" autoFocus
                       value={distance} onChange={(e) => setDistance(e.target.value)} />
                <select className="input w-20" value={unit} onChange={(e) => setUnit(e.target.value)}>
                  {['m', 'cm', 'mm', 'ft', 'in'].map((u) => <option key={u}>{u}</option>)}
                </select>
              </div>
            )}
            {error && <p className="text-[12px] text-bad mt-2">{error}</p>}
            <div className="flex gap-2 mt-3">
              <button className="btn-secondary flex-1" onClick={onCancelPick} disabled={busy}>Cancel</button>
              <button className="btn-primary flex-1" disabled={picks.length < 2 || !(parseFloat(distance) > 0) || busy}
                      onClick={() => onApply(parseFloat(distance), unit)}>
                {busy && <Loader2 size={14} className="animate-spin" />}Apply scale
              </button>
            </div>
          </div>
        )}
      </div>

      <div>
        <div className="label mb-2">Dimension labels found ({scale.measurements.length})</div>
        {scale.measurements.length === 0 ? (
          <div className="text-[12.5px] text-ink-mute border border-dashed border-line rounded-lg p-4 text-center">
            {result.ocr_available ? 'No dimension text was recognised on this plan.' : 'Text recognition is unavailable.'}
          </div>
        ) : (
          <ul className="space-y-1.5">
            {[...accepted, ...rejected].map((m, i) => (
              <li key={i} className="rounded-lg border border-line px-3 py-2">
                <div className="flex items-center gap-2">
                  {m.status === 'accepted' ? <CheckCircle2 size={14} className="text-ok shrink-0" /> : <XCircle size={14} className="text-bad/80 shrink-0" />}
                  <span className="text-[12.5px] font-medium font-mono">{m.text}</span>
                  <span className="text-[11px] text-ink-mute ml-auto">{m.kind === 'pair' ? 'Room label' : 'Dimension line'}</span>
                </div>
                <div className="text-[11.5px] text-ink-mute mt-0.5 pl-6">
                  {m.status === 'accepted'
                    ? `Read as ${m.meters.map((v) => v.toFixed(2)).join(' × ')} m — used for calibration`
                    : m.reason}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
