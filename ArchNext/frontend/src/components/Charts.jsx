import { useState } from 'react'
import { Bar, BarChart, CartesianGrid, Cell, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { ChevronDown, Info } from 'lucide-react'

// Categorical palette (validated for lightness, chroma and colour-blind separation).
export const CONFIG_COLOR = {
  baseline: '#eb6834',
  topologyguard_only: '#1baf7a',
  scalelock_only: '#eda100',
  full: '#2a78d6',
}

export const METRICS = {
  room_recall: { label: 'Room recall', kind: 'ratio', better: 'higher', tip: 'Share of the real rooms that were found (overlap of at least 50%).' },
  room_precision: { label: 'Room precision', kind: 'ratio', better: 'higher', tip: 'Share of detected rooms that are real rooms.' },
  room_iou_all: { label: 'Room overlap (IoU)', kind: 'ratio', better: 'higher', tip: 'How well detected room shapes overlap the real ones (intersection over union). Missed rooms count as 0.' },
  structural_consistency: { label: 'Wall connectivity', kind: 'ratio', better: 'higher', tip: 'Share of wall ends that connect to another wall or to a door/window.' },
  dimension_error_pct: { label: 'Dimension error', kind: 'pct', better: 'lower', tip: 'Average difference between measured and true room length/width.' },
  scale_error_pct: { label: 'Scale error', kind: 'pct', better: 'lower', tip: 'Difference between the computed and true metres-per-pixel scale.' },
  doors_f1: { label: 'Door F1', kind: 'ratio', better: 'higher', tip: 'Door detection score combining precision and recall (1.0 is perfect).' },
  windows_f1: { label: 'Window F1', kind: 'ratio', better: 'higher', tip: 'Window detection score combining precision and recall (1.0 is perfect).' },
}

export function metricValue(res, key) {
  if (!res) return null
  if (key === 'doors_f1') return res.doors ? res.doors.f1 : null
  if (key === 'windows_f1') return res.windows ? res.windows.f1 : null
  const v = res[key]
  return v === undefined ? null : v
}

/** Values on the chart are shown in percent for ratios and percentage errors. */
export function asPercent(key, v) {
  if (v == null) return null
  return METRICS[key].kind === 'ratio' ? v * 100 : v
}

export function fmtMetric(key, v) {
  if (v == null) return 'N/A'
  if (key === 'doors_f1' || key === 'windows_f1') return v.toFixed(2)
  return `${asPercent(key, v).toFixed(1)}%`
}

export function InfoTip({ text }) {
  return (
    <span className="relative group inline-flex align-middle">
      <Info size={13} className="text-ink-mute cursor-help" aria-label={text} />
      <span className="pointer-events-none absolute left-1/2 -translate-x-1/2 bottom-full mb-1.5 w-56 rounded-md bg-ink text-white text-[11.5px] leading-snug px-2.5 py-1.5 opacity-0 group-hover:opacity-100 z-20 font-normal normal-case tracking-normal">
        {text}
      </span>
    </span>
  )
}

export function BetterHint({ better }) {
  return (
    <span className="text-[11px] text-ink-mute">{better === 'higher' ? '↑ Higher is better' : '↓ Lower is better'}</span>
  )
}

/** Horizontal bars, one per configuration, for a single metric (one scale per chart). */
export function ConfigBarChart({ rows, metric, height }) {
  const m = METRICS[metric]
  const data = rows.map((r) => ({
    name: r.label, key: r.key, value: asPercent(metric, metricValue(r.res, metric)), raw: metricValue(r.res, metric),
  }))
  const isF1 = metric === 'doors_f1' || metric === 'windows_f1'
  const vals = data.map((d) => d.value).filter((v) => v != null)
  const max = m.kind === 'ratio' ? 100 : Math.max(5, Math.ceil((Math.max(0, ...vals) * 1.2) / 5) * 5)
  const fmt = (v) => (v == null ? 'N/A' : isF1 ? (v / 100).toFixed(2) : `${v.toFixed(1)}%`)
  return (
    <ResponsiveContainer width="100%" height={height || 44 * data.length + 40}>
      <BarChart data={data} layout="vertical" margin={{ top: 4, right: 56, bottom: 18, left: 8 }} barCategoryGap={8}>
        <CartesianGrid horizontal={false} stroke="#ECE8E1" />
        <XAxis type="number" domain={[0, max]} tickFormatter={(v) => (isF1 ? (v / 100).toFixed(1) : `${v}%`)}
               tick={{ fontSize: 11, fill: '#7C818A' }} axisLine={{ stroke: '#D9D4CA' }} tickLine={false}
               label={{ value: `${m.label}${isF1 ? '' : ' (%)'}`, position: 'insideBottom', offset: -10, fontSize: 11, fill: '#7C818A' }} />
        <YAxis type="category" dataKey="name" width={132} tick={{ fontSize: 12, fill: '#26292E' }} axisLine={false} tickLine={false} />
        <Tooltip cursor={{ fill: 'rgba(63,106,143,0.06)' }} formatter={(v) => [fmt(v), m.label]}
                 contentStyle={{ fontSize: 12, borderRadius: 8, borderColor: '#E4E0D8' }} />
        <Bar dataKey="value" isAnimationActive={false} radius={[0, 4, 4, 0]} maxBarSize={22}>
          {data.map((d) => <Cell key={d.key} fill={CONFIG_COLOR[d.key]} />)}
          <LabelList dataKey="value" position="right" formatter={fmt} style={{ fontSize: 12, fill: '#26292E', fontWeight: 600 }} />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

export function Disclosure({ title, children, defaultOpen = false, subtitle }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="card">
      <button onClick={() => setOpen((v) => !v)} className="w-full px-5 py-3 flex items-center gap-2 text-left hover:bg-paper/60 rounded-xl">
        <ChevronDown size={15} className={`text-ink-mute transition-transform ${open ? '' : '-rotate-90'}`} />
        <span className="card-title">{title}</span>
        {subtitle && <span className="text-[12px] text-ink-mute ml-2">{subtitle}</span>}
      </button>
      {open && <div className="px-5 pb-5 pt-1">{children}</div>}
    </div>
  )
}
