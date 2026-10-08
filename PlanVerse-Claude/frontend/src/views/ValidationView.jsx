import { useEffect, useRef, useState } from 'react'
import { FileJson, Loader2, Upload } from 'lucide-react'
import { api } from '../lib/api.js'
import { ROOM_TYPE_LABEL, SCALE_STATUS, pct } from '../lib/format.js'
import { ScaleBadge } from '../components/ScalePanel.jsx'

function Section({ title, subtitle, children, right }) {
  return (
    <section className="card">
      <div className="px-5 py-3.5 border-b border-line flex items-center gap-3">
        <div>
          <h2 className="card-title">{title}</h2>
          {subtitle && <p className="text-[12px] text-ink-mute mt-0.5">{subtitle}</p>}
        </div>
        <div className="ml-auto">{right}</div>
      </div>
      <div className="p-5">{children}</div>
    </section>
  )
}

const better = (a, b, higher = true) => (a == null || b == null || a === b ? '' : (higher ? b > a : b < a) ? 'text-ok font-medium' : 'text-warn font-medium')

function MetricsTable({ base, pv, labels = ['Baseline', 'PlanVerse'] }) {
  const rows = [
    ['Room recall', base.room_recall, pv.room_recall, pct, true],
    ['Room precision', base.room_precision, pv.room_precision, pct, true],
    ['Room IoU (matched rooms)', base.room_iou_matched, pv.room_iou_matched, (v) => (v == null ? '—' : v.toFixed(3)), true],
    ['Room IoU (all ground-truth rooms)', base.room_iou_all, pv.room_iou_all, (v) => (v == null ? '—' : v.toFixed(3)), true],
    ['Room-type accuracy', base.room_type_accuracy, pv.room_type_accuracy, pct, true],
    ['Door F1', base.doors?.f1, pv.doors?.f1, (v) => (v == null ? '—' : v.toFixed(3)), true],
    ['Window F1', base.windows?.f1, pv.windows?.f1, (v) => (v == null ? '—' : v.toFixed(3)), true],
    ['Dimension error', base.dimension_error_pct, pv.dimension_error_pct, (v) => (v == null ? '—' : `${v.toFixed(1)}%`), false],
    ['Scale error', base.scale_error_pct, pv.scale_error_pct, (v) => (v == null ? '—' : `${v.toFixed(1)}%`), false],
    ['Structural consistency (connected wall ends)', base.structural_consistency, pv.structural_consistency, pct, true],
  ]
  return (
    <table className="table">
      <thead><tr><th>Metric</th><th className="text-right">{labels[0]}</th><th className="text-right">{labels[1]}</th></tr></thead>
      <tbody>
        {rows.map(([l, a, b, f, hi]) => (
          <tr key={l}><td>{l}</td><td className="text-right tabular-nums">{f(a)}</td><td className={`text-right tabular-nums ${better(a, b, hi)}`}>{f(b)}</td></tr>
        ))}
      </tbody>
    </table>
  )
}

