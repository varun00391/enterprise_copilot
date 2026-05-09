import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import {
  FileText, MessageSquare, TrendingUp, Clock,
  Upload, Brain, BookOpen, Loader2, CheckCircle,
  AlertCircle, ChevronRight
} from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import api from '../lib/api'
import { formatDistanceToNow } from 'date-fns'

function MetricCard({ icon: Icon, label, value, color = 'blue', loading }) {
  const colors = {
    blue: 'text-blue-400 bg-blue-500/20',
    green: 'text-green-400 bg-green-500/20',
    purple: 'text-purple-400 bg-purple-500/20',
    amber: 'text-amber-400 bg-amber-500/20',
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
        ? <div className="h-8 w-16 bg-navy-600 rounded animate-pulse" />
        : <p className="text-3xl font-bold text-white">{value}</p>
      }
    </div>
  )
}

const statusConfig = {
  indexed:   { label: 'Indexed',   color: 'badge-green',  icon: CheckCircle },
  uploading: { label: 'Uploading', color: 'badge-yellow', icon: Loader2 },
  parsing:   { label: 'Parsing',   color: 'badge-yellow', icon: Loader2 },
  chunking:  { label: 'Chunking',  color: 'badge-yellow', icon: Loader2 },
  embedding: { label: 'Embedding', color: 'badge-blue',   icon: Loader2 },
  failed:    { label: 'Failed',    color: 'badge-red',    icon: AlertCircle },
  uploaded:  { label: 'Uploaded',  color: 'badge-yellow', icon: Loader2 },
}

