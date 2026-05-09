import { useState, useEffect } from 'react'
import {
  Users, FileText, MessageSquare, TrendingUp, HardDrive,
  Building2, Activity, Loader2, CheckCircle, AlertCircle,
  Download, AlertTriangle, BarChart2, Grid, RefreshCw
} from 'lucide-react'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  BarChart, Bar, Cell
} from 'recharts'
import api from '../lib/api'
import { formatDistanceToNow } from 'date-fns'

function StatCard({ icon: Icon, label, value, sub, color = 'blue', loading }) {
  const colors = {
    blue: 'bg-blue-500/20 text-blue-400',
    green: 'bg-green-500/20 text-green-400',
    purple: 'bg-purple-500/20 text-purple-400',
    amber: 'bg-amber-500/20 text-amber-400',
    red: 'bg-red-500/20 text-red-400',
  }
  return (
    <div className="card-hover">
      <div className="flex items-center justify-between mb-3">
        <span className="text-sm text-gray-400">{label}</span>
        <div className={`w-8 h-8 rounded-lg ${colors[color]} flex items-center justify-center`}>
          <Icon className="w-4 h-4" />
        </div>
      </div>
      {loading
        ? <div className="h-8 w-20 bg-navy-600 rounded animate-pulse" />
        : <p className="text-3xl font-bold text-white">{value}</p>
      }
      {sub && <p className="text-xs text-gray-500 mt-1">{sub}</p>}
    </div>
  )
}

