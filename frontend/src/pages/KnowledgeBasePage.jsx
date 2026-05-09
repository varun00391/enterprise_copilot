import { useState, useEffect, useCallback } from 'react'
import {
  BookOpen, Search, FileText, FileSpreadsheet, Image,
  File, Loader2, Trash2,
} from 'lucide-react'
import api from '../lib/api'
import { useAuth } from '../context/AuthContext'
import { formatDistanceToNow } from 'date-fns'

const statusBadge = {
  indexed:   'badge-green',
  uploading: 'badge-yellow',
  parsing:   'badge-yellow',
  chunking:  'badge-yellow',
  embedding: 'badge-blue',
  failed:    'badge-red',
  uploaded:  'badge-yellow',
}

/** DB stage → clearer copy (`uploaded` is not “stored only”—it waits for background indexing). */
function statusDisplay(status) {
  const labels = {
    uploaded: 'Queued — indexing pending',
    parsing: 'Indexing — extracting text',
    chunking: 'Indexing — splitting into chunks',
    embedding: 'Indexing — embeddings',
    indexed: 'Indexed',
    failed: 'Failed',
  }
  return labels[status] || status
}

function FileIcon({ type }) {
  if (['xlsx','xls','csv'].includes(type)) return <FileSpreadsheet className="w-5 h-5 text-green-400" />
  if (['png','jpg','jpeg'].includes(type)) return <Image className="w-5 h-5 text-purple-400" />
  if (type === 'pdf') return <FileText className="w-5 h-5 text-red-400" />
  if (type === 'docx') return <FileText className="w-5 h-5 text-blue-400" />
  return <File className="w-5 h-5 text-gray-400" />
}

