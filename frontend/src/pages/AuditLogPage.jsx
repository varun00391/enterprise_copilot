import { useState, useEffect } from 'react'
import { ClipboardList, Search, RefreshCw, Filter } from 'lucide-react'
import api from '../lib/api'
import { format, formatDistanceToNow } from 'date-fns'
import clsx from 'clsx'

const actionColors = {
  'user.login': 'badge-blue',
  'user.register': 'badge-green',
  'document.upload': 'badge-blue',
  'document.delete': 'badge-red',
  'chat.query': 'bg-purple-500/20 text-purple-300',
  'admin.user_update': 'badge-yellow',
  'admin.department_create': 'badge-green',
}

export default function AuditLogPage() {
  const [logs, setLogs] = useState([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [actionFilter, setActionFilter] = useState('')
  const [page, setPage] = useState(0)
  const limit = 50

  const load = async (reset = false) => {
    setLoading(true)
    const p = reset ? 0 : page
    try {
      const params = new URLSearchParams({ skip: String(p * limit), limit: String(limit) })
      if (actionFilter) params.set('action', actionFilter)
      if (search) params.set('actor_email', search)
      const { data } = await api.get(`/admin/audit-log?${params}`)
      if (reset) { setLogs(data); setPage(0) } else setLogs(data)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load(true) }, [actionFilter])

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <ClipboardList className="w-6 h-6 text-blue-400" />
            Audit Log
          </h1>
          <p className="text-gray-400 mt-1">Immutable record of all platform actions</p>
        </div>
        <button onClick={() => load(true)} className="btn-ghost flex items-center gap-2 text-sm">
          <RefreshCw className="w-4 h-4" />
          Refresh
        </button>
      </div>

      <div className="flex flex-col sm:flex-row gap-3 mb-5">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
          <input
            className="input pl-10"
            placeholder="Filter by email..."
            value={search}
            onKeyDown={e => e.key === 'Enter' && load(true)}
            onChange={e => setSearch(e.target.value)}
          />
        </div>
        <select className="input w-auto" value={actionFilter} onChange={e => setActionFilter(e.target.value)}>
          <option value="">All actions</option>
          <option value="user.login">Login</option>
          <option value="user.register">Register</option>
          <option value="document.upload">Upload</option>
          <option value="document.delete">Delete</option>
          <option value="chat.query">Chat Query</option>
          <option value="admin">Admin actions</option>
        </select>
      </div>

      {loading ? (
        <div className="space-y-2">
          {[...Array(8)].map((_, i) => <div key={i} className="h-12 bg-navy-700 rounded-lg animate-pulse" />)}
        </div>
      ) : (
        <div className="card p-0 overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="border-b border-navy-600">
                {['Timestamp', 'Actor', 'Action', 'Target', 'IP'].map(h => (
                  <th key={h} className="text-left px-4 py-3 text-xs font-medium text-gray-400 uppercase tracking-wider">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-navy-700">
              {logs.map(log => (
                <tr key={log.id} className="hover:bg-navy-700/30 transition-colors">
                  <td className="px-4 py-3">
                    <p className="text-xs text-white font-mono">
                      {format(new Date(log.created_at), 'MMM d, HH:mm:ss')}
                    </p>
                    <p className="text-xs text-gray-600">
                      {formatDistanceToNow(new Date(log.created_at), { addSuffix: true })}
                    </p>
                  </td>
                  <td className="px-4 py-3">
                    <p className="text-sm text-gray-300">{log.actor_email || 'System'}</p>
                  </td>
                  <td className="px-4 py-3">
                    <span className={`badge text-xs ${actionColors[log.action] || 'badge-blue'}`}>
                      {log.action}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-400">
                    {log.target_type && <span className="text-gray-500">{log.target_type}: </span>}
                    {log.target_id?.slice(0, 12)}{log.target_id?.length > 12 && '...'}
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-600 font-mono">
                    {log.ip_address || '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {logs.length === 0 && (
            <p className="text-center text-gray-500 py-10 text-sm">No audit logs found</p>
          )}
        </div>
      )}
    </div>
  )
}
