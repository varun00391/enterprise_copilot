import { useState, useEffect } from 'react'
import { Building2, AlertCircle, Loader2, CheckCircle } from 'lucide-react'
import api from '../lib/api'
import { useAuth } from '../context/AuthContext'

/**
 * Shown when a logged-in user has no department assigned.
 * Lets them pick one and saves it via PATCH /api/auth/me.
 * Calls onSuccess() after the user object is refreshed.
 */
export default function SelectDepartmentModal({ onSuccess }) {
  const { loadUser } = useAuth()
  const [departments, setDepartments] = useState([])
  const [selected, setSelected] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    api.get('/auth/departments')
      .then(({ data }) => setDepartments(data))
      .catch(() => setError('Could not load departments. Please refresh.'))
  }, [])

  const handleSave = async () => {
    if (!selected) return
    setSaving(true)
    setError('')
    try {
      await api.patch('/auth/me', { dept_id: selected })
      await loadUser()
      onSuccess?.()
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to save department.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div className="w-full max-w-md bg-navy-800 border border-navy-600 rounded-2xl shadow-2xl p-6 animate-slide-up">
        <div className="flex items-center gap-3 mb-4">
          <div className="w-10 h-10 rounded-xl bg-amber-500/20 flex items-center justify-center">
            <Building2 className="w-5 h-5 text-amber-400" />
          </div>
          <div>
            <h2 className="text-lg font-bold text-white">Select Your Department</h2>
            <p className="text-sm text-gray-400">Required before you can upload or chat</p>
          </div>
        </div>

        <p className="text-sm text-gray-400 mb-5">
          Your account isn't assigned to a department yet. Please choose one to continue.
        </p>

        {error && (
          <div className="flex items-center gap-2 bg-red-500/10 border border-red-500/30 text-red-300 rounded-lg p-3 text-sm mb-4">
            <AlertCircle className="w-4 h-4 flex-shrink-0" />
            {error}
          </div>
        )}

        <div className="mb-5">
          <label className="label">Department</label>
          <select
            className="input"
            value={selected}
            onChange={e => setSelected(e.target.value)}
            disabled={departments.length === 0}
          >
            <option value="">
              {departments.length === 0 ? 'Loading...' : 'Select a department'}
            </option>
            {departments.map(d => (
              <option key={d.id} value={d.id}>{d.name}</option>
            ))}
          </select>
        </div>

        <button
          onClick={handleSave}
          disabled={!selected || saving}
          className="btn-primary w-full py-3 flex items-center justify-center gap-2"
        >
          {saving
            ? <><Loader2 className="w-4 h-4 animate-spin" /> Saving...</>
            : <><CheckCircle className="w-4 h-4" /> Confirm Department</>
          }
        </button>
      </div>
    </div>
  )
}