export default function KnowledgeBasePage() {
  const { isAdmin } = useAuth()
  const [docs, setDocs] = useState([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [deleting, setDeleting] = useState(null)

  const load = useCallback(async (opts = {}) => {
    const { silent } = opts
    if (!silent) setLoading(true)
    try {
      const params = new URLSearchParams({ limit: '100' })
      if (statusFilter) params.set('status', statusFilter)
      const { data } = await api.get(`/documents?${params}`)
      setDocs(data)
    } finally {
      if (!silent) setLoading(false)
    }
  }, [statusFilter])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    const pending = docs.some(d =>
      ['uploaded', 'parsing', 'chunking', 'embedding'].includes(d.status),
    )
    if (!pending) return undefined
    const id = setInterval(() => load({ silent: true }), 8000)
    return () => clearInterval(id)
  }, [docs, load])

  const handleDelete = async (id) => {
    if (!confirm('Are you sure you want to delete this document? This will also remove it from the knowledge base.')) return
    setDeleting(id)
    try {
      await api.delete(`/documents/${id}`)
      setDocs(prev => prev.filter(d => d.id !== id))
    } catch (err) {
      alert(err.response?.data?.detail || 'Failed to delete')
    } finally {
      setDeleting(null)
    }
  }

  const filtered = docs.filter(d =>
    d.original_name.toLowerCase().includes(search.toLowerCase()) ||
    (d.category || '').toLowerCase().includes(search.toLowerCase())
  )

  const indexed = docs.filter(d => d.status === 'indexed').length
  const processing = docs.filter(d => !['indexed', 'failed'].includes(d.status)).length
  const failed = docs.filter(d => d.status === 'failed').length

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-white flex items-center gap-2">
          <BookOpen className="w-6 h-6 text-blue-400" />
          Knowledge Base
        </h1>
        <p className="text-gray-400 mt-1">
          Rows marked &quot;Queued&quot; are still being indexed (parsing → embeddings); the list refreshes automatically while indexing runs.
        </p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-3 gap-4 mb-6">
        <div className="card text-center">
          <p className="text-3xl font-bold text-green-400">{indexed}</p>
          <p className="text-sm text-gray-400 mt-1">Indexed</p>
        </div>
        <div className="card text-center">
          <p className="text-3xl font-bold text-amber-400">{processing}</p>
          <p className="text-sm text-gray-400 mt-1">Processing</p>
        </div>
        <div className="card text-center">
          <p className="text-3xl font-bold text-red-400">{failed}</p>
          <p className="text-sm text-gray-400 mt-1">Failed</p>
        </div>
      </div>

      {/* Filters */}
      <div className="flex flex-col sm:flex-row gap-3 mb-5">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
          <input
            className="input pl-10"
            placeholder="Search documents..."
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
        </div>
        <select
          className="input w-auto"
          value={statusFilter}
          onChange={e => setStatusFilter(e.target.value)}
        >
          <option value="">All statuses</option>
          <option value="indexed">Indexed</option>
          <option value="failed">Failed</option>
          <option value="uploaded">Queued (uploaded)</option>
          <option value="parsing">Indexing — parsing</option>
          <option value="chunking">Indexing — chunking</option>
          <option value="embedding">Indexing — embedding</option>
        </select>
      </div>

      {/* Document list */}
      {loading ? (
        <div className="space-y-3">
          {[1,2,3,4,5].map(i => <div key={i} className="h-16 bg-navy-700 rounded-lg animate-pulse" />)}
        </div>
      ) : filtered.length === 0 ? (
        <div className="text-center py-20">
          <BookOpen className="w-12 h-12 text-gray-600 mx-auto mb-3" />
          <p className="text-gray-400 font-medium">
            {search ? 'No documents match your search' : 'No documents yet'}
          </p>
          <p className="text-gray-600 text-sm mt-1">
            {!search && 'Upload files to start building your knowledge base'}
          </p>
        </div>
      ) : (
        <div className="card p-0 overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="border-b border-navy-600">
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-400 uppercase tracking-wider">Document</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-400 uppercase tracking-wider">Type</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-400 uppercase tracking-wider">Status</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-400 uppercase tracking-wider">Chunks</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-400 uppercase tracking-wider">Size</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-400 uppercase tracking-wider">Uploaded</th>
                {isAdmin && <th className="px-4 py-3" />}
              </tr>
            </thead>
            <tbody className="divide-y divide-navy-700">
              {filtered.map(doc => (
                <tr key={doc.id} className="hover:bg-navy-700/50 transition-colors">
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-3">
                      <FileIcon type={doc.file_type} />
                      <div>
                        <p className="text-sm font-medium text-white truncate max-w-xs">{doc.original_name}</p>
                        {doc.category && <p className="text-xs text-gray-500">{doc.category}</p>}
                      </div>
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <span className="text-xs text-gray-400 uppercase font-mono">{doc.file_type}</span>
                  </td>
                  <td className="px-4 py-3">
                    <div className="max-w-[14rem]">
                      <span
                        title={doc.status}
                        className={`badge ${statusBadge[doc.status] || 'badge-blue'} inline-block`}
                      >
                        <span className="break-words">{statusDisplay(doc.status)}</span>
                      </span>
                      {doc.status === 'failed' && doc.error_message && (
                        <p className="text-[11px] text-red-400/90 mt-1 break-words" title={doc.error_message}>
                          {doc.error_message.length > 120
                            ? `${doc.error_message.slice(0, 120)}…`
                            : doc.error_message}
                        </p>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <span className="text-sm text-gray-300">{doc.chunk_count || '—'}</span>
                  </td>
                  <td className="px-4 py-3">
                    <span className="text-xs text-gray-400">
                      {doc.file_size_bytes ? `${(doc.file_size_bytes / 1024).toFixed(0)} KB` : '—'}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span className="text-xs text-gray-500">
                      {formatDistanceToNow(new Date(doc.created_at), { addSuffix: true })}
                    </span>
                  </td>
                  {isAdmin && (
                    <td className="px-4 py-3">
                      <button
                        onClick={() => handleDelete(doc.id)}
                        disabled={deleting === doc.id}
                        className="text-gray-600 hover:text-red-400 transition-colors"
                      >
                        {deleting === doc.id
                          ? <Loader2 className="w-4 h-4 animate-spin" />
                          : <Trash2 className="w-4 h-4" />
                        }
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
