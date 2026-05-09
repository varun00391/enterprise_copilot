import { useState, useEffect, useCallback } from 'react'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  BarChart, Bar, Cell
} from 'recharts'
import {
  Activity, AlertTriangle, Award, BookOpen, Calendar, Download,
  RefreshCw, Shield, TrendingUp, Users, FileText, Clock
} from 'lucide-react'
import api from '../lib/api'

const MetricCard = ({ icon: Icon, label, value, sub, color = 'blue' }) => {
  const colors = {
    blue: 'from-blue-500/20 to-blue-600/10 border-blue-500/30',
    green: 'from-green-500/20 to-green-600/10 border-green-500/30',
    yellow: 'from-yellow-500/20 to-yellow-600/10 border-yellow-500/30',
    red: 'from-red-500/20 to-red-600/10 border-red-500/30',
    purple: 'from-purple-500/20 to-purple-600/10 border-purple-500/30',
  }
  return (
    <div className={`rounded-xl border bg-gradient-to-br p-5 ${colors[color]}`}>
      <div className="flex items-start justify-between">
        <div>
          <p className="text-sm text-gray-400">{label}</p>
          <p className="mt-1 text-2xl font-bold text-white">{value}</p>
          {sub && <p className="mt-1 text-xs text-gray-400">{sub}</p>}
        </div>
        <Icon className="h-5 w-5 opacity-60 text-white" />
      </div>
    </div>
  )
}

const HealthGauge = ({ score }) => {
  const angle = ((score / 100) * 180) - 90
  const color = score >= 70 ? '#22c55e' : score >= 40 ? '#f59e0b' : '#ef4444'
  const label = score >= 70 ? 'Healthy' : score >= 40 ? 'Moderate' : 'Needs Attention'
  return (
    <div className="flex flex-col items-center">
      <div className="relative flex h-32 w-64 items-center justify-center overflow-hidden">
        <svg viewBox="0 0 200 110" className="w-full">
          <path d="M 20 100 A 80 80 0 0 1 180 100" stroke="#374151" strokeWidth="16" fill="none" />
          <path
            d="M 20 100 A 80 80 0 0 1 180 100"
            stroke={color}
            strokeWidth="16"
            fill="none"
            strokeDasharray={`${(score / 100) * 251.2} 251.2`}
            style={{ transition: 'stroke-dasharray 0.8s ease' }}
          />
        </svg>
        <div className="absolute bottom-0 text-center">
          <p className="text-3xl font-bold text-white">{Math.round(score)}</p>
          <p className="text-xs" style={{ color }}>{label}</p>
        </div>
      </div>
    </div>
  )
}

