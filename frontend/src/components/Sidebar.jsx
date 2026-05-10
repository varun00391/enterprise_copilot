import { NavLink, useNavigate } from 'react-router-dom'
import {
  LayoutDashboard, MessageSquare, Upload, BookOpen,
  Settings, LogOut, Users, Building2, ClipboardList, Brain, BarChart2, Radio, Gauge
} from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import clsx from 'clsx'

const userNav = [
  { to: '/dashboard', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/chat', icon: MessageSquare, label: 'Chat' },
  { to: '/voice-agent', icon: Radio, label: 'Voice Agent' },
  { to: '/upload', icon: Upload, label: 'Upload Files' },
  { to: '/knowledge', icon: BookOpen, label: 'Knowledge Base' },
  { to: '/analytics', icon: BarChart2, label: 'Analytics' },
  { to: '/settings', icon: Settings, label: 'Settings' },
]

const adminNav = [
  { to: '/admin', icon: LayoutDashboard, label: 'Admin Dashboard', requireSuper: false },
  { to: '/admin/departments', icon: Building2, label: 'Departments', requireSuper: false },
  { to: '/admin/users', icon: Users, label: 'Users', requireSuper: true },
  { to: '/admin/evaluations', icon: Gauge, label: 'Evaluations', requireSuper: true },
  { to: '/admin/audit-log', icon: ClipboardList, label: 'Audit Log', requireSuper: true },
]

export default function Sidebar() {
  const { user, logout, isAdmin, isSuperAdmin } = useAuth()
  const navigate = useNavigate()

  const handleLogout = () => {
    logout()
    navigate('/')
  }

  return (
    <aside className="w-60 min-h-screen bg-navy-900 border-r border-navy-700 flex flex-col">
      <div className="p-5 border-b border-navy-700">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-blue-500 flex items-center justify-center">
            <Brain className="w-4 h-4 text-white" />
          </div>
          <span className="text-lg font-bold text-white">OrgMind</span>
        </div>
      </div>

      <div className="p-3 border-b border-navy-700">
        <div className="px-3 py-2">
          <p className="text-xs text-gray-500 uppercase tracking-wider mb-2">
            {isAdmin ? 'Admin Panel' : 'Workspace'}
          </p>
        </div>
        <nav className="space-y-0.5">
          {(isAdmin ? adminNav.filter((item) => !item.requireSuper || isSuperAdmin) : userNav).map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/admin' || to === '/dashboard'}
              className={({ isActive }) =>
                clsx(
                  'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all duration-200',
                  isActive
                    ? 'bg-blue-500/20 text-blue-300 border-r-2 border-blue-500'
                    : 'text-gray-400 hover:text-white hover:bg-navy-700'
                )
              }
            >
              <Icon className="w-4 h-4 flex-shrink-0" />
              {label}
            </NavLink>
          ))}
        </nav>
      </div>

      <div className="mt-auto p-3 border-t border-navy-700">
        <div className="px-3 py-2 mb-2">
          <p className="text-sm font-medium text-white truncate">{user?.name}</p>
          <p className="text-xs text-gray-500 truncate">{user?.email}</p>
          <span className="badge-blue mt-1">{user?.role?.replace('_', ' ')}</span>
        </div>
        <button
          onClick={handleLogout}
          className="flex items-center gap-3 w-full px-3 py-2.5 rounded-lg text-sm font-medium text-gray-400 hover:text-red-400 hover:bg-red-500/10 transition-all duration-200"
        >
          <LogOut className="w-4 h-4" />
          Sign Out
        </button>
      </div>
    </aside>
  )
}
