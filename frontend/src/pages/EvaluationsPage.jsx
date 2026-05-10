import { useState, useEffect } from 'react'
import {
  Gauge,
  RefreshCw,
  ExternalLink,
  AlertTriangle,
  CheckCircle,
  Copy,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react'
import api from '../lib/api'
import { format, formatDistanceToNow } from 'date-fns'
import clsx from 'clsx'

function traceHref(meta, traceId) {
  if (!meta?.langfuse_ui_origin || !traceId) return null
  const base = meta.langfuse_ui_origin.replace(/\/$/, '')
  const pid = meta.langfuse_project_id
  if (pid) return `${base}/project/${pid}/traces/${encodeURIComponent(traceId)}`
  return `${base}/trace/${encodeURIComponent(traceId)}`
}

export default function EvaluationsPage() {
  const [rows, setRows] = useState([])
  const [meta, setMeta] = useState(null)
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState('all')
  const [page, setPage] = useState(0)
  const limit = 30

  const load = async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams({
        skip: String(page * limit),
        limit: String(limit),
      })
      if (filter === 'flagged') params.set('flagged_only', 'true')
      if (filter === 'ok') params.set('flagged_only', 'false')
      const [metaRes, listRes] = await Promise.all([
        api.get('/admin/evaluations/meta'),
        api.get(`/admin/evaluations?${params}`),
      ])
      setMeta(metaRes.data)
      setRows(listRes.data)
    } catch {
      setRows([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [filter, page])

  const copyTrace = (id) => {
    if (!id) return
    navigator.clipboard.writeText(id)
  }

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <div className="flex items-start justify-between gap-4 mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <Gauge className="w-6 h-6 text-blue-400" />
            Answer evaluations
          </h1>
          <p className="text-gray-400 mt-1 max-w-3xl">
            Scores come from{' '}
            <span className="text-gray-300">RAGAS</span> (faithfulness + answer relevancy) using your configured{' '}
            <span className="text-gray-300">chat</span> and <span className="text-gray-300">embedding</span> models on the same OpenAI-compatible API as OrgMind.
            Rows marked <span className="text-amber-400">flagged</span> fall below admin thresholds in <code className="text-xs bg-navy-800 px-1 rounded">.env</code>.
          </p>
          <p className="text-gray-500 text-sm mt-2">
            Langfuse shows <strong className="text-gray-400">traces</strong> for each chat turn when keys are set; numeric scores may appear on those traces when evaluation completes.
            This page reads persisted scores from the OrgMind database (not only Langfuse).
          </p>
        </div>
        <button type="button" onClick={() => load()} className="btn-ghost flex items-center gap-2 text-sm shrink-0">
          <RefreshCw className="w-4 h-4" />
          Refresh
        </button>
      </div>

      <div className="flex flex-col sm:flex-row gap-3 mb-5 items-start sm:items-center justify-between">
        <select
          className="input w-auto"
          value={filter}
          onChange={(e) => {
            setFilter(e.target.value)
            setPage(0)
          }}
        >
          <option value="all">All sampled evaluations</option>
          <option value="flagged">Flagged only</option>
          <option value="ok">Not flagged</option>
        </select>
        {meta?.langfuse_ui_origin && (
          <a
            href={meta.langfuse_ui_origin.replace(/\/$/, '')}
            target="_blank"
            rel="noopener noreferrer"
            className="text-sm text-blue-400 hover:text-blue-300 flex items-center gap-1"
          >
            Open Langfuse <ExternalLink className="w-3.5 h-3.5" />
          </a>
        )}
      </div>

      {loading ? (
        <div className="space-y-2">
          {[...Array(8)].map((_, i) => (
            <div key={i} className="h-14 bg-navy-700 rounded-lg animate-pulse" />
          ))}
        </div>
      ) : rows.length === 0 ? (
        <div className="card p-8 text-gray-400 space-y-4">
          <p className="font-medium text-white">No evaluation rows yet</p>
          <p className="text-sm">Typical causes:</p>
          <ul className="text-sm list-disc pl-5 space-y-2">
            <li>
              You must be logged in as <strong className="text-gray-300">super_admin</strong> — evaluations APIs are restricted to that role.
            </li>
            <li>
              Set <code className="text-gray-300 bg-navy-800 px-1 rounded">RAGAS_EVAL_ENABLED=true</code> in{' '}
              <code className="text-gray-300 bg-navy-800 px-1 rounded">.env</code> and restart the backend.
            </li>
            <li>
              While testing, set <code className="text-gray-300 bg-navy-800 px-1 rounded">RAGAS_EVAL_SAMPLE_RATE=1.0</code> so every assistant reply is considered (otherwise sampling skips most turns).
            </li>
            <li>
              Ask questions that return <strong className="text-gray-300">retrieved sources</strong> (indexed docs in Qdrant). If the model answers with <strong className="text-gray-300">zero sources</strong>, evaluation does not write a row.
            </li>
            <li>
              Run migrations: <code className="text-gray-300 bg-navy-800 px-1 rounded">cd backend && alembic upgrade head</code>
            </li>
            <li>
              Ensure <code className="text-gray-300 bg-navy-800 px-1 rounded">OPENAI_API_KEY</code> is valid — RAGAS runs separate LLM and embedding calls; failures may show rows with an error instead of scores.
            </li>
          </ul>
          <p className="text-xs text-gray-500">
            Check browser DevTools → Network → <code className="bg-navy-800 px-1 rounded">GET /api/admin/evaluations</code>: 403 means wrong role; 500 often means DB/table missing.
          </p>
        </div>
      ) : (
        <>
          <div className="card p-0 overflow-hidden">
            <table className="w-full">
              <thead>
                <tr className="border-b border-navy-600">
                  {['When', 'Status', 'Faithfulness', 'Relevancy', 'Answer preview', 'Trace'].map((h) => (
                    <th
                      key={h}
                      className="text-left px-4 py-3 text-xs font-medium text-gray-400 uppercase tracking-wider"
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-navy-700">
                {rows.map((ev) => {
                  const href = traceHref(meta, ev.langfuse_trace_id)
                  return (
                    <tr key={ev.id} className="hover:bg-navy-700/30 transition-colors align-top">
                      <td className="px-4 py-3 whitespace-nowrap">
                        <p className="text-xs text-white font-mono">
                          {format(new Date(ev.created_at), 'MMM d, HH:mm')}
                        </p>
                        <p className="text-xs text-gray-600">
                          {formatDistanceToNow(new Date(ev.created_at), { addSuffix: true })}
                        </p>
                      </td>
                      <td className="px-4 py-3">
                        {ev.flagged ? (
                          <span className="inline-flex items-center gap-1 badge-yellow text-xs">
                            <AlertTriangle className="w-3 h-3" /> Flagged
                          </span>
                        ) : ev.error_message ? (
                          <span className="inline-flex items-center gap-1 text-xs text-gray-400">Error / skip</span>
                        ) : (
                          <span className="inline-flex items-center gap-1 badge-green text-xs">
                            <CheckCircle className="w-3 h-3" /> OK
                          </span>
                        )}
                        {ev.error_message && (
                          <p className="text-xs text-red-400/90 mt-1 max-w-[14rem] break-words">
                            {ev.error_message}
                          </p>
                        )}
                      </td>
                      <td className="px-4 py-3 text-sm font-mono text-gray-300">
                        {ev.faithfulness != null ? ev.faithfulness.toFixed(3) : '—'}
                      </td>
                      <td className="px-4 py-3 text-sm font-mono text-gray-300">
                        {ev.answer_relevancy != null ? ev.answer_relevancy.toFixed(3) : '—'}
                      </td>
                      <td className="px-4 py-3 text-xs text-gray-400 max-w-md">
                        <p className="line-clamp-4">{ev.answer_preview || '—'}</p>
                        <p className="text-gray-600 mt-1 font-mono text-[10px]">
                          msg {String(ev.message_id).slice(0, 8)}…
                        </p>
                      </td>
                      <td className="px-4 py-3">
                        {href ? (
                          <a
                            href={href}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-xs text-blue-400 hover:text-blue-300 inline-flex items-center gap-1"
                          >
                            Trace <ExternalLink className="w-3 h-3" />
                          </a>
                        ) : ev.langfuse_trace_id ? (
                          <button
                            type="button"
                            onClick={() => copyTrace(ev.langfuse_trace_id)}
                            className="text-xs text-gray-500 hover:text-gray-300 inline-flex items-center gap-1"
                            title="Copy trace id"
                          >
                            <Copy className="w-3 h-3" /> Copy id
                          </button>
                        ) : (
                          <span className="text-xs text-gray-600">—</span>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          <div className="flex items-center justify-between mt-4">
            <button
              type="button"
              disabled={page === 0}
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              className={clsx(
                'btn-ghost flex items-center gap-1 text-sm',
                page === 0 && 'opacity-40 pointer-events-none'
              )}
            >
              <ChevronLeft className="w-4 h-4" /> Previous
            </button>
            <span className="text-xs text-gray-500">Page {page + 1}</span>
            <button
              type="button"
              disabled={rows.length < limit}
              onClick={() => setPage((p) => p + 1)}
              className={clsx(
                'btn-ghost flex items-center gap-1 text-sm',
                rows.length < limit && 'opacity-40 pointer-events-none'
              )}
            >
              Next <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        </>
      )}
    </div>
  )
}