export default function AdminDashboard() {
  const [metrics, setMetrics] = useState(null)
  const [docs, setDocs] = useState([])
  const [health, setHealth] = useState(null)
  const [loading, setLoading] = useState(true)
  // Phase 2
  const [comparison, setComparison] = useState([])
  const [queryVolume, setQueryVolume] = useState([])
  const [unanswered, setUnanswered] = useState([])
  const [heatmap, setHeatmap] = useState([])
  const [activeTab, setActiveTab] = useState('overview')
  const [exporting, setExporting] = useState(false)

  useEffect(() => {
    Promise.all([
      api.get('/analytics/admin'),
      api.get('/admin/documents?limit=10'),
      api.get('/health'),
      api.get('/admin/department-comparison').catch(() => ({ data: [] })),
      api.get('/admin/query-volume?days=30').catch(() => ({ data: [] })),
      api.get('/admin/unanswered-queries?limit=15').catch(() => ({ data: [] })),
      api.get('/admin/active-users-heatmap').catch(() => ({ data: [] })),
    ]).then(([m, d, h, comp, vol, unans, heat]) => {
      setMetrics(m.data)
      setDocs(d.data)
      setHealth(h.data)
      setComparison(Array.isArray(comp.data) ? comp.data : [])
      setQueryVolume(Array.isArray(vol.data) ? vol.data : [])
      setUnanswered(Array.isArray(unans.data) ? unans.data : [])
      setHeatmap(Array.isArray(heat.data) ? heat.data : [])
    }).finally(() => setLoading(false))
  }, [])

  const handleExport = async (format) => {
    setExporting(true)
    try {
      const resp = await api.get(`/admin/export?format=${format}`, { responseType: 'blob' })
      const url = window.URL.createObjectURL(new Blob([resp.data]))
      const a = document.createElement('a')
      a.href = url; a.download = format === 'pdf' ? 'admin_report.pdf' : 'admin_export.csv'
      a.click(); window.URL.revokeObjectURL(url)
    } catch { alert('Export failed') }
    finally { setExporting(false) }
  }

  const maxHeat = heatmap.length > 0
    ? Math.max(...heatmap.flatMap(d => d.hours?.map(h => h.count) || [0]))
    : 1

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Admin Dashboard</h1>
          <p className="text-gray-400 mt-1">Platform-wide overview and management</p>
        </div>
        <div className="flex gap-2">
          <button onClick={() => handleExport('csv')} disabled={exporting} className="flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm text-white hover:bg-blue-700 disabled:opacity-50">
            <Download className="h-4 w-4" /> CSV
          </button>
          <button onClick={() => handleExport('pdf')} disabled={exporting} className="flex items-center gap-2 rounded-lg bg-purple-600 px-3 py-2 text-sm text-white hover:bg-purple-700 disabled:opacity-50">
            <Download className="h-4 w-4" /> PDF
          </button>
        </div>
      </div>

      {/* Tab bar */}
      <div className="mb-6 flex gap-2 border-b border-gray-700 pb-2">
        {[
          { id: 'overview', label: 'Overview' },
          { id: 'comparison', label: 'Dept. Comparison' },
          { id: 'queries', label: 'Query Analytics' },
          { id: 'heatmap', label: 'User Heatmap' },
        ].map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`rounded-lg px-3 py-1.5 text-sm transition-colors ${activeTab === tab.id ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-white hover:bg-gray-800'}`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* ── Overview tab ── */}
      {activeTab !== 'overview' && null}

      {/* Platform metrics */}
      {activeTab === 'overview' && <>
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4 mb-8">
        <StatCard icon={Users} label="Total Users" value={metrics?.total_users ?? '—'} color="blue" loading={loading} />
        <StatCard icon={FileText} label="Total Documents" value={metrics?.total_documents ?? '—'} color="green" loading={loading} />
        <StatCard icon={MessageSquare} label="Queries Today" value={metrics?.total_queries_today ?? '—'} color="purple" loading={loading} />
        <StatCard icon={TrendingUp} label="Avg Confidence" value={metrics ? `${Math.round(metrics.avg_confidence * 100)}%` : '—'} color="amber" loading={loading} />
        <StatCard icon={HardDrive} label="Storage Used" value={metrics ? `${metrics.storage_used_mb.toFixed(1)} MB` : '—'} color="red" loading={loading} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Department table — original overview */}
        <div className="lg:col-span-2 card">
          <h2 className="font-semibold text-white mb-4 flex items-center gap-2">
            <Building2 className="w-4 h-4 text-blue-400" />
            Departments
          </h2>
          {loading ? (
            <div className="space-y-2">
              {[1,2,3].map(i => <div key={i} className="h-12 bg-navy-600 rounded animate-pulse" />)}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-navy-600">
                    <th className="text-left py-2 text-xs text-gray-400 font-medium">Department</th>
                    <th className="text-right py-2 text-xs text-gray-400 font-medium">Users</th>
                    <th className="text-right py-2 text-xs text-gray-400 font-medium">Docs</th>
                    <th className="text-right py-2 text-xs text-gray-400 font-medium">Queries Today</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-navy-700">
                  {metrics?.departments?.map(dept => (
                    <tr key={dept.id} className="hover:bg-navy-700/50 transition-colors">
                      <td className="py-2.5 text-white font-medium">{dept.name}</td>
                      <td className="py-2.5 text-right text-gray-300">{dept.user_count}</td>
                      <td className="py-2.5 text-right text-gray-300">{dept.document_count}</td>
                      <td className="py-2.5 text-right text-gray-300">{dept.query_count_today}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="space-y-5">
          {/* System Health */}
          <div className="card">
            <h2 className="font-semibold text-white mb-3 flex items-center gap-2">
              <Activity className="w-4 h-4 text-blue-400" />
              System Health
              {health && (
                <span className={`badge ml-auto ${health.status === 'ok' ? 'badge-green' : 'badge-yellow'}`}>
                  {health.status}
                </span>
              )}
            </h2>
            {loading ? (
              <div className="space-y-2">
                {[1,2,3,4].map(i => <div key={i} className="h-8 bg-navy-600 rounded animate-pulse" />)}
              </div>
            ) : (
              <div className="space-y-2">
                {health && Object.entries(health.services).map(([name, status]) => (
                  <div key={name} className="flex items-center justify-between p-2 bg-navy-800 rounded-lg">
                    <span className="text-sm text-gray-300 capitalize">{name}</span>
                    {status === 'ok'
                      ? <CheckCircle className="w-4 h-4 text-green-400" />
                      : <AlertCircle className="w-4 h-4 text-red-400" />
                    }
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Recent Ingestion */}
          <div className="card">
            <h2 className="font-semibold text-white mb-3">Recent Ingestion</h2>
            {loading ? (
              <div className="space-y-2">
                {[1,2,3].map(i => <div key={i} className="h-10 bg-navy-600 rounded animate-pulse" />)}
              </div>
            ) : docs.length === 0 ? (
              <p className="text-sm text-gray-500 text-center py-4">No documents</p>
            ) : (
              <div className="space-y-2">
                {docs.slice(0, 6).map(doc => (
                  <div key={doc.id} className="flex items-center gap-2 p-2 rounded hover:bg-navy-800 transition-colors">
                    <FileText className="w-3.5 h-3.5 text-blue-400 flex-shrink-0" />
                    <span className="text-xs text-gray-300 truncate flex-1">{doc.original_name}</span>
                    <span className={`badge text-xs ${doc.status === 'indexed' ? 'badge-green' : doc.status === 'failed' ? 'badge-red' : 'badge-yellow'}`}>
                      {doc.status}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
      </>}

      {/* ── Department Comparison Tab ── */}
      {activeTab === 'comparison' && (
        <div className="rounded-xl border border-gray-700 bg-gray-900 p-5">
          <h2 className="mb-4 flex items-center gap-2 font-semibold text-white">
            <Building2 className="h-5 w-5 text-blue-400" />
            Department Comparison (30-day window)
          </h2>
          {loading ? (
            <div className="space-y-2">{[1,2,3].map(i => <div key={i} className="h-10 animate-pulse rounded bg-gray-800" />)}</div>
          ) : comparison.length === 0 ? (
            <p className="py-8 text-center text-sm text-gray-500">No data available.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-700">
                    <th className="py-2 text-left text-xs text-gray-400">Department</th>
                    <th className="py-2 text-right text-xs text-gray-400">Docs</th>
                    <th className="py-2 text-right text-xs text-gray-400">Queries (30d)</th>
                    <th className="py-2 text-right text-xs text-gray-400">Avg Confidence</th>
                    <th className="py-2 text-left text-xs text-gray-400 pl-4">Top Question</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-800">
                  {comparison.map(d => (
                    <tr key={d.dept_id} className="hover:bg-gray-800/50">
                      <td className="py-3 font-medium text-white">{d.dept_name}</td>
                      <td className="py-3 text-right text-gray-300">{d.doc_count}</td>
                      <td className="py-3 text-right text-gray-300">{d.query_count_30d}</td>
                      <td className="py-3 text-right">
                        <span className={`rounded-full px-2 py-0.5 text-xs ${d.avg_confidence >= 0.7 ? 'bg-green-500/20 text-green-400' : d.avg_confidence >= 0.4 ? 'bg-yellow-500/20 text-yellow-400' : 'bg-red-500/20 text-red-400'}`}>
                          {(d.avg_confidence * 100).toFixed(0)}%
                        </span>
                      </td>
                      <td className="py-3 pl-4 text-xs text-gray-400 max-w-xs truncate">{d.top_question || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* ── Query Analytics Tab ── */}
      {activeTab === 'queries' && (
        <div className="space-y-6">
          {/* Query volume chart */}
          <div className="rounded-xl border border-gray-700 bg-gray-900 p-5">
            <h2 className="mb-4 flex items-center gap-2 font-semibold text-white">
              <TrendingUp className="h-5 w-5 text-blue-400" /> Platform Query Volume (30d)
            </h2>
            {queryVolume.length > 0 ? (
              <ResponsiveContainer width="100%" height={200}>
                <LineChart data={queryVolume}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                  <XAxis dataKey="date" tick={{ fill: '#9ca3af', fontSize: 11 }} tickFormatter={v => v.slice(5)} />
                  <YAxis tick={{ fill: '#9ca3af', fontSize: 11 }} />
                  <Tooltip contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151', borderRadius: 8 }} />
                  <Line type="monotone" dataKey="count" stroke="#3b82f6" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            ) : <p className="py-8 text-center text-sm text-gray-500">No query data.</p>}
          </div>

          {/* Unanswered queries */}
          <div className="rounded-xl border border-gray-700 bg-gray-900 p-5">
            <h2 className="mb-4 flex items-center gap-2 font-semibold text-white">
              <AlertTriangle className="h-5 w-5 text-yellow-400" /> Top Unanswered Queries
              <span className="ml-auto text-xs text-gray-500">confidence &lt; 40%</span>
            </h2>
            {unanswered.length === 0 ? (
              <p className="py-8 text-center text-sm text-gray-500">No low-confidence queries detected.</p>
            ) : (
              <div className="space-y-2">
                {unanswered.map((q, i) => (
                  <div key={i} className="flex items-start justify-between rounded-lg bg-gray-800 p-3">
                    <div className="min-w-0 flex-1 mr-3">
                      <p className="text-sm text-gray-200 line-clamp-2">{q.query}</p>
                      <p className="mt-0.5 text-xs text-gray-500">{q.dept_name} · {q.date ? new Date(q.date).toLocaleDateString() : ''}</p>
                    </div>
                    <span className="shrink-0 rounded-full bg-red-500/20 px-2 py-0.5 text-xs text-red-400">
                      {(q.confidence * 100).toFixed(0)}%
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── Heatmap Tab ── */}
      {activeTab === 'heatmap' && (
        <div className="rounded-xl border border-gray-700 bg-gray-900 p-5">
          <h2 className="mb-4 flex items-center gap-2 font-semibold text-white">
            <Grid className="h-5 w-5 text-purple-400" /> Active Users Heatmap (Hour × Day of Week)
          </h2>
          {heatmap.length === 0 ? (
            <p className="py-8 text-center text-sm text-gray-500">No activity data available.</p>
          ) : (
            <div className="overflow-x-auto">
              <div className="min-w-max">
                {/* Hour labels */}
                <div className="flex gap-0.5 mb-1 ml-20">
                  {Array.from({ length: 24 }, (_, h) => (
                    <div key={h} className="w-6 text-center text-xs text-gray-600">{h % 4 === 0 ? h : ''}</div>
                  ))}
                </div>
                {heatmap.map(row => (
                  <div key={row.day} className="flex items-center gap-0.5 mb-0.5">
                    <div className="w-20 shrink-0 text-right pr-3 text-xs text-gray-400">{row.day.slice(0, 3)}</div>
                    {(row.hours || []).map(cell => {
                      const intensity = maxHeat > 0 ? cell.count / maxHeat : 0
                      const bg = intensity === 0 ? '#111827' : `rgba(59,130,246,${0.15 + intensity * 0.85})`
                      return (
                        <div
                          key={cell.hour}
                          className="h-6 w-6 rounded-sm"
                          style={{ backgroundColor: bg }}
                          title={`${row.day} ${cell.hour}:00 — ${cell.count} queries`}
                        />
                      )
                    })}
                  </div>
                ))}
                <div className="mt-3 flex items-center gap-2 ml-20">
                  <span className="text-xs text-gray-500">Low</span>
                  {[0.1, 0.3, 0.5, 0.7, 0.9].map(v => (
                    <div key={v} className="h-4 w-6 rounded-sm" style={{ backgroundColor: `rgba(59,130,246,${v})` }} />
                  ))}
                  <span className="text-xs text-gray-500">High</span>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
