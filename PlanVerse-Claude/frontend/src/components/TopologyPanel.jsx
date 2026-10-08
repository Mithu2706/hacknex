import { useMemo, useState } from 'react'
import { AlertTriangle, CheckCircle2, Info, Wrench } from 'lucide-react'

const STATUS_ICON = {
  pass: <CheckCircle2 size={15} className="text-ok" />,
  corrected: <Wrench size={14} className="text-accent" />,
  review: <AlertTriangle size={14} className="text-warn" />,
}

export default function TopologyPanel({ result, selected, onSelect }) {
  const [filter, setFilter] = useState('all')
  const { checks, issues } = result.topology
  const o = result.geometry.original.stats
  const c = result.geometry.corrected.stats
  const shown = useMemo(() => issues.filter((i) => filter === 'all' || i.status === filter), [issues, filter])
  const nameOf = Object.fromEntries(checks.map((ch) => [ch.key, ch.name]))

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-2">
        {[
          ['Checks run', checks.length, 'text-ink'],
          ['Auto-corrected', result.topology.corrected, 'text-accent'],
          ['Needs review', result.topology.review, 'text-warn'],
        ].map(([l, v, cls]) => (
          <div key={l} className="rounded-lg border border-line p-2.5 bg-paper/50">
            <div className={`text-[18px] font-semibold tabular-nums ${cls}`}>{v}</div>
            <div className="text-[11px] text-ink-mute">{l}</div>
          </div>
        ))}
      </div>

      <div className="rounded-lg border border-line p-3">
        <div className="label mb-2">Before → after TopologyGuard</div>
        <div className="grid grid-cols-[1fr_auto_auto] gap-x-4 gap-y-1 text-[12.5px]">
          {[
            ['Rooms enclosed', o.rooms, c.rooms, true],
            ['Connected wall ends', `${Math.round(o.connected_endpoint_ratio * 100)}%`, `${Math.round(c.connected_endpoint_ratio * 100)}%`, c.connected_endpoint_ratio >= o.connected_endpoint_ratio],
            ['Disconnected ends', o.dangling_endpoints, c.dangling_endpoints, c.dangling_endpoints <= o.dangling_endpoints],
            ['Wall segments', o.walls, c.walls, null],
          ].map(([l, a, b, good]) => (
            <div key={l} className="contents">
              <span className="text-ink-soft">{l}</span>
              <span className="text-ink-mute tabular-nums text-right">{a}</span>
              <span className={`tabular-nums text-right font-medium ${good === null ? 'text-ink' : good ? 'text-ok' : 'text-warn'}`}>{b}</span>
            </div>
          ))}
        </div>
      </div>

      <div>
        <div className="label mb-2">Structural checks</div>
        <ul className="divide-y divide-line border border-line rounded-lg">
          {checks.map((ch) => (
            <li key={ch.key} className="px-3 py-2 flex items-start gap-2.5">
              <span className="mt-0.5">{STATUS_ICON[ch.status]}</span>
              <div className="flex-1 min-w-0">
                <div className="text-[12.5px] font-medium">{ch.name}</div>
                <div className="text-[11.5px] text-ink-mute leading-snug">{ch.description}</div>
              </div>
              <div className="text-[11px] text-ink-mute text-right whitespace-nowrap">
                {ch.detected === 0 ? 'No issues' : (
                  <>{ch.corrected > 0 && <div className="text-accent">{ch.corrected} fixed</div>}
                    {ch.review > 0 && <div className="text-warn">{ch.review} review</div>}
                    {ch.detected - ch.corrected - ch.review > 0 && <div>{ch.detected - ch.corrected - ch.review} note</div>}</>
                )}
              </div>
            </li>
          ))}
        </ul>
      </div>

      <div>
        <div className="flex items-center justify-between mb-2">
          <div className="label">Issues ({shown.length})</div>
          <div className="seg">
            {[['all', 'All'], ['corrected', 'Corrected'], ['review', 'Review']].map(([k, l]) => (
              <button key={k} data-active={filter === k} onClick={() => setFilter(k)}>{l}</button>
            ))}
          </div>
        </div>
        {shown.length === 0 ? (
          <div className="text-[12.5px] text-ink-mute border border-dashed border-line rounded-lg p-4 text-center">Nothing to show.</div>
        ) : (
          <ul className="space-y-1.5">
            {shown.map((i) => (
              <li key={i.id}>
                <button onClick={() => onSelect(i.id === selected ? null : i.id)}
                  className={`w-full text-left rounded-lg border px-3 py-2 transition-colors
                    ${selected === i.id ? 'border-accent bg-accent-soft/60' : 'border-line hover:bg-paper'}`}>
                  <div className="flex items-center gap-2">
                    {i.status === 'corrected' ? <Wrench size={13} className="text-accent shrink-0" />
                      : i.status === 'review' ? <AlertTriangle size={13} className="text-warn shrink-0" />
                        : <Info size={13} className="text-ink-mute shrink-0" />}
                    <span className="text-[11.5px] font-medium text-ink-soft">{nameOf[i.check]}</span>
                    <span className={`ml-auto chip ${i.status === 'corrected' ? 'bg-accent-soft text-accent-dark' : i.status === 'review' ? 'bg-warn/10 text-warn' : 'bg-paper text-ink-mute'}`}>
                      {i.status === 'corrected' ? 'Auto-corrected' : i.status === 'review' ? 'Review' : 'Note'}
                    </span>
                  </div>
                  <div className="text-[12px] text-ink-soft mt-1 leading-snug">{i.message}</div>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
