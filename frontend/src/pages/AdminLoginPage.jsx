import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Brain, Shield, Eye, EyeOff, AlertCircle } from 'lucide-react'
import { useAuth } from '../context/AuthContext'

export default function AdminLoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [form, setForm] = useState({ email: '', password: '' })
  const [showPw, setShowPw] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const user = await login(form.email, form.password)
      if (user.role !== 'super_admin' && user.role !== 'dept_admin') {
        setError('Access denied. Admin credentials required.')
        return
      }
      navigate('/admin')
    } catch (err) {
      setError(err.response?.data?.detail || 'Invalid credentials')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-4"
      style={{ background: 'linear-gradient(135deg, #060a1a 0%, #0a0f1f 50%, #0d1545 100%)' }}>
      <div className="w-full max-w-md animate-slide-up">
        <div className="text-center mb-8">
          <Link to="/" className="inline-flex items-center gap-2.5 mb-6">
            <div className="w-10 h-10 rounded-xl bg-blue-500 flex items-center justify-center">
              <Brain className="w-5 h-5 text-white" />
            </div>
            <span className="text-2xl font-bold text-white">OrgMind</span>
          </Link>

          <div className="inline-flex items-center gap-2 bg-amber-500/10 border border-amber-500/30 text-amber-300 rounded-full px-4 py-1.5 text-sm mb-4">
            <Shield className="w-4 h-4" />
            Admin Portal
          </div>

          <h1 className="text-2xl font-bold text-white mb-1">Platform Administration</h1>
          <p className="text-gray-400">Restricted to administrators only</p>
        </div>

        <div className="card border-amber-500/20 bg-navy-700">
          <div className="flex items-center gap-2 bg-amber-500/10 border border-amber-500/20 rounded-lg p-3 mb-5 text-sm text-amber-300">
            <Shield className="w-4 h-4 flex-shrink-0" />
            This portal is for super_admin and dept_admin accounts only.
          </div>

          <form onSubmit={handleSubmit} className="space-y-5">
            {error && (
              <div className="flex items-center gap-2 bg-red-500/10 border border-red-500/30 text-red-300 rounded-lg p-3 text-sm">
                <AlertCircle className="w-4 h-4 flex-shrink-0" />
                {error}
              </div>
            )}

            <div>
              <label className="label">Admin Email</label>
              <input
                type="email"
                className="input"
                placeholder="admin@company.com"
                value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })}
                required
                autoFocus
              />
            </div>

            <div>
              <label className="label">Admin Password</label>
              <div className="relative">
                <input
                  type={showPw ? 'text' : 'password'}
                  className="input pr-11"
                  placeholder="••••••••"
                  value={form.password}
                  onChange={(e) => setForm({ ...form, password: e.target.value })}
                  required
                />
                <button
                  type="button"
                  onClick={() => setShowPw(!showPw)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300"
                >
                  {showPw ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>

            <button type="submit" disabled={loading}
              className="w-full py-3 rounded-lg bg-amber-500 hover:bg-amber-600 text-white font-semibold text-base transition-all duration-200 disabled:opacity-50">
              {loading ? 'Authenticating...' : 'Access Admin Panel'}
            </button>
          </form>
        </div>

        <p className="text-center mt-4 text-sm text-gray-600">
          Regular user?{' '}
          <Link to="/login" className="text-gray-500 hover:text-gray-400">
            User login →
          </Link>
        </p>
      </div>
    </div>
  )
}
