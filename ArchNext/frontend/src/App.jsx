import { useCallback, useEffect, useState } from 'react'
import Header from './components/Header.jsx'
import UploadView from './views/UploadView.jsx'
import AnalysisView from './views/AnalysisView.jsx'
import StudioView from './views/StudioView.jsx'
import ValidationView from './views/ValidationView.jsx'
import { api } from './lib/api.js'

export default function App() {
  const [view, setView] = useState('upload')
  const [file, setFile] = useState(null)
  const [preview, setPreview] = useState(null)
  const [status, setStatus] = useState('idle') // idle | processing | ready | error
  const [error, setError] = useState('')
  const [result, setResult] = useState(null)

  useEffect(() => () => preview && URL.revokeObjectURL(preview), [preview])

  const chooseFile = useCallback((f) => {
    setFile(f)
    setPreview(f ? URL.createObjectURL(f) : null)
    setResult(null)
    setStatus('idle')
    setError('')
    setView('upload')
  }, [])

  const generate = useCallback(async () => {
    if (!file) return
    setStatus('processing')
    setError('')
    try {
      const r = await api.upload(file)
      setResult(r)
      setStatus('ready')
      setView('analysis')
    } catch (e) {
      setError(e.message)
      setStatus('error')
    }
  }, [file])

  const newPlan = useCallback(() => chooseFile(null), [chooseFile])

  return (
    <div className="h-full flex flex-col">
      <Header view={view} onView={setView} hasResult={!!result} filename={result?.filename} onNew={newPlan} />
      <main className="flex-1 min-h-0">
        {view === 'upload' && (
          <UploadView file={file} preview={preview} status={status} error={error} result={result}
                      onFile={chooseFile} onGenerate={generate} onOpen={() => setView('analysis')} />
        )}
        {view === 'analysis' && result && <AnalysisView result={result} onResult={setResult} onStudio={() => setView('studio')} />}
        {view === 'studio' && result && <StudioView result={result} onCalibrate={() => setView('analysis')} />}
        {view === 'validation' && result && <ValidationView result={result} />}
      </main>
    </div>
  )
}