export default function UserDashboard() {
  const { user } = useAuth()
  const [metrics, setMetrics] = useState(null)
  const [activity, setActivity] = useState([])
  const [topDocs, setTopDocs] = useState([])
  const [pendingDocs, setPendingDocs] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const load = async () => {
      try {
        const [m, a, t, d] = await Promise.all([
          api.get('/analytics/dashboard'),
          api.get('/analytics/recent-activity'),
          api.get('/analytics/top-documents'),
          api.get('/documents?status=uploaded&limit=5').catch(() => ({ data: [] })),
        ])
        setMetrics(m.data)
        setActivity(a.data)
        setTopDocs(t.data)
        setPendingDocs(d.data.filter(doc => doc.status !== 'indexed'))
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  const now = new Date()
  const hour = now.getHours()
  const greeting = hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening'

  return (
    <div className="p-6 max-w-7xl mx-auto">
      {/* Welcome */}
      <div className="mb-8 animate-fade-in">
        <h1 className="text-2xl font-bold text-white">
          {greeting}, {user?.name?.split(' ')[0]} 👋
        </h1>
        <p className="text-gray-400 mt-1">
          {user?.dept_name || 'Your workspace'} · {now.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })}
        </p>
      </div>

      {/* Quick Actions */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-8">
        {[
          { to: '/upload',    icon: Upload,        label: 'Upload Files',    color: 'blue'   },
          { to: '/chat',      icon: MessageSquare, label: 'Ask a Question',  color: 'green'  },
          { to: '/knowledge', icon: BookOpen,      label: 'Knowledge Base',  color: 'purple' },
          { to: '/chat',      icon: Brain,         label: 'AI Chat',         color: 'amber'  },
        ].map(({ to, icon: Icon, label, color }) => (
          <Link key={label} to={to} className="flex flex-col items-center gap-2 p-4 card-hover cursor-pointer">
            <div className={`w-10 h-10 rounded-xl flex items-center justify-center ${
              color === 'blue'   ? 'bg-blue-500/20 text-blue-400'     :
              color === 'green'  ? 'bg-green-500/20 text-green-400'   :
              color === 'purple' ? 'bg-purple-500/20 text-purple-400' :
                                   'bg-amber-500/20 text-amber-400'
            }`}>
              <Icon className="w-5 h-5" />
            </div>
            <span className="text-sm font-medium text-gray-300">{label}</span>
          </Link>
        ))}
      </div>

      {/* Metric Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <MetricCard icon={FileText}     label="Total Documents"  value={metrics?.total_documents ?? 0}                                        color="blue"   loading={loading} />
        <MetricCard icon={MessageSquare} label="Questions Today" value={metrics?.questions_today ?? 0}                                        color="green"  loading={loading} />
        <MetricCard icon={TrendingUp}   label="Avg Confidence"   value={metrics ? `${Math.round(metrics.avg_confidence * 100)}%` : '—'}       color="purple" loading={loading} />
        <MetricCard icon={Clock}        label="Docs This Week"   value={metrics?.documents_this_week ?? 0}                                    color="amber"  loading={loading} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Recent Activity — compact timeline */}
        <div className="lg:col-span-2 card">
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-semibold text-white text-sm">Recent Activity</h2>
            <Link to="/chat" className="text-xs text-blue-400 hover:text-blue-300 flex items-center gap-1">
              Open Chat <ChevronRight className="w-3 h-3" />
            </Link>
          </div>

          {loading ? (
            <div className="space-y-2">
              {[1,2,3,4].map(i => <div key={i} className="h-10 bg-navy-600 rounded animate-pulse" />)}
            </div>
          ) : activity.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-10 text-gray-500">
              <MessageSquare className="w-7 h-7 mb-2 opacity-30" />
              <p className="text-xs">No queries yet. Ask your first question!</p>
            </div>
          ) : (
            <div className="divide-y divide-navy-700/50">
              {activity.slice(0, 6).map((item) => (
                <div key={item.id} className="flex items-start gap-3 py-2.5">
                  <div className="w-6 h-6 rounded-full bg-blue-500/15 flex items-center justify-center flex-shrink-0 mt-0.5">
                    <MessageSquare className="w-3 h-3 text-blue-400" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-medium text-white truncate">{item.query}</p>
                    <p className="text-xs text-gray-500 truncate mt-0.5">{item.answer_snippet}</p>
                    {item.source_doc && (
                      <p className="text-xs text-gray-600 mt-0.5 flex items-center gap-1">
                        <FileText className="w-2.5 h-2.5" />{item.source_doc}
                      </p>
                    )}
                  </div>
                  <div className="flex-shrink-0 text-right space-y-1">
                    {item.confidence != null && (
                      <span className="badge bg-blue-500/15 text-blue-300 text-[10px] px-1.5">
                        {Math.round(item.confidence * 100)}%
                      </span>
                    )}
                    <p className="text-[10px] text-gray-600">
                      {formatDistanceToNow(new Date(item.created_at), { addSuffix: true })}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Right column */}
        <div className="space-y-4">
          {/* Top Documents */}
          <div className="card">
            <div className="flex items-center justify-between mb-3">
              <h2 className="font-semibold text-white text-sm">Top Documents</h2>
              <Link to="/knowledge" className="text-xs text-blue-400 hover:text-blue-300">View all</Link>
            </div>
            {loading ? (
              <div className="space-y-2">
                {[1,2,3].map(i => <div key={i} className="h-9 bg-navy-600 rounded animate-pulse" />)}
              </div>
            ) : topDocs.length === 0 ? (
              <p className="text-xs text-gray-500 text-center py-4">No documents yet</p>
            ) : (
              <div className="space-y-1.5">
                {topDocs.map((doc) => (
                  <div key={doc.id} className="flex items-center gap-2.5 p-2 rounded-lg hover:bg-navy-800 transition-colors">
                    <div className="w-6 h-6 rounded bg-blue-500/20 flex items-center justify-center flex-shrink-0">
                      <FileText className="w-3 h-3 text-blue-400" />
                    </div>
                    <span className="text-xs text-gray-300 truncate flex-1">{doc.original_name}</span>
                    <span className="text-[10px] text-gray-600 uppercase font-medium">{doc.file_type}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Pending */}
          {pendingDocs.length > 0 && (
            <div className="card border-amber-500/20">
              <h2 className="font-semibold text-white text-sm mb-3 flex items-center gap-2">
                <Loader2 className="w-3.5 h-3.5 text-amber-400 animate-spin" />
                Processing ({pendingDocs.length})
              </h2>
              <div className="space-y-2">
                {pendingDocs.map((doc) => {
                  const cfg = statusConfig[doc.status] || statusConfig.uploaded
                  const Icon = cfg.icon
                  return (
                    <div key={doc.id} className="flex items-center justify-between gap-2">
                      <span className="text-xs text-gray-400 truncate flex-1">{doc.original_name}</span>
                      <span className={`badge ${cfg.color} flex items-center gap-1`}>
                        <Icon className="w-2.5 h-2.5" />
                        {cfg.label}
                      </span>
                    </div>
                  )
                })}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
