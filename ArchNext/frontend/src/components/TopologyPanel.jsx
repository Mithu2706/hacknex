import { useMemo, useState } from 'react'
import { AlertTriangle, Check, CheckCircle2, ChevronDown, Eye, Hand, Info, Loader2, MapPin, Undo2, Wand2, Wrench, X } from 'lucide-react'

const STATUS_ICON = {
  pass: <CheckCircle2 size={15} className="text-ok" />,
  corrected: <Wrench size={14} className="text-accent" />,
  review: <AlertTriangle size={14} className="text-warn" />,
}

const cleanMsg = (m) => m.replace(/\s*Manual review required\.$/, '')

function Collapsible({ title, count, children, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="border border-line rounded-lg">
      <button className="w-full flex items-center gap-2 px-3 py-2 text-[12.5px] font-medium text-ink-soft hover:bg-paper rounded-lg"
              onClick={() => setOpen((v) => !v)}>
        <ChevronDown size={14} className={`transition-transform ${open ? '' : '-rotate-90'}`} />
        {title}{count != null && <span className="text-ink-mute font-normal">({count})</span>}
      </button>
      {open && <div className="px-3 pb-3">{children}</div>}
    </div>
  )
}

export default function TopologyPanel({ result, selected, onSelect, preview, onPreview, onCancelPreview, onApply, onUndo, busy, notice, error }) {
  const { checks, issues } = result.topology
  const o = result.geometry.original.stats
  const c = result.geometry.corrected.stats
  const nameOf = Object.fromEntries(checks.map((ch) => [ch.key, ch.name]))
  const review = useMemo(() => issues.filter((i) => i.status === 'review')
    .sort((a, b) => (b.fixable - a.fixable) || (a.severity === 'info') - (b.severity === 'info')), [issues])
  const auto = issues.filter((i) => i.status === 'corrected')
  const fixed = issues.filter((i) => i.status === 'fixed')
  const fixable = review.filter((i) => i.fixable).length

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-4 gap-2">
        {[
          ['Auto-corrected', auto.length, 'text-accent', 'Fixed automatically by TopologyGuard during reconstruction'],
          ['Fixed by you', fixed.length, 'text-ok', 'Corrections you applied in this session'],
          ['Can be fixed', fixable, 'text-ink', 'Remaining issues with a safe, previewable fix'],
          ['Manual review', review.length - fixable, 'text-warn', 'Issues that cannot be corrected safely without a human decision'],
        ].map(([l, v, cls, tip]) => (
          <div key={l} className="rounded-lg border border-line p-2 bg-paper/50" title={tip}>
            <div className={`text-[17px] font-semibold tabular-nums ${cls}`}>{v}</div>
            <div className="text-[10.5px] text-ink-mute leading-tight">{l}</div>
          </div>
        ))}
      </div>

      <div className="flex items-center gap-2">
        <p className="text-[12.5px] text-ink-soft flex-1">
          {review.length === 0
            ? 'All structural checks pass on the current geometry.'
            : `${review.length} item${review.length === 1 ? '' : 's'} remain: ${fixable} can be fixed safely, ${review.length - fixable} need${review.length - fixable === 1 ? 's' : ''} manual review.`}
        </p>
        <button className="btn-secondary btn-sm" onClick={onUndo} disabled={!result.topology.can_undo || busy} title="Undo your last fix">
          <Undo2 size={13} />Undo
        </button>
      </div>

      {notice && (
        <div className={`rounded-lg border px-3 py-2 text-[12.5px] flex gap-2 ${notice.ok ? 'border-ok/30 bg-ok/5 text-ok' : 'border-warn/30 bg-warn/5 text-warn'}`}>
          {notice.ok ? <Check size={14} className="mt-0.5 shrink-0" /> : <AlertTriangle size={14} className="mt-0.5 shrink-0" />}
          <span className="text-ink-soft">{notice.text}</span>
        </div>
      )}
      {error && <p className="text-[12.5px] text-bad">{error}</p>}

      <div>
        <div className="label mb-2">Needs attention</div>
        {review.length === 0 ? (
          <div className="text-[12.5px] text-ink-mute border border-dashed border-line rounded-lg p-4 text-center">No remaining structural issues.</div>
        ) : (
          <ul className="space-y-1.5">
            {review.map((i) => {
              const isSel = selected === i.key
              const isPrev = preview?.key === i.key
              return (
                <li key={i.key} className={`rounded-lg border transition-colors ${isPrev ? 'border-ok bg-ok/5' : isSel ? 'border-accent bg-accent-soft/50' : 'border-line'}`}>
                  <button className="w-full text-left px-3 pt-2" onClick={() => onSelect(isSel ? null : i.key)}>
                    <div className="flex items-center gap-2">
                      {i.fixable ? <Wand2 size={13} className="text-accent shrink-0" /> : i.severity === 'info'
                        ? <Info size={13} className="text-ink-mute shrink-0" /> : <AlertTriangle size={13} className="text-warn shrink-0" />}
                      <span className="text-[11.5px] font-medium text-ink-soft">{nameOf[i.check]}</span>
                      <MapPin size={12} className={`ml-auto ${isSel ? 'text-accent' : 'text-ink-mute'}`} />
                    </div>
                    <div className="text-[12px] text-ink-soft mt-1 leading-snug">{cleanMsg(i.message)}</div>
                  </button>
                  <div className="px-3 pb-2 pt-1.5 flex items-center gap-2">
                    {i.fixable ? (
                      isPrev ? null : (
                        <button className="btn-primary btn-sm h-7" disabled={busy || !!preview} onClick={() => onPreview(i)}>
                          <Eye size={13} />Fix: {i.fix.label}
                        </button>
                      )
                    ) : (
                      <span className="chip bg-warn/10 text-warn"><Hand size={11} />Manual review required</span>
                    )}
                  </div>
                  {isPrev && (
                    <div className="mx-3 mb-3 rounded-md border border-ok/30 bg-white p-2.5">
                      <div className="text-[12px] font-medium text-ink">Preview: {i.fix.label}</div>
                      <div className="text-[11.5px] text-ink-mute mt-1 flex flex-wrap gap-x-3 gap-y-1">
                        <span className="flex items-center gap-1"><span className="w-3 h-2 rounded-sm border border-dashed border-bad bg-bad/20" />current</span>
                        <span className="flex items-center gap-1"><span className="w-3 h-2 rounded-sm bg-ok" />after the fix</span>
                        {i.fix.removed.length > 0 && <span>{i.fix.removed.length} segment removed</span>}
                      </div>
                      <div className="flex gap-2 mt-2.5">
                        <button className="btn-secondary btn-sm flex-1" onClick={onCancelPreview} disabled={busy}><X size={13} />Cancel</button>
                        <button className="btn-primary btn-sm flex-1" onClick={() => onApply(i)} disabled={busy}>
                          {busy ? <Loader2 size={13} className="animate-spin" /> : <Check size={13} />}Apply
                        </button>
                      </div>
                    </div>
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </div>

      {fixed.length > 0 && (
        <Collapsible title="Fixed by you" count={fixed.length} defaultOpen>
          <ul className="space-y-1">
            {fixed.map((i) => <li key={i.key} className="text-[12px] text-ink-soft flex gap-2"><Check size={13} className="text-ok mt-0.5 shrink-0" />{cleanMsg(i.message)}</li>)}
          </ul>
        </Collapsible>
      )}

      <Collapsible title="Automatic corrections" count={auto.length}>
        {auto.length === 0 ? <p className="text-[12px] text-ink-mute">None were needed for this plan.</p> : (
          <ul className="space-y-1">
            {auto.map((i) => (
              <li key={i.key}><button className="text-left text-[12px] text-ink-soft flex gap-2 hover:text-ink" onClick={() => onSelect(i.key)}>
                <Wrench size={12} className="text-accent mt-0.5 shrink-0" />{i.message}</button></li>
            ))}
          </ul>
        )}
      </Collapsible>

      <Collapsible title="Before → after TopologyGuard">
        <div className="grid grid-cols-[1fr_auto_auto] gap-x-4 gap-y-1 text-[12.5px]">
          <span className="text-ink-mute text-[11px]">Measure</span><span className="text-ink-mute text-[11px] text-right">Detected</span><span className="text-ink-mute text-[11px] text-right">Now</span>
          {[
            ['Rooms enclosed', o.rooms, c.rooms, c.rooms >= o.rooms],
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
      </Collapsible>

      <Collapsible title="All structural checks" count={checks.length}>
        <ul className="divide-y divide-line">
          {checks.map((ch) => (
            <li key={ch.key} className="py-2 flex items-start gap-2.5">
              <span className="mt-0.5">{STATUS_ICON[ch.status]}</span>
              <div className="flex-1 min-w-0">
                <div className="text-[12.5px] font-medium">{ch.name}</div>
                <div className="text-[11.5px] text-ink-mute leading-snug">{ch.description}</div>
              </div>
              <div className="text-[11px] text-ink-mute text-right whitespace-nowrap">
                {ch.detected === 0 ? 'Pass' : (
                  <>{ch.corrected > 0 && <div className="text-accent">{ch.corrected} auto</div>}
                    {ch.fixed > 0 && <div className="text-ok">{ch.fixed} fixed</div>}
                    {ch.review > 0 && <div className="text-warn">{ch.review} open</div>}</>
                )}
              </div>
            </li>
          ))}
        </ul>
      </Collapsible>
    </div>
  )
}
