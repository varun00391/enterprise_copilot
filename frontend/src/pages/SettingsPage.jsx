import { useState } from 'react'
import { User, Lock, Bell, Shield, CheckCircle } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import api from '../lib/api'

export default function SettingsPage() {
  const { user, loadUser } = useAuth()
  const [profile, setProfile] = useState({ name: user?.name || '' })
  const [password, setPassword] = useState({ current: '', new: '', confirm: '' })
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState('')

  const handleSaveProfile = async (e) => {
    e.preventDefault()
    setSaving(true)
    setError('')
    try {
      await api.patch('/auth/me', { name: profile.name })
      await loadUser()
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    } catch (err) {
      setError(err.response?.data?.detail || 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="p-6 max-w-2xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-white">Settings</h1>
        <p className="text-gray-400 mt-1">Manage your account and preferences</p>
      </div>

      <div className="space-y-6">
        {/* Profile */}
        <div className="card">
          <h2 className="font-semibold text-white mb-4 flex items-center gap-2">
            <User className="w-4 h-4 text-blue-400" />
            Profile Information
          </h2>
          <form onSubmit={handleSaveProfile} className="space-y-4">
            {error && (
              <div className="text-red-400 text-sm bg-red-500/10 border border-red-500/20 rounded-lg p-3">{error}</div>
            )}
            <div>
              <label className="label">Full Name</label>
              <input
                className="input"
                value={profile.name}
                onChange={e => setProfile({ ...profile, name: e.target.value })}
              />
            </div>
            <div>
              <label className="label">Email</label>
              <input className="input opacity-60 cursor-not-allowed" value={user?.email} disabled />
              <p className="text-xs text-gray-600 mt-1">Email cannot be changed</p>
            </div>
            <div>
              <label className="label">Department</label>
              <input className="input opacity-60 cursor-not-allowed" value={user?.dept_name || 'Not assigned'} disabled />
            </div>
            <div>
              <label className="label">Role</label>
              <input className="input opacity-60 cursor-not-allowed" value={user?.role?.replace('_', ' ')} disabled />
            </div>
            <button type="submit" disabled={saving} className="btn-primary flex items-center gap-2">
              {saved ? (
                <><CheckCircle className="w-4 h-4" /> Saved!</>
              ) : saving ? 'Saving...' : 'Save Changes'}
            </button>
          </form>
        </div>

        {/* Security info */}
        <div className="card">
          <h2 className="font-semibold text-white mb-4 flex items-center gap-2">
            <Shield className="w-4 h-4 text-blue-400" />
            Security
          </h2>
          <div className="space-y-3 text-sm">
            <div className="flex items-center justify-between p-3 bg-navy-800 rounded-lg">
              <span className="text-gray-300">Two-Factor Authentication</span>
              <span className="badge-yellow">Coming in Phase 2</span>
            </div>
            <div className="flex items-center justify-between p-3 bg-navy-800 rounded-lg">
              <span className="text-gray-300">Session Management</span>
              <span className="badge-yellow">Coming in Phase 2</span>
            </div>
            <div className="flex items-center justify-between p-3 bg-navy-800 rounded-lg">
              <span className="text-gray-300">API Keys</span>
              <span className="badge-yellow">Coming in Phase 4</span>
            </div>
          </div>
        </div>

        {/* Account info */}
        <div className="card bg-navy-700/50">
          <h2 className="font-semibold text-white mb-3 flex items-center gap-2">
            <Bell className="w-4 h-4 text-blue-400" />
            Account Details
          </h2>
          <div className="grid grid-cols-2 gap-3 text-sm">
            <div>
              <p className="text-gray-500">Member since</p>
              <p className="text-white">{user?.created_at ? new Date(user.created_at).toLocaleDateString() : '—'}</p>
            </div>
            <div>
              <p className="text-gray-500">Account status</p>
              <span className="badge-green">Active</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
