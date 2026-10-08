import { Fragment, useEffect, useRef, useState } from 'react'
import { AlertTriangle, FileJson, FlaskConical, Loader2, Upload } from 'lucide-react'
import { api } from '../lib/api.js'
import { ROOM_TYPE_LABEL, SCALE_STATUS, TONE, pct } from '../lib/format.js'
import { ScaleBadge } from '../components/ScalePanel.jsx'
import { BetterHint, ConfigBarChart, Disclosure, InfoTip, METRICS, fmtMetric, metricValue } from '../components/Charts.jsx'

const CONFIG_ORDER = [
  { key: 'baseline', label: 'Baseline' },
  { key: 'topologyguard_only', label: 'TopologyGuard only' },
  { key: 'scalelock_only', label: 'ScaleLock only' },
  { key: 'full', label: 'Full ArchNext' },
]
const ABLATION_METRICS = ['room_recall', 'room_precision', 'room_iou_all', 'structural_consistency',
  'dimension_error_pct', 'scale_error_pct', 'doors_f1', 'windows_f1']
const NA_REASON = {
  dimension_error_pct: 'Needs matched rooms and a true scale in the annotation.',
  scale_error_pct: 'Needs "meters_per_px" in the annotation.',
  room_type_accuracy: 'Needs room types in the annotation.',
}

function SourceChip({ source }) {
  const map = {
    plan: ['This plan', TONE.accent],
    plan_labels: ['This plan · dimension labels', TONE.accent],
    plan_gt: ['This plan · your annotation', TONE.ok],
    bench: ['Synthetic benchmark', TONE.warn],
    none: ['Not evaluated', TONE.mute],
  }
  const [label, cls] = map[source]
  return <span className={`chip ${cls}`}>{label}</span>
}

function Card({ title, tip, value, sub, source, better }) {
  return (
    <div className="card p-4 flex flex-col">
      <div className="flex items-center gap-1.5 text-[12.5px] font-medium text-ink-soft">{title}<InfoTip text={tip} /></div>
      <div className={`mt-2 tabular-nums ${value == null ? 'text-[17px] text-ink-mute font-medium' : 'text-[26px] font-semibold text-ink'}`}>
        {value == null ? 'Not evaluated' : value}
      </div>
      <p className="text-[12px] text-ink-mute mt-1 leading-snug flex-1">{sub}</p>
      <div className="mt-3 flex items-center justify-between gap-2"><SourceChip source={source} />{better && <BetterHint better={better} />}</div>
    </div>
  )
}

function Section({ letter, title, subtitle, right, children }) {
  return (
    <section className="card">
      <div className="px-5 py-3.5 border-b border-line flex items-center gap-3">
        <span className="w-6 h-6 rounded-md bg-accent-soft text-accent-dark text-[12px] font-semibold grid place-items-center">{letter}</span>
        <div className="min-w-0">
          <h2 className="card-title">{title}</h2>
          {subtitle && <p className="text-[12px] text-ink-mute mt-0.5">{subtitle}</p>}
        </div>
        <div className="ml-auto">{right}</div>
      </div>
      <div className="p-5">{children}</div>
    </section>
  )
}