export default function ValidationView({ result }) {
  const o = result.geometry.original.stats
  const c = result.geometry.corrected.stats
  const rooms = result.geometry.corrected.rooms
  const holdout = result.scale.holdout
  const [evalRes, setEvalRes] = useState(null)
  const [evalErr, setEvalErr] = useState('')
  const [evalBusy, setEvalBusy] = useState(false)
  const [bench, setBench] = useState(null)
  const fileRef = useRef(null)

  useEffect(() => { api.benchmark().then(setBench).catch(() => setBench({ available: false })) }, [])

  const runEval = async (f) => {
    if (!f) return
    setEvalBusy(true); setEvalErr('')
    try { setEvalRes(await api.evaluate(result.id, f)) } catch (e) { setEvalErr(e.message) } finally { setEvalBusy(false) }
  }

  const meanHoldout = holdout.length ? holdout.reduce((a, r) => a + r.error_pct, 0) / holdout.length : null

  return (
    <div className="h-full overflow-auto scrollbar-thin">
      <div className="max-w-6xl mx-auto p-6 space-y-5">
        <div className="grid grid-cols-2 gap-5">
          <Section title="Structural checks" subtitle="The same detected walls, before and after TopologyGuard.">
            <table className="table">
              <thead><tr><th>Measure</th><th className="text-right">Detected</th><th className="text-right">Corrected</th></tr></thead>
              <tbody>
                {[
                  ['Enclosed rooms', o.rooms, c.rooms, 'higher', String],
                  ['Connected wall ends', o.connected_endpoint_ratio, c.connected_endpoint_ratio, 'higher', (v) => pct(v)],
                  ['Disconnected wall ends', o.dangling_endpoints, c.dangling_endpoints, 'lower', String],
                  ['Wall segments', o.walls, c.walls, null, String],
                  ['Doors', o.doors, c.doors, null, String],
                  ['Windows', o.windows, c.windows, null, String],
                  ['All openings', o.openings, c.openings, null, String],
                ].map(([l, a, b, dir, f]) => (
                  <tr key={l}><td>{l}</td><td className="text-right tabular-nums">{f(a)}</td>
                    <td className={`text-right tabular-nums ${dir ? better(a, b, dir === 'higher') : ''}`}>{f(b)}</td></tr>
                ))}
              </tbody>
            </table>
            <p className="text-[12px] text-ink-mute mt-3">
              {result.topology.corrected} automatic correction{result.topology.corrected === 1 ? '' : 's'} applied, {result.topology.review} item{result.topology.review === 1 ? '' : 's'} left for review.
            </p>
          </Section>

          <Section title="Scale verification" subtitle="Each dimension label is predicted from the others and compared with its written value."
                   right={<ScaleBadge scale={result.scale} />}>
            {result.scale.status === 'auto' && holdout.length > 0 ? (
              <>
                <table className="table">
                  <thead><tr><th>Label</th><th className="text-right">Written</th><th className="text-right">Predicted</th><th className="text-right">Error</th></tr></thead>
                  <tbody>
                    {holdout.map((r, i) => (
                      <tr key={i}><td className="font-mono">{r.text}</td><td className="text-right tabular-nums">{r.labelled_m.toFixed(2)} m</td>
                        <td className="text-right tabular-nums">{r.predicted_m.toFixed(2)} m</td><td className="text-right tabular-nums">{r.error_pct.toFixed(1)}%</td></tr>
                    ))}
                  </tbody>
                </table>
                <p className="text-[12px] text-ink-mute mt-3">Mean hold-out error: <b className="text-ink font-medium">{meanHoldout.toFixed(1)}%</b></p>
              </>
            ) : (
              <p className="text-[12.5px] text-ink-soft">
                {result.scale.status === 'auto'
                  ? 'Only one dimension label was usable, so a hold-out comparison is not possible.'
                  : result.scale.status === 'manual'
                    ? 'The scale was set manually from a reference distance. Manually calibrated values are not counted as automatic accuracy.'
                    : `${SCALE_STATUS.estimated.label}. No dimension labels could be verified for this plan.`}
              </p>
            )}
          </Section>
        </div>

        <Section title="Room schedule" subtitle="Dimensions are measured from the reconstructed floor polygons using the current scale.">
          {rooms.length === 0 ? <p className="text-[12.5px] text-ink-mute">No enclosed rooms were detected.</p> : (
            <table className="table">
              <thead><tr><th>Room</th><th>Type</th><th className="text-right">Length</th><th className="text-right">Width</th><th className="text-right">Area</th><th>Label on plan</th></tr></thead>
              <tbody>
                {[...rooms].sort((a, b) => b.area_m2 - a.area_m2).map((r) => (
                  <tr key={r.id}>
                    <td className="text-ink font-medium">{r.name}</td><td>{ROOM_TYPE_LABEL[r.type]}</td>
                    <td className="text-right tabular-nums">{r.length_m.toFixed(2)} m</td><td className="text-right tabular-nums">{r.width_m.toFixed(2)} m</td>
                    <td className="text-right tabular-nums">{r.area_m2.toFixed(1)} m²</td>
                    <td className="font-mono text-ink-mute">{r.label_dims || '—'}{r.rectangularity < 0.85 && <span className="font-sans text-[11px] ml-2 text-ink-mute">(irregular shape: bounding size)</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Section>

        <Section title="Ground-truth evaluation"
                 subtitle="Upload an annotation file for this plan to measure accuracy. Baseline and PlanVerse use the same parser; PlanVerse adds TopologyGuard and ScaleLock."
                 right={
                   <>
                     <button className="btn-secondary btn-sm" onClick={() => fileRef.current?.click()} disabled={evalBusy}>
                       {evalBusy ? <Loader2 size={13} className="animate-spin" /> : <Upload size={13} />}Upload annotation
                     </button>
                     <input ref={fileRef} type="file" accept=".json,application/json" className="hidden"
                            onChange={(e) => { runEval(e.target.files?.[0]); e.target.value = '' }} />
                   </>
                 }>
          {evalErr && <p className="text-[12.5px] text-bad mb-3">{evalErr}</p>}
          {evalRes ? (
            <>
              <MetricsTable base={evalRes.baseline} pv={evalRes.planverse} />
              <p className="text-[12px] text-ink-mute mt-3">Manual calibration and edits are excluded from these automatic scores. The baseline uses an estimated scale because it has no ScaleLock.</p>
            </>
          ) : (
            <div className="flex items-start gap-3 text-[12.5px] text-ink-soft">
              <FileJson size={18} className="text-ink-mute mt-0.5 shrink-0" />
              <div>
                No annotation loaded. The file lists the true rooms, doors and windows in image pixels:
                <pre className="mt-2 text-[11.5px] bg-paper border border-line rounded-lg p-3 text-ink-soft overflow-auto">{`{
  "meters_per_px": 0.02,
  "rooms":   [{ "polygon": [[x, y], ...], "type": "bedroom" }],
  "doors":   [{ "x1": 0, "y1": 0, "x2": 0, "y2": 0 }],
  "windows": [{ "x1": 0, "y1": 0, "x2": 0, "y2": 0 }]
}`}</pre>
              </div>
            </div>
          )}
        </Section>

        {bench?.available && (
          <Section title="Benchmark on generated plans"
                   subtitle={`${bench.count} synthetic floor plans with exact known geometry, wall breaks and junction gaps. Same parser for both columns.`}>
            <MetricsTable base={bench.baseline} pv={bench.planverse} />
            <p className="text-[12px] text-ink-mute mt-3">{bench.note}</p>
          </Section>
        )}
      </div>
    </div>
  )
}
