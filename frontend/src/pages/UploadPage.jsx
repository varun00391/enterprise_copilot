import { useState, useCallback, useRef } from 'react'
import { useDropzone } from 'react-dropzone'
import {
  Upload, FileText, X, CheckCircle, AlertCircle,
  Loader2, FileSpreadsheet, File, Image, Tag, Globe, Plus, Link, Video
} from 'lucide-react'
import api from '../lib/api'
import clsx from 'clsx'
import { useAuth } from '../context/AuthContext'
import SelectDepartmentModal from '../components/SelectDepartmentModal'

const MAX_SIZE_MB = 50
const MAX_FILES_PER_BATCH = 20
/** Maps to real MIME types so the OS file picker and drag-drop accept mixed formats reliably. */
const ACCEPT_BY_EXT = {
  pdf: ['application/pdf'],
  docx: ['application/vnd.openxmlformats-officedocument.wordprocessingml.document'],
  txt: ['text/plain'],
  xlsx: ['application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'],
  xls: ['application/vnd.ms-excel'],
  csv: ['text/csv', 'application/vnd.ms-excel'],
  json: ['application/json'],
  png: ['image/png'],
  jpg: ['image/jpeg'],
  jpeg: ['image/jpeg'],
  pptx: ['application/vnd.openxmlformats-officedocument.presentationml.presentation'],
  mp3: ['audio/mpeg', 'audio/mp3'],
  wav: ['audio/wav', 'audio/x-wav'],
  m4a: ['audio/mp4', 'audio/x-m4a'],
  mp4: ['video/mp4'],
  mov: ['video/quicktime'],
  webm: ['video/webm', 'audio/webm'],
  mkv: ['video/x-matroska'],
  avi: ['video/x-msvideo', 'video/avi'],
  wmv: ['video/x-ms-wmv'],
  flv: ['video/x-flv'],
  mpg: ['video/mpeg'],
  mpeg: ['video/mpeg'],
  m4v: ['video/x-m4v'],
  '3gp': ['video/3gpp'],
  '3g2': ['video/3gpp2'],
  ogv: ['video/ogg'],
  ts: ['video/mp2t'],
  m2ts: ['video/mp2t'],
  vob: ['video/dvd'],
  f4v: ['video/x-f4v'],
  asf: ['video/x-ms-asf'],
  divx: ['video/divx'],
  mxf: ['application/mxf'],
}
const ALLOWED = Object.keys(ACCEPT_BY_EXT)
/** Merge MIME keys so shared types (e.g. JPG/JPEG → image/jpeg) list every extension once. */
const dropzoneAccept = ALLOWED.reduce((acc, ext) => {
  const dot = `.${ext}`
  for (const mime of ACCEPT_BY_EXT[ext]) {
    const prev = acc[mime] || []
    if (!prev.includes(dot)) acc[mime] = [...prev, dot]
  }
  return acc
}, {})

const statusConfig = {
  pending:   { label: 'Ready', icon: FileText, color: 'text-gray-400' },
  uploading: { label: 'Uploading', icon: Loader2, color: 'text-blue-400', spin: true },
  processing:{ label: 'Processing', icon: Loader2, color: 'text-amber-400', spin: true },
  indexed:   { label: 'Indexed', icon: CheckCircle, color: 'text-green-400' },
  error:     { label: 'Failed', icon: AlertCircle, color: 'text-red-400' },
  duplicate: { label: 'Duplicate', icon: AlertCircle, color: 'text-yellow-400' },
}

function fileIcon(ext) {
  if (['xlsx','xls','csv'].includes(ext)) return FileSpreadsheet
  if (['png','jpg','jpeg'].includes(ext)) return Image
  if (['mp4','mov','webm','mkv','avi','wmv','flv','mpg','mpeg','m4v','3gp','3g2','ogv','ts','m2ts','vob','f4v','asf','divx','mxf'].includes(ext)) return Video
  return FileText
}

