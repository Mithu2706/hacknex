import { Box, FileUp, Layers, Plus, ShieldCheck } from 'lucide-react'

const TABS = [
  { key: 'upload', label: 'Upload', icon: FileUp },
  { key: 'analysis', label: 'Analysis', icon: Layers },
  { key: 'studio', label: '3D Studio', icon: Box },
  { key: 'validation', label: 'Validation', icon: ShieldCheck },
]

export default function Header({ view, onView, hasResult, filename, onNew }) {
  return (
    <header className="h-14 shrink-0 bg-white/90 backdrop-blur border-b border-line flex items-center px-5 gap-6">
      <div className="flex items-center gap-2.5 min-w-[210px]">
        <svg viewBox="0 0 32 32" className="w-7 h-7" aria-hidden>
          <rect width="32" height="32" rx="7" fill="#3F6A8F" />
          <path d="M8 23V9h9v6h7v8z" fill="none" stroke="#fff" strokeWidth="2.2" strokeLinejoin="round" />
        </svg>
        <div className="leading-tight">
          <div className="text-[14px] font-semibold tracking-tight">ArchNext</div>
          <div className="text-[11px] text-ink-mute">Every Line Becomes a Space.</div>
        </div>
      </div>

      <nav className="flex items-center gap-1 mx-auto">
        {TABS.map(({ key, label, icon: Icon }, i) => {
          const disabled = key !== 'upload' && !hasResult
          const active = view === key
          return (
            <button key={key} disabled={disabled} onClick={() => onView(key)}
              className={`h-9 px-3.5 rounded-lg flex items-center gap-2 text-[13px] font-medium transition-colors
                ${active ? 'bg-accent-soft text-accent-dark' : 'text-ink-soft hover:bg-paper'}
                disabled:opacity-35 disabled:hover:bg-transparent disabled:cursor-not-allowed`}>
              <span className={`w-5 h-5 rounded-full text-[10.5px] grid place-items-center border
                ${active ? 'border-accent/40 bg-white' : 'border-line'}`}>{i + 1}</span>
              <Icon size={15} strokeWidth={1.8} />
              {label}
            </button>
          )
        })}
      </nav>

      <div className="flex items-center gap-3 min-w-[210px] justify-end">
        {filename && <span className="text-[12px] text-ink-mute truncate max-w-[160px]" title={filename}>{filename}</span>}
        {hasResult && (
          <button className="btn-secondary btn-sm" onClick={onNew}><Plus size={14} />New plan</button>
        )}
      </div>
    </header>
  )
}