export default function AnalyticsPage() {
  const [health, setHealth] = useState(null)
  const [gaps, setGaps] = useState([])
  const [freshness, setFreshness] = useState([])
  const [contributors, setContributors] = useState([])
  const [trend, setTrend] = useState([])
  const [loading, setLoading] = useState(true)
  const [exporting, setExporting] = useState(false)
  const [error, setError] = useState('')
  const [trendDays, setTrendDays] = useState(30)

  const loadAll = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [h, g, f, c, t] = await Promise.all([
        api.get('/analytics/knowledge-health'),
        api.get('/analytics/coverage-gaps?limit=10'),
        api.get('/analytics/document-freshness'),
        api.get('/analytics/contributors?limit=5'),
        api.get(`/analytics/query-trend?days=${trendDays}`),
      ])
      setHealth(h.data)
      setGaps(Array.isArray(g.data) ? g.data : [])
      setFreshness(Array.isArray(f.data) ? f.data : [])
      setContributors(Array.isArray(c.data) ? c.data : [])
      setTrend(Array.isArray(t.data) ? t.data : [])
    } catch (err) {
      setError('Failed to load analytics data.')
    } finally {
      setLoading(false)
    }
  }, [trendDays])

  useEffect(() => { loadAll() }, [loadAll])

  const handleExport = async (format) => {
    setExporting(true)
    try {
      const resp = await api.get(`/analytics/export?format=${format}`, { responseType: 'blob' })
      const url = window.URL.createObjectURL(new Blob([resp.data]))
      const a = document.createElement('a')
      a.href = url
      a.download = format === 'pdf' ? 'analytics_report.pdf' : 'analytics_export.csv'
      a.click()
      window.URL.revokeObjectURL(url)
    } catch {
      setError('Export failed.')
    } finally {
      setExporting(false)
    }
  }

  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <RefreshCw className="h-8 w-8 animate-spin text-blue-400" />
      </div>
    )
  }

  const maxCount = contributors.length > 0 ? Math.max(...contributors.map(c => c.doc_count)) : 1

  return (
    <div className="min-h-screen bg-gray-950 p-6 text-white">
      {/* Header */}
      <div className="mb-8 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Analytics</h1>
          <p className="text-sm text-gray-400 mt-1">Department knowledge health &amp; insights</p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={loadAll}
            className="flex items-center gap-2 rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-sm hover:bg-gray-700"
          >
            <RefreshCw className="h-4 w-4" /> Refresh
          </button>
          <button
            onClick={() => handleExport('csv')}
            disabled={exporting}
            className="flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm hover:bg-blue-700 disabled:opacity-50"
          >
            <Download className="h-4 w-4" /> CSV
          </button>
          <button
            onClick={() => handleExport('pdf')}
            disabled={exporting}
            className="flex items-center gap-2 rounded-lg bg-purple-600 px-3 py-2 text-sm hover:bg-purple-700 disabled:opacity-50"
          >
            <Download className="h-4 w-4" /> PDF
          </button>
        </div>
      </div>

      {error && (
        <div className="mb-6 rounded-lg border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-400">
          {error}
        </div>
      )}

      {/* Row 1 — Health + metric cards */}
      <div className="mb-6 grid grid-cols-1 gap-4 lg:grid-cols-4">
        {/* Health Score Gauge */}
        <div className="col-span-1 rounded-xl border border-gray-700 bg-gray-900 p-5">
          <div className="mb-3 flex items-center gap-2">
            <Shield className="h-5 w-5 text-blue-400" />
            <h2 className="font-semibold">Knowledge Health Score</h2>
          </div>
          <HealthGauge score={health?.health_score ?? 0} />
          <div className="mt-4 space-y-2 text-sm">
            <div className="flex justify-between text-gray-400">
              <span>Avg Confidence</span>
              <span className="text-white">{((health?.avg_confidence ?? 0) * 100).toFixed(1)}%</span>
            </div>
            <div className="flex justify-between text-gray-400">
              <span>Coverage Gap</span>
              <span className="text-white">{((health?.coverage_gap_ratio ?? 0) * 100).toFixed(1)}%</span>
            </div>
            <div className="flex justify-between text-gray-400">
              <span>Stale Docs</span>
              <span className="text-white">{((health?.stale_doc_ratio ?? 0) * 100).toFixed(1)}%</span>
            </div>
          </div>
        </div>

        {/* 3 metric cards */}
        <div className="col-span-1 lg:col-span-3 grid grid-cols-1 sm:grid-cols-3 gap-4 content-start">
          <MetricCard icon={Activity} label="Queries (30d)" value={health?.total_queries_30d ?? 0} color="blue" />
          <MetricCard icon={FileText} label="Total Documents" value={health?.total_docs ?? 0} color="green" />
          <MetricCard icon={Clock} label="Stale Documents" value={health?.stale_docs ?? 0} sub={`older than 90 days`} color={health?.stale_docs > 0 ? 'yellow' : 'green'} />
        </div>
      </div>

      {/* Row 2 — Query Trend Chart */}
      <div className="mb-6 rounded-xl border border-gray-700 bg-gray-900 p-5">
        <div className="mb-4 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <TrendingUp className="h-5 w-5 text-blue-400" />
            <h2 className="font-semibold">Query Volume Trend</h2>
          </div>
          <div className="flex gap-1">
            {[7, 14, 30, 60].map(d => (
              <button
                key={d}
                onClick={() => setTrendDays(d)}
                className={`rounded px-2 py-1 text-xs ${trendDays === d ? 'bg-blue-600 text-white' : 'bg-gray-800 text-gray-400 hover:bg-gray-700'}`}
              >
                {d}d
              </button>
            ))}
          </div>
        </div>
        {trend.length > 0 ? (
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={trend} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis dataKey="date" tick={{ fill: '#9ca3af', fontSize: 11 }} tickFormatter={v => v.slice(5)} />
              <YAxis tick={{ fill: '#9ca3af', fontSize: 11 }} />
              <Tooltip
                contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151', borderRadius: 8 }}
                labelStyle={{ color: '#9ca3af' }}
                itemStyle={{ color: '#60a5fa' }}
              />
              <Line type="monotone" dataKey="count" stroke="#3b82f6" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <p className="py-8 text-center text-sm text-gray-500">No query data for this period.</p>
        )}
      </div>

      {/* Row 3 — Coverage Gaps + Document Freshness */}
      <div className="mb-6 grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* Coverage Gaps */}
        <div className="rounded-xl border border-gray-700 bg-gray-900 p-5">
          <div className="mb-3 flex items-center gap-2">
            <AlertTriangle className="h-5 w-5 text-yellow-400" />
            <h2 className="font-semibold">Coverage Gaps</h2>
            <span className="ml-auto rounded-full bg-yellow-500/20 px-2 py-0.5 text-xs text-yellow-400">{gaps.length} gaps</span>
          </div>
          {gaps.length === 0 ? (
            <p className="py-8 text-center text-sm text-gray-500">No coverage gaps detected.</p>
          ) : (
            <div className="space-y-2 max-h-64 overflow-y-auto">
              {gaps.map((g, i) => (
                <div key={i} className="flex items-start justify-between rounded-lg bg-gray-800 p-3">
                  <p className="text-sm text-gray-300 flex-1 mr-2 line-clamp-2">{g.query}</p>
                  <span className="shrink-0 rounded-full bg-red-500/20 px-2 py-0.5 text-xs text-red-400">
                    {(g.confidence * 100).toFixed(0)}%
                    {g.occurrences > 1 && (
                      <span className="ml-1 text-gray-400">×{g.occurrences}</span>
                    )}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Document Freshness */}
        <div className="rounded-xl border border-gray-700 bg-gray-900 p-5">
          <div className="mb-3 flex items-center gap-2">
            <Calendar className="h-5 w-5 text-orange-400" />
            <h2 className="font-semibold">Stale Documents</h2>
            <span className="ml-auto rounded-full bg-orange-500/20 px-2 py-0.5 text-xs text-orange-400">{freshness.length} stale</span>
          </div>
          {freshness.length === 0 ? (
            <p className="py-8 text-center text-sm text-gray-500">All documents are fresh!</p>
          ) : (
            <div className="space-y-2 max-h-64 overflow-y-auto">
              {freshness.map((doc, i) => (
                <div key={i} className="flex items-center justify-between rounded-lg bg-gray-800 p-3">
                  <div className="flex items-center gap-2 min-w-0">
                    <BookOpen className="h-4 w-4 shrink-0 text-gray-400" />
                    <p className="text-sm text-gray-300 truncate">{doc.name}</p>
                  </div>
                  <span className={`shrink-0 ml-2 rounded-full px-2 py-0.5 text-xs ${doc.age_days > 180 ? 'bg-red-500/20 text-red-400' : 'bg-yellow-500/20 text-yellow-400'}`}>
                    {doc.age_days}d old
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Row 4 — Top Contributors */}
      <div className="rounded-xl border border-gray-700 bg-gray-900 p-5">
        <div className="mb-4 flex items-center gap-2">
          <Award className="h-5 w-5 text-purple-400" />
          <h2 className="font-semibold">Top Contributors This Month</h2>
          <Users className="ml-auto h-4 w-4 text-gray-500" />
        </div>
        {contributors.length === 0 ? (
          <p className="py-4 text-center text-sm text-gray-500">No contributions this month.</p>
        ) : (
          <div className="space-y-3">
            {contributors.map((c, i) => (
              <div key={c.user_id} className="flex items-center gap-3">
                <span className="w-6 shrink-0 text-sm font-bold text-gray-500">#{i + 1}</span>
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-purple-600 text-sm font-semibold">
                  {c.name?.[0]?.toUpperCase() ?? '?'}
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-white">{c.name}</p>
                  <p className="text-xs text-gray-400">{c.email}</p>
                </div>
                <div className="text-right">
                  <p className="text-sm font-semibold text-white">{c.doc_count}</p>
                  <p className="text-xs text-gray-400">docs</p>
                </div>
                <div className="w-24 shrink-0">
                  <div className="h-1.5 rounded-full bg-gray-700">
                    <div
                      className="h-1.5 rounded-full bg-purple-500"
                      style={{ width: `${(c.doc_count / maxCount) * 100}%` }}
                    />
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