function MetricTable({ configs, metrics = ABLATION_METRICS.concat(['room_iou_matched', 'room_type_accuracy']) }) {
  const extra = { room_iou_matched: { label: 'Room IoU (matched rooms only)' }, room_type_accuracy: { label: 'Room-type accuracy' } }
  return (
    <div className="overflow-auto">
      <table className="table">
        <thead><tr><th>Metric</th>{CONFIG_ORDER.map((c) => <th key={c.key} className="text-right">{c.label}</th>)}</tr></thead>
        <tbody>
          {metrics.map((k) => (
            <tr key={k}>
              <td>{METRICS[k]?.label || extra[k].label}</td>
              {CONFIG_ORDER.map((c) => {
                const v = metricValue(configs[c.key], k)
                const shown = METRICS[k] ? fmtMetric(k, v) : (v == null ? 'N/A' : pct(v))
                return <td key={c.key} className="text-right tabular-nums" title={v == null ? (NA_REASON[k] || 'Not measurable for this configuration') : ''}>{shown}</td>
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function DetectionDetails({ configs }) {
  return (
    <table className="table">
      <thead><tr><th>Configuration</th><th>Element</th><th className="text-right">Found correctly</th><th className="text-right">Detected</th><th className="text-right">Actual</th><th className="text-right">Precision</th><th className="text-right">Recall</th><th className="text-right">F1</th></tr></thead>
      <tbody>
        {CONFIG_ORDER.flatMap((c) => ['doors', 'windows'].map((el) => {
          const d = configs[c.key]?.[el]
          if (!d) return null
          return (
            <tr key={c.key + el}><td>{c.label}</td><td className="capitalize">{el}</td>
              <td className="text-right tabular-nums">{d.tp}</td><td className="text-right tabular-nums">{d.predicted}</td><td className="text-right tabular-nums">{d.actual}</td>
              <td className="text-right tabular-nums">{d.precision.toFixed(2)}</td><td className="text-right tabular-nums">{d.recall.toFixed(2)}</td><td className="text-right tabular-nums">{d.f1.toFixed(2)}</td></tr>
          )
        }))}
      </tbody>
    </table>
  )
}

export default function ValidationView({ result }) {
  const [bench, setBench] = useState(null)
  const [evalRes, setEvalRes] = useState(null)
  const [evalErr, setEvalErr] = useState('')
  const [evalBusy, setEvalBusy] = useState(false)
  const [source, setSource] = useState('bench')
  const [ablMetric, setAblMetric] = useState('room_recall')
  const fileRef = useRef(null)

  useEffect(() => {
    api.benchmark().then((b) => { setBench(b); if (!b?.available) setSource('plan') })
      .catch(() => { setBench({ available: false }); setSource('plan') })
  }, [])
  useEffect(() => { setEvalRes(null) }, [result.id])

  const benchOk = bench?.available && bench.results
  const runEval = async (f) => {
    if (!f) return
    setEvalBusy(true); setEvalErr('')
    try { setEvalRes(await api.evaluate(result.id, f)); setSource('plan') } catch (e) { setEvalErr(e.message) } finally { setEvalBusy(false) }
  }

  const cur = result.geometry.corrected.stats
  const orig = result.geometry.original.stats
  const holdout = result.scale.holdout || []
  const holdMean = holdout.length ? holdout.reduce((a, r) => a + r.error_pct, 0) / holdout.length : null
  const usePlan = source === 'plan'
  const planFull = evalRes?.configs?.full
  const benchFull = benchOk ? bench.results.full : null

  // Section A values ---------------------------------------------------------------------------
  const cardVal = (key) => {
    if (usePlan) return planFull ? metricValue(planFull, key) : null
    return benchFull ? metricValue(benchFull, key) : null
  }
  const srcFor = (hasPlanGT) => (usePlan ? (hasPlanGT ? 'plan_gt' : 'none') : (benchOk ? 'bench' : 'none'))
  const dimCard = (() => {
    if (!usePlan) return { v: benchFull?.dimension_error_pct, src: benchOk ? 'bench' : 'none', sub: 'Average room length/width error across the generated plans.' }
    if (planFull?.dimension_error_pct != null) return { v: planFull.dimension_error_pct, src: 'plan_gt', sub: 'Average room length/width error against your annotation.' }
    if (holdMean != null) return { v: holdMean, src: 'plan_labels', sub: `Each dimension written on this plan predicted from the others (${result.scale.status === 'manual' ? 'manual' : 'automatic'} calibration).` }
    return { v: null, src: 'none', sub: 'Needs dimension labels on the plan or a ground-truth annotation.' }
  })()
  const conn = usePlan ? cur.connected_endpoint_ratio : benchFull?.structural_consistency

  // Section B data --------------------------------------------------------------------------------
  const bvRows = (key) => {
    if (usePlan) {
      if (key === 'structural_consistency' && !evalRes) {
        return [{ key: 'baseline', label: 'Baseline (detected)', res: { structural_consistency: orig.connected_endpoint_ratio } },
          { key: 'full', label: 'Full ArchNext', res: { structural_consistency: cur.connected_endpoint_ratio } }]
      }
      if (!evalRes) return null
      return [{ key: 'baseline', label: 'Baseline', res: evalRes.configs.baseline }, { key: 'full', label: 'Full ArchNext', res: evalRes.configs.full }]
    }
    if (!benchOk) return null
    return [{ key: 'baseline', label: 'Baseline', res: bench.results.baseline }, { key: 'full', label: 'Full ArchNext', res: bench.results.full }]
  }
  const ablConfigs = usePlan ? evalRes?.configs : (benchOk ? bench.results : null)
  const ablRows = ablConfigs ? CONFIG_ORDER.map((c) => ({ ...c, res: ablConfigs[c.key] })) : null

  const sourceLabel = usePlan
    ? (evalRes ? 'This plan, scored against your annotation.' : 'This plan has no ground-truth annotation, so accuracy cannot be measured. Upload one below to evaluate it.')
    : (benchOk ? bench.dataset.label : 'No benchmark results are available.')

  return (
    <div className="h-full overflow-auto scrollbar-thin">
      <div className="max-w-6xl mx-auto p-6 space-y-5">
        {/* Source selector ------------------------------------------------------------------- */}
        <div className="flex items-center gap-3 flex-wrap">
          <div>
            <h1 className="text-[18px] font-semibold tracking-tight">Validation</h1>
            <p className="text-[12.5px] text-ink-mute">How well ArchNext reconstructs floor plans, and where the numbers come from.</p>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <span className="text-[12px] text-ink-mute">Results for</span>
            <div className="seg">
              <button data-active={source === 'plan'} onClick={() => setSource('plan')}>This plan</button>
              <button data-active={source === 'bench'} onClick={() => setSource('bench')} disabled={!benchOk}>Synthetic benchmark</button>
            </div>
            <button className="btn-secondary btn-sm" onClick={() => fileRef.current?.click()} disabled={evalBusy}>
              {evalBusy ? <Loader2 size={13} className="animate-spin" /> : <Upload size={13} />}{evalBusy ? 'Evaluating…' : 'Evaluate with annotation'}
            </button>
            <input ref={fileRef} type="file" accept=".json,application/json" className="hidden"
                   onChange={(e) => { runEval(e.target.files?.[0]); e.target.value = '' }} />
          </div>
        </div>
        <div className={`rounded-lg border px-4 py-2.5 text-[12.5px] flex items-start gap-2 ${usePlan ? 'border-accent/25 bg-accent-soft/40' : 'border-warn/30 bg-warn/5'}`}>
          {usePlan ? <FileJson size={15} className="text-accent mt-0.5 shrink-0" /> : <FlaskConical size={15} className="text-warn mt-0.5 shrink-0" />}
          <span className="text-ink-soft">{sourceLabel}{!usePlan && ' These are not accuracy scores for your uploaded plan.'}</span>
        </div>
        {evalErr && <p className="text-[12.5px] text-bad">{evalErr}</p>}

        {/* A. Performance overview --------------------------------------------------------------- */}
        <div className="flex items-center gap-2 px-1">
          <span className="w-6 h-6 rounded-md bg-accent-soft text-accent-dark text-[12px] font-semibold grid place-items-center">A</span>
          <h2 className="card-title">Performance overview</h2>
        </div>
        <div className="grid grid-cols-4 gap-4">
          <Card title="Room Detection" tip={METRICS.room_recall.tip} better="higher"
                value={cardVal('room_recall') == null ? null : fmtMetric('room_recall', cardVal('room_recall'))}
                sub="Share of the real rooms that were found." source={srcFor(!!planFull)} />
          <Card title="Structural Connectivity" tip={METRICS.structural_consistency.tip} better="higher"
                value={conn == null ? null : fmtMetric('structural_consistency', conn)}
                sub={usePlan ? `Wall ends connected in the current geometry${result.topology.edited ? ' (includes your fixes)' : ''}.` : 'Wall ends connected, averaged over the generated plans.'}
                source={usePlan ? 'plan' : (benchOk ? 'bench' : 'none')} />
          <Card title="Dimension Error" tip={METRICS.dimension_error_pct.tip} better="lower"
                value={dimCard.v == null ? null : `${dimCard.v.toFixed(1)}%`} sub={dimCard.sub} source={dimCard.src} />
          <Card title="Room Overlap" tip={METRICS.room_iou_all.tip} better="higher"
                value={cardVal('room_iou_all') == null ? null : fmtMetric('room_iou_all', cardVal('room_iou_all'))}
                sub="How closely detected room shapes match the real ones." source={srcFor(!!planFull)} />
        </div>

        {/* B. Before vs after ------------------------------------------------------------------- */}
        <Section letter="B" title="Before vs after" subtitle="Baseline parser output compared with full ArchNext (TopologyGuard + ScaleLock). Each metric has its own chart and scale.">
          <div className="grid grid-cols-3 gap-5">
            {['room_recall', 'structural_consistency', 'dimension_error_pct'].map((k) => {
              const rows = bvRows(k)
              return (
                <div key={k} className="rounded-lg border border-line p-3">
                  <div className="flex items-center justify-between mb-1">
                    <div className="text-[12.5px] font-medium flex items-center gap-1.5">{METRICS[k].label}<InfoTip text={METRICS[k].tip} /></div>
                    <BetterHint better={METRICS[k].better} />
                  </div>
                  {rows ? <ConfigBarChart rows={rows} metric={k} height={130} />
                    : <div className="h-[130px] grid place-items-center text-[12px] text-ink-mute text-center px-4">Not evaluated — no ground truth for this plan.</div>}
                </div>
              )
            })}
          </div>
        </Section>

        {/* C. Four-way ablation --------------------------------------------------------------- */}
        <Section letter="C" title="Research contribution: four-way ablation"
                 subtitle="The same parser and the same plans run four times with each contribution switched on or off independently.">
          <div className="grid grid-cols-4 gap-2 mb-4">
            {[['Baseline', 'TopologyGuard OFF · ScaleLock OFF'], ['TopologyGuard only', 'TopologyGuard ON · ScaleLock OFF'],
              ['ScaleLock only', 'TopologyGuard OFF · ScaleLock ON'], ['Full ArchNext', 'TopologyGuard ON · ScaleLock ON']].map(([l, d], i) => (
              <div key={l} className="rounded-lg border border-line px-3 py-2">
                <div className="text-[12.5px] font-medium flex items-center gap-2">
                  <span className="w-2.5 h-2.5 rounded-sm" style={{ background: ['#eb6834', '#1baf7a', '#eda100', '#2a78d6'][i] }} />{l}
                </div>
                <div className="text-[11px] text-ink-mute mt-0.5">{d}</div>
              </div>
            ))}
          </div>
          {ablRows ? (
            <>
              <div className="flex items-center gap-2 flex-wrap mb-2">
                <span className="text-[12px] text-ink-mute">Metric</span>
                <div className="seg flex-wrap">
                  {ABLATION_METRICS.map((k) => <button key={k} data-active={ablMetric === k} onClick={() => setAblMetric(k)}>{METRICS[k].label}</button>)}
                </div>
              </div>
              <div className="flex items-center gap-3 text-[12px] text-ink-mute mb-1">
                <span>{METRICS[ablMetric].tip}</span><span className="ml-auto"><BetterHint better={METRICS[ablMetric].better} /></span>
              </div>
              <ConfigBarChart rows={ablRows} metric={ablMetric} />
              {ablRows.some((r) => metricValue(r.res, ablMetric) == null) && (
                <p className="text-[12px] text-ink-mute">N/A: {NA_REASON[ablMetric] || 'not measurable for this configuration.'}</p>
              )}
              {!usePlan && bench.notes?.scale && <p className="text-[12px] text-ink-mute mt-2">{bench.notes.scale}</p>}
              <p className="text-[12px] text-ink-mute mt-1">
                Source: <b className="font-medium text-ink-soft">{usePlan ? 'this plan, scored against your annotation' : bench.dataset.label}</b>
                {!usePlan && bench.reproducibility?.identical && ' Re-running the study reproduced identical results.'}
              </p>
              <div className="mt-4"><Disclosure title="View detailed results"><MetricTable configs={ablConfigs} /></Disclosure></div>
            </>
          ) : (
            <p className="text-[12.5px] text-ink-mute">Not evaluated — upload a ground-truth annotation for this plan, or switch to the synthetic benchmark.</p>
          )}
          <p className="text-[12px] text-ink-mute mt-3 border-t border-line pt-3">
            Real-world annotated test set: <b className="font-medium text-ink-soft">not evaluated</b> — no annotated real floor plans are included yet.
            Synthetic and real-world results are always reported separately.
          </p>
        </Section>

        {/* D. Scale verification ------------------------------------------------------------- */}
        <Section letter="D" title="Scale verification" subtitle="Dimensions written on the blueprint compared with what ArchNext measures."
                 right={<ScaleBadge scale={result.scale} />}>
          {(result.scale.warnings || []).map((w) => (
            <p key={w} className="mb-3 rounded-lg border border-warn/30 bg-warn/5 px-3 py-2 text-[12.5px] text-ink-soft flex gap-2"><AlertTriangle size={14} className="text-warn mt-0.5 shrink-0" />{w}</p>
          ))}
          {holdout.length > 0 ? (
            <table className="table">
              <thead><tr><th>Dimension on blueprint</th><th className="text-right">Written</th><th className="text-right">Predicted</th><th className="text-right">Error</th><th>Calibration method</th></tr></thead>
              <tbody>
                {holdout.map((r, i) => (
                  <tr key={i}><td className="font-mono">{r.text}</td><td className="text-right tabular-nums">{r.labelled_m.toFixed(2)} m</td>
                    <td className="text-right tabular-nums">{r.predicted_m.toFixed(2)} m</td>
                    <td className={`text-right tabular-nums ${r.error_pct > 5 ? 'text-warn font-medium' : ''}`}>{r.error_pct.toFixed(1)}%</td>
                    <td>{r.method === 'manual' ? 'Manual' : 'Automatic'}</td></tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="text-[12.5px] text-ink-soft">
              {result.scale.status === 'estimated'
                ? `${SCALE_STATUS.estimated.label}. No dimension labels on this plan could be verified; dimensions are estimates.`
                : result.scale.status === 'manual'
                  ? 'Manually calibrated. No readable dimension labels on this plan to compare against.'
                  : 'Only one dimension label was usable, so it cannot be checked against the others.'}
            </p>
          )}
          {result.scale.status === 'auto' && holdout.length > 0 && (
            <p className="text-[12px] text-ink-mute mt-2">Each label is predicted using only the other labels, so it is an honest check rather than a fit.</p>
          )}
        </Section>

        {/* E. Advanced -------------------------------------------------------------------------- */}
        <div className="space-y-3">
          <div className="label px-1">Advanced evaluation</div>
          <Disclosure title="Detailed structural checks" subtitle="current geometry">
            <table className="table">
              <thead><tr><th>Check</th><th className="text-right">Auto-corrected</th><th className="text-right">Fixed by you</th><th className="text-right">Open</th></tr></thead>
              <tbody>
                {result.topology.checks.map((c) => (
                  <tr key={c.key}><td title={c.description}>{c.name}</td><td className="text-right tabular-nums">{c.corrected}</td>
                    <td className="text-right tabular-nums">{c.fixed}</td><td className="text-right tabular-nums">{c.review}</td></tr>
                ))}
              </tbody>
            </table>
            <table className="table mt-4">
              <thead><tr><th>Measure</th><th className="text-right">Detected</th><th className="text-right">Current</th></tr></thead>
              <tbody>
                {[['Enclosed rooms', orig.rooms, cur.rooms], ['Connected wall ends', pct(orig.connected_endpoint_ratio), pct(cur.connected_endpoint_ratio)],
                  ['Disconnected wall ends', orig.dangling_endpoints, cur.dangling_endpoints], ['Wall segments', orig.walls, cur.walls],
                  ['Doors', orig.doors, cur.doors], ['Windows', orig.windows, cur.windows], ['All openings', orig.openings, cur.openings]].map(([l, a, b]) => (
                  <tr key={l}><td>{l}</td><td className="text-right tabular-nums">{a}</td><td className="text-right tabular-nums">{b}</td></tr>
                ))}
              </tbody>
            </table>
          </Disclosure>

          <Disclosure title="Full room schedule" subtitle={`${result.geometry.corrected.rooms.length} rooms`}>
            {result.geometry.corrected.rooms.length === 0 ? <p className="text-[12.5px] text-ink-mute">No enclosed rooms were detected.</p> : (
              <table className="table">
                <thead><tr><th>Room</th><th>Type</th><th className="text-right">Length</th><th className="text-right">Width</th><th className="text-right">Area</th><th>Label on plan</th></tr></thead>
                <tbody>
                  {[...result.geometry.corrected.rooms].sort((a, b) => b.area_m2 - a.area_m2).map((r) => (
                    <tr key={r.id}><td className="text-ink font-medium">{r.name}</td><td>{ROOM_TYPE_LABEL[r.type]}</td>
                      <td className="text-right tabular-nums">{r.length_m.toFixed(2)} m</td><td className="text-right tabular-nums">{r.width_m.toFixed(2)} m</td>
                      <td className="text-right tabular-nums">{r.area_m2.toFixed(1)} m²</td>
                      <td className="font-mono text-ink-mute">{r.label_dims || '—'}{r.rectangularity < 0.85 && <span className="font-sans text-[11px] ml-2">(irregular: bounding size)</span>}</td></tr>
                  ))}
                </tbody>
              </table>
            )}
          </Disclosure>

          <Disclosure title="Ground-truth annotation upload">
            <div className="flex items-start gap-3 text-[12.5px] text-ink-soft">
              <FileJson size={18} className="text-ink-mute mt-0.5 shrink-0" />
              <div className="flex-1">
                Upload a JSON file listing the true rooms, doors and windows of <b className="font-medium">this</b> plan in image pixels.
                All four configurations are then re-run on this plan and scored. Your manual fixes and manual calibration are not counted.
                <pre className="mt-2 text-[11.5px] bg-paper border border-line rounded-lg p-3 overflow-auto">{`{
  "meters_per_px": 0.02,
  "rooms":   [{ "polygon": [[x, y], ...], "type": "bedroom" }],
  "doors":   [{ "x1": 0, "y1": 0, "x2": 0, "y2": 0 }],
  "windows": [{ "x1": 0, "y1": 0, "x2": 0, "y2": 0 }]
}`}</pre>
                <button className="btn-secondary btn-sm mt-2" onClick={() => fileRef.current?.click()} disabled={evalBusy}><Upload size={13} />Upload annotation</button>
                {evalRes && <span className="ml-3 text-ok">Annotation evaluated.</span>}
              </div>
            </div>
          </Disclosure>

          <Disclosure title="Precision, recall, IoU and F1 details" subtitle={evalRes ? 'this plan' : benchOk ? 'synthetic benchmark' : ''}>
            {(evalRes?.configs || (benchOk && bench.results)) ? (
              <>
                <p className="text-[12px] text-ink-mute mb-2">Source: {evalRes ? 'this plan, scored against your annotation' : bench.dataset.label}</p>
                <MetricTable configs={evalRes?.configs || bench.results} />
                <div className="mt-4"><DetectionDetails configs={evalRes?.configs || bench.results} /></div>
              </>
            ) : <p className="text-[12.5px] text-ink-mute">Not evaluated.</p>}
          </Disclosure>

          {benchOk && (
            <Disclosure title="Complete benchmark tables" subtitle={bench.dataset.label}>
              <p className="text-[12px] text-ink-mute mb-3">{bench.dataset.description} {bench.parser}. Seeds {bench.dataset.seeds[0]}–{bench.dataset.seeds[1]}.</p>
              <MetricTable configs={bench.results} />
              <div className="mt-4 overflow-auto">
                <table className="table">
                  <thead><tr><th>Plan</th><th className="text-right">Rooms</th><th>Units</th>
                    {CONFIG_ORDER.map((c) => <th key={c.key} className="text-right">{c.label}: recall</th>)}<th className="text-right">Full: scale error</th></tr></thead>
                  <tbody>
                    {bench.per_plan.map((p) => (
                      <tr key={p.seed}><td>#{p.seed}</td><td className="text-right">{p.rooms}</td><td>{p.units}</td>
                        {CONFIG_ORDER.map((c) => <td key={c.key} className="text-right tabular-nums">{pct(p[c.key].room_recall, 0)}</td>)}
                        <td className="text-right tabular-nums">{p.full.scale_error_pct == null ? 'N/A' : `${p.full.scale_error_pct.toFixed(1)}%`}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <dl className="mt-4 grid grid-cols-[200px_1fr] gap-y-1 text-[12px]">
                {Object.entries(bench.definitions || {}).map(([k, v]) => (<Fragment key={k}><dt className="text-ink-soft font-mono">{k}</dt><dd className="text-ink-mute">{v}</dd></Fragment>))}
              </dl>
            </Disclosure>
          )}
        </div>
      </div>
    </div>
  )
}
