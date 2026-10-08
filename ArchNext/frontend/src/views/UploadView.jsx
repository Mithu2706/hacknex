import { useEffect, useRef, useState } from 'react'
import { AlertTriangle, ArrowRight, Image as ImageIcon, Loader2, RefreshCw, Upload, X } from 'lucide-react'

const ACCEPT = ['image/png', 'image/jpeg', 'image/webp']
const STAGES = [
  'Reading and cleaning the drawing',
  'Detecting walls, rooms, doors and windows',
  'Validating structure with TopologyGuard',
  'Calibrating real-world scale with ScaleLock',
]

function Elapsed() {
  const [s, setS] = useState(0)
  useEffect(() => {
    const t = setInterval(() => setS((v) => v + 1), 1000)
    return () => clearInterval(t)
  }, [])
  return <span className="tabular-nums">{s}s</span>
}

export default function UploadView({ file, preview, status, error, result, onFile, onGenerate, onOpen }) {
  const input = useRef(null)
  const [drag, setDrag] = useState(false)
  const [localError, setLocalError] = useState('')
  const [dims, setDims] = useState(null)

  const pick = (f) => {
    if (!f) return
    if (!ACCEPT.includes(f.type)) {
      setLocalError('Please choose a PNG, JPG or WebP image of a floor plan.')
      return
    }
    if (f.size > 25 * 1024 * 1024) {
      setLocalError('The file is larger than 25 MB.')
      return
    }
    setLocalError('')
    setDims(null)
    onFile(f)
  }

  const processing = status === 'processing'

  if (!file) {
    return (
      <div className="h-full grid place-items-center p-8">
        <div className="w-full max-w-2xl">
          <div className="mb-6">
            <h1 className="text-[22px] font-semibold tracking-tight">Upload a floor plan</h1>
            <p className="text-[13.5px] text-ink-soft mt-1">
              ArchNext reads the walls, rooms, doors and windows in your drawing and rebuilds it as a scaled, explorable 3D model.
            </p>
          </div>
          <div
            onDragOver={(e) => { e.preventDefault(); setDrag(true) }}
            onDragLeave={() => setDrag(false)}
            onDrop={(e) => { e.preventDefault(); setDrag(false); pick(e.dataTransfer.files?.[0]) }}
            onClick={() => input.current?.click()}
            className={`card cursor-pointer border-dashed border-2 h-72 grid place-items-center text-center transition-colors
              ${drag ? 'border-accent bg-accent-soft/50' : 'hover:border-accent/50'}`}>
            <div>
              <div className="w-12 h-12 rounded-xl bg-accent-soft text-accent grid place-items-center mx-auto mb-4">
                <Upload size={22} strokeWidth={1.8} />
              </div>
              <div className="text-[14px] font-medium">Drop a floor plan here, or <span className="text-accent">browse</span></div>
              <div className="text-[12px] text-ink-mute mt-1.5">PNG, JPG or WebP · up to 25 MB</div>
            </div>
          </div>
          <input ref={input} type="file" accept=".png,.jpg,.jpeg,.webp" className="hidden"
                 onChange={(e) => { pick(e.target.files?.[0]); e.target.value = '' }} />
          {localError && <p className="mt-3 text-[12.5px] text-bad flex items-center gap-1.5"><AlertTriangle size={14} />{localError}</p>}
          <div className="grid grid-cols-3 gap-3 mt-6">
            {[
              ['Best results', 'Clean architectural plans with solid, dark walls.'],
              ['Dimensions', 'Room labels such as 3.4 x 4.1 m or 11\'1" x 13\'6" set the scale automatically.'],
              ['No labels?', 'You can calibrate the scale by marking a known distance.'],
            ].map(([t, d]) => (
              <div key={t} className="card p-3.5">
                <div className="text-[12.5px] font-medium">{t}</div>
                <div className="text-[12px] text-ink-mute mt-1 leading-relaxed">{d}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="h-full p-6 grid grid-cols-[1fr_340px] gap-5 min-h-0">
      <div className="card min-h-0 flex flex-col overflow-hidden">
        <div className="h-11 px-4 border-b border-line flex items-center gap-2 text-[12.5px] text-ink-soft">
          <ImageIcon size={15} /> Blueprint preview
        </div>
        <div className="flex-1 min-h-0 p-5 grid place-items-center bg-[repeating-linear-gradient(0deg,transparent,transparent_23px,#efece6_24px),repeating-linear-gradient(90deg,transparent,transparent_23px,#efece6_24px)]">
          <img src={preview} alt="Uploaded floor plan" className="max-w-full max-h-full object-contain bg-white shadow-card rounded"
               onLoad={(e) => setDims([e.target.naturalWidth, e.target.naturalHeight])} />
        </div>
      </div>

      <aside className="flex flex-col gap-4">
        <div className="card p-4">
          <div className="label mb-2">Selected file</div>
          <div className="flex items-start gap-3">
            <div className="min-w-0 flex-1">
              <div className="text-[13.5px] font-medium truncate" title={file.name}>{file.name}</div>
              <div className="text-[12px] text-ink-mute mt-0.5">
                {(file.size / 1024).toFixed(0)} KB{dims ? ` · ${dims[0]} × ${dims[1]} px` : ''}
              </div>
            </div>
            {!processing && (
              <button className="btn-ghost btn-sm" onClick={() => onFile(null)} title="Remove"><X size={14} /></button>
            )}
          </div>
        </div>

        {status === 'ready' && result ? (
          <div className="card p-4">
            <div className="text-[13px] font-medium">Reconstruction ready</div>
            <p className="text-[12.5px] text-ink-mute mt-1">This plan has already been processed.</p>
            <button className="btn-primary w-full mt-4" onClick={onOpen}>Open analysis <ArrowRight size={15} /></button>
          </div>
        ) : processing ? (
          <div className="card p-4">
            <div className="flex items-center gap-2 text-[13px] font-medium">
              <Loader2 size={16} className="animate-spin text-accent" /> Reconstructing… <span className="ml-auto text-ink-mute text-[12px]"><Elapsed /></span>
            </div>
            <ul className="mt-3 space-y-2">
              {STAGES.map((s) => (
                <li key={s} className="text-[12.5px] text-ink-soft flex items-center gap-2">
                  <span className="w-1.5 h-1.5 rounded-full bg-accent/50" />{s}
                </li>
              ))}
            </ul>
            <p className="text-[11.5px] text-ink-mute mt-3">Most plans take a few seconds.</p>
          </div>
        ) : (
          <div className="card p-4">
            {status === 'error' && (
              <div className="mb-4 rounded-lg bg-bad/5 border border-bad/20 p-3">
                <div className="flex items-center gap-1.5 text-[12.5px] font-medium text-bad"><AlertTriangle size={14} />Reconstruction failed</div>
                <p className="text-[12.5px] text-ink-soft mt-1">{error}</p>
              </div>
            )}
            <button className="btn-primary w-full h-10" onClick={onGenerate}>
              {status === 'error' ? <><RefreshCw size={15} />Try again</> : <>Generate 3D <ArrowRight size={15} /></>}
            </button>
            <button className="btn-secondary w-full mt-2" onClick={() => input.current?.click()}>Choose another image</button>
            <input ref={input} type="file" accept=".png,.jpg,.jpeg,.webp" className="hidden"
                   onChange={(e) => { pick(e.target.files?.[0]); e.target.value = '' }} />
            {localError && <p className="mt-3 text-[12px] text-bad">{localError}</p>}
          </div>
        )}
      </aside>
    </div>
  )
}