const crawlStatusColors = {
  queued: 'text-gray-400',
  crawling: 'text-blue-400',
  indexed: 'text-green-400',
  failed: 'text-red-400',
}

export default function UploadPage() {
  const { user, loadUser } = useAuth()
  const [files, setFiles] = useState([])
  const [uploading, setUploading] = useState(false)
  const uploadInFlight = useRef(false)
  const [category, setCategory] = useState('')
  const [author, setAuthor] = useState('')
  const noDept = !user?.dept_id

  // URL crawl state
  const [urlInputs, setUrlInputs] = useState([''])
  const [crawlDepth, setCrawlDepth] = useState(1)
  const [crawlMode, setCrawlMode] = useState('auto')
  const [maxPagesPerSeed, setMaxPagesPerSeed] = useState(80)
  const [maxPagesTotal, setMaxPagesTotal] = useState(250)
  const [crawling, setCrawling] = useState(false)
  const [crawlResults, setCrawlResults] = useState([])
  const [crawlError, setCrawlError] = useState('')

  const onDrop = useCallback((accepted, rejected) => {
    const newFiles = accepted.map(f => ({
      file: f,
      id: `${f.name}-${Date.now()}-${Math.random()}`,
      status: 'pending',
      progress: 0,
      error: null,
    }))
    setFiles(prev => [...prev, ...newFiles])

    rejected.forEach(({ file, errors }) => {
      const msg = errors[0]?.code === 'file-too-large'
        ? `File too large (max ${MAX_SIZE_MB}MB)`
        : errors[0]?.message || 'File rejected'
      setFiles(prev => [...prev, { file, id: `${file.name}-err`, status: 'error', error: msg }])
    })
  }, [])

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: dropzoneAccept,
    maxSize: MAX_SIZE_MB * 1024 * 1024,
    multiple: true,
    maxFiles: MAX_FILES_PER_BATCH,
  })

  const removeFile = (id) => setFiles(prev => prev.filter(f => f.id !== id))

  const handleUpload = async () => {
    const pending = files.filter(f => f.status === 'pending')
    if (!pending.length || uploadInFlight.current) return
    uploadInFlight.current = true
    setUploading(true)
    try {
      const pollDocument = async (itemId, docId, retries = 60) => {
        if (retries <= 0) {
          setFiles(prev => prev.map(f =>
            f.id === itemId ? { ...f, status: 'error', error: 'Processing is taking longer than expected' } : f,
          ))
          return
        }
        await new Promise(r => setTimeout(r, 2000))
        try {
          const { data } = await api.get(`/documents/${docId}/status`)
          if (data.status === 'indexed') {
            setFiles(prev => prev.map(f => f.id === itemId ? { ...f, status: 'indexed' } : f))
          } else if (data.status === 'failed') {
            setFiles(prev => prev.map(f =>
              f.id === itemId ? { ...f, status: 'error', error: data.error_message || 'Ingestion failed' } : f,
            ))
          } else {
            await pollDocument(itemId, docId, retries - 1)
          }
        } catch {
          await pollDocument(itemId, docId, retries - 1)
        }
      }

      for (let offset = 0; offset < pending.length; offset += MAX_FILES_PER_BATCH) {
        const batch = pending.slice(offset, offset + MAX_FILES_PER_BATCH)
        const batchIds = new Set(batch.map(b => b.id))
        setFiles(prev => prev.map(f => batchIds.has(f.id) ? { ...f, status: 'uploading' } : f))

        try {
          const fd = new FormData()
          for (const item of batch) fd.append('files', item.file)
          if (category) fd.append('category', category)
          if (author) fd.append('author', author)

          const { data: docs } = await api.post('/documents/upload', fd)

          setFiles(prev => prev.map(f => {
            if (!batchIds.has(f.id)) return f
            const idx = batch.findIndex(b => b.id === f.id)
            const doc = idx >= 0 ? docs[idx] : null
            return doc?.id ? { ...f, status: 'processing' } : f
          }))

          batch.forEach((item, idx) => {
            const doc = docs[idx]
            if (doc?.id) pollDocument(item.id, doc.id)
          })
        } catch (err) {
          const detail = err.response?.data?.detail || 'Upload failed'
          const isDupe = err.response?.status === 409
          setFiles(prev => prev.map(f =>
            batchIds.has(f.id) ? { ...f, status: isDupe ? 'duplicate' : 'error', error: detail } : f,
          ))
        }
      }
    } finally {
      setUploading(false)
      uploadInFlight.current = false
    }
  }

  const pendingCount = files.filter(f => f.status === 'pending').length
  const ext = (name) => name.split('.').pop()?.toLowerCase() || ''

  const handleCrawl = async () => {
    const urls = urlInputs.filter(u => u.trim())
    if (urls.length === 0) return
    setCrawling(true)
    setCrawlError('')
    setCrawlResults([])
    try {
      const {data} = await api.post('/documents/crawl', {
        urls,
        crawl_mode: crawlMode,
        max_depth: crawlDepth,
        max_pages_per_seed: maxPagesPerSeed,
        max_pages_total: maxPagesTotal,
      })
      setCrawlResults(data.documents || [])
    } catch (err) {
      setCrawlError(err.response?.data?.detail || 'Crawl submission failed.')
    } finally {
      setCrawling(false)
    }
  }

  return (
    <div className="p-6 max-w-4xl mx-auto">
      {noDept && <SelectDepartmentModal onSuccess={() => loadUser()} />}
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-white">Upload Documents</h1>
        <p className="text-gray-400 mt-1">
          Add files to your department's knowledge base. Supported: PDF, DOCX, XLSX, CSV, TXT, JSON, PNG/JPG
        </p>
      </div>

      {/* Metadata */}
      <div className="card mb-5">
        <h2 className="text-sm font-semibold text-gray-300 mb-3 flex items-center gap-2">
          <Tag className="w-4 h-4 text-blue-400" />
          Optional Metadata
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="label">Category</label>
            <input className="input" placeholder="e.g. Policy, Report, Contract" value={category} onChange={e => setCategory(e.target.value)} />
          </div>
          <div>
            <label className="label">Author</label>
            <input className="input" placeholder="Document author" value={author} onChange={e => setAuthor(e.target.value)} />
          </div>
        </div>
      </div>

      {/* Drop zone */}
      <div
        {...getRootProps()}
        className={clsx(
          'border-2 border-dashed rounded-xl p-12 text-center cursor-pointer transition-all duration-200 mb-5',
          isDragActive
            ? 'border-blue-500 bg-blue-500/10 scale-[1.01]'
            : 'border-navy-600 hover:border-blue-500/50 hover:bg-navy-700/30'
        )}
      >
        <input {...getInputProps()} />
        <div className="flex flex-col items-center gap-3">
          <div className={clsx(
            'w-16 h-16 rounded-2xl flex items-center justify-center transition-colors',
            isDragActive ? 'bg-blue-500/30' : 'bg-navy-700'
          )}>
            <Upload className={clsx('w-7 h-7', isDragActive ? 'text-blue-300' : 'text-gray-400')} />
          </div>
          <div>
            <p className="text-white font-semibold">
              {isDragActive ? 'Drop files here...' : 'Drag & drop files, or click to browse'}
            </p>
            <p className="text-gray-500 text-sm mt-1">
              Up to {MAX_FILES_PER_BATCH} files per drop · Max {MAX_SIZE_MB}MB each · PDF, DOCX, XLSX, CSV, TXT, JSON, images, audio, PPTX
            </p>
          </div>
        </div>
      </div>

      {/* File list */}
      {files.length > 0 && (
        <div className="card mb-5">
          <div className="flex items-center justify-between mb-3">
            <h2 className="font-semibold text-white">{files.length} file{files.length > 1 ? 's' : ''}</h2>
            <button
              onClick={() => setFiles([])}
              className="text-xs text-gray-500 hover:text-red-400 transition-colors"
            >
              Clear all
            </button>
          </div>
          <div className="space-y-2 max-h-80 overflow-y-auto">
            {files.map((item) => {
              const cfg = statusConfig[item.status] || statusConfig.pending
              const Icon = fileIcon(ext(item.file?.name || ''))
              const StatusIcon = cfg.icon
              return (
                <div key={item.id} className="flex items-center gap-3 p-3 bg-navy-800 rounded-lg">
                  <div className="w-8 h-8 rounded-lg bg-navy-700 flex items-center justify-center flex-shrink-0">
                    <Icon className="w-4 h-4 text-blue-400" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-white truncate">{item.file?.name}</p>
                    <p className="text-xs text-gray-500">
                      {item.file?.size ? `${(item.file.size / 1024 / 1024).toFixed(2)} MB` : ''}
                      {item.error && <span className="text-red-400 ml-2">{item.error}</span>}
                    </p>
                  </div>
                  <div className={clsx('flex items-center gap-1.5 text-xs font-medium', cfg.color)}>
                    <StatusIcon className={clsx('w-3.5 h-3.5', cfg.spin && 'animate-spin')} />
                    {cfg.label}
                  </div>
                  {item.status === 'pending' && (
                    <button onClick={() => removeFile(item.id)}
                      className="text-gray-600 hover:text-red-400 ml-1 transition-colors">
                      <X className="w-4 h-4" />
                    </button>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}

      {pendingCount > 0 && (
        <button
          onClick={handleUpload}
          disabled={uploading}
          className="btn-primary w-full py-3 text-base flex items-center justify-center gap-2"
        >
          {uploading
            ? <><Loader2 className="w-5 h-5 animate-spin" /> Uploading...</>
            : <><Upload className="w-5 h-5" /> Upload {pendingCount} file{pendingCount > 1 ? 's' : ''}</>
          }
        </button>
      )}

      {/* URL Crawl Section */}
      <div className="mt-8 rounded-xl border border-gray-700 bg-gray-900 p-5">
        <div className="mb-4 flex items-center gap-2">
          <Globe className="h-5 w-5 text-blue-400" />
          <h3 className="font-semibold text-white">Crawl Web URLs</h3>
          <span className="ml-auto text-xs text-gray-500">Up to 25 seed URLs (sitemap = one XML URL)</span>
        </div>
        <div className="space-y-2">
          {urlInputs.map((url, i) => (
            <div key={i} className="flex gap-2">
              <div className="flex flex-1 items-center gap-2 rounded-lg border border-gray-700 bg-gray-800 px-3 py-2">
                <Link className="h-4 w-4 shrink-0 text-gray-500" />
                <input
                  className="flex-1 bg-transparent text-sm text-white placeholder-gray-500 outline-none"
                  placeholder="https://example.com/policy-page"
                  value={url}
                  onChange={e => setUrlInputs(prev => prev.map((u, j) => j === i ? e.target.value : u))}
                />
              </div>
              {urlInputs.length > 1 && (
                <button
                  onClick={() => setUrlInputs(prev => prev.filter((_, j) => j !== i))}
                  className="text-gray-600 hover:text-red-400"
                >
                  <X className="h-4 w-4" />
                </button>
              )}
            </div>
          ))}
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-4">
          {urlInputs.length < 25 && (
            <button
              onClick={() => setUrlInputs(prev => [...prev, ''])}
              className="flex items-center gap-1 text-xs text-blue-400 hover:text-blue-300"
            >
              <Plus className="h-3.5 w-3.5" /> Add URL
            </button>
          )}
        </div>

        <div className="mt-3 flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end">
          <div className="flex flex-col gap-1">
            <span className="text-xs text-gray-500">Crawl mode</span>
            <select
              className="rounded-lg border border-gray-700 bg-gray-800 px-2 py-1.5 text-xs text-white outline-none focus:border-blue-500"
              value={crawlMode}
              onChange={e => setCrawlMode(e.target.value)}
            >
              <option value="auto">Auto (sitemap XML if detected)</option>
              <option value="site_pages">Site pages (seed URLs + same-site links)</option>
              <option value="sitemap">Sitemap only (one sitemap.xml URL)</option>
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <span className="text-xs text-gray-500">Max pages (bulk cap)</span>
            <input
              type="number"
              min={10}
              max={2000}
              className="w-28 rounded-lg border border-gray-700 bg-gray-800 px-2 py-1.5 text-xs text-white"
              value={maxPagesTotal}
              onChange={e => setMaxPagesTotal(Number(e.target.value) || 250)}
            />
          </div>
          <div className="flex flex-col gap-1">
            <span className="text-xs text-gray-500">Max pages per seed link crawl</span>
            <input
              type="number"
              min={5}
              max={500}
              className="w-28 rounded-lg border border-gray-700 bg-gray-800 px-2 py-1.5 text-xs text-white"
              value={maxPagesPerSeed}
              onChange={e => setMaxPagesPerSeed(Number(e.target.value) || 80)}
            />
          </div>
          <div className="flex flex-col gap-1">
            <span className="text-xs text-gray-500">Same-site link depth</span>
            <div className="flex flex-wrap gap-1">
              {[0, 1, 2].map(d => (
                <button
                  key={d}
                  type="button"
                  onClick={() => setCrawlDepth(d)}
                  className={`rounded px-2 py-0.5 text-xs ${crawlDepth === d ? 'bg-blue-600 text-white' : 'bg-gray-700 text-gray-400 hover:bg-gray-600'}`}
                >
                  {d === 0 ? 'Seed only' : d === 1 ? '1 hop' : '2 hops'}
                </button>
              ))}
            </div>
          </div>
          <button
            onClick={handleCrawl}
            disabled={crawling || !urlInputs.some(u => u.trim())}
            className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700 disabled:opacity-50 sm:ml-auto"
          >
            {crawling ? <Loader2 className="h-4 w-4 animate-spin" /> : <Globe className="h-4 w-4" />}
            {crawling ? 'Submitting…' : 'Start Crawl'}
          </button>
        </div>

        {crawlError && (
          <p className="mt-2 text-xs text-red-400">{crawlError}</p>
        )}

        {crawlResults.length > 0 && (
          <div className="mt-3 space-y-2">
            <p className="text-xs text-gray-400">{crawlResults.length} URL{crawlResults.length > 1 ? 's' : ''} queued for crawling</p>
            {crawlResults.map((r, i) => (
              <div key={i} className="flex items-center gap-2 rounded-lg bg-gray-800 p-2 text-xs">
                <Globe className="h-3.5 w-3.5 text-blue-400 shrink-0" />
                <span className="flex-1 truncate text-gray-300">{r.url}</span>
                <span className={`shrink-0 ${crawlStatusColors[r.status] || 'text-gray-400'}`}>{r.status}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Instructions */}
      <div className="mt-8 grid grid-cols-1 md:grid-cols-3 gap-4">
        {[
          { step: '1', title: 'Upload', desc: `Drop your files above or click to browse — mixed formats, up to ${MAX_FILES_PER_BATCH} files per upload.` },
          { step: '2', title: 'Process', desc: 'Our AI agents parse, chunk, and embed your documents automatically.' },
          { step: '3', title: 'Ask', desc: 'Once indexed, your documents are searchable via the Chat interface.' },
        ].map(({ step, title, desc }) => (
          <div key={step} className="flex gap-3 p-4 bg-navy-700/50 rounded-lg">
            <div className="w-6 h-6 rounded-full bg-blue-500 text-white text-xs font-bold flex items-center justify-center flex-shrink-0 mt-0.5">
              {step}
            </div>
            <div>
              <p className="font-medium text-white text-sm">{title}</p>
              <p className="text-xs text-gray-400 mt-0.5">{desc}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
