import { useState, useEffect } from 'react'
import { Building2, Plus, Trash2, Loader2, HardDrive } from 'lucide-react'
import api from '../lib/api'
import { formatDistanceToNow } from 'date-fns'

export default function DeptManagementPage() {
  const [departments, setDepartments] = useState([])
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState({ name: '', slug: '', storage_quota_mb: 5000 })
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    api.get('/admin/departments').then(({ data }) => setDepartments(data)).finally(() => setLoading(false))
  }, [])

  const handleCreate = async (e) => {
    e.preventDefault()
    setError('')
    setCreating(true)
    try {
      const { data } = await api.post('/admin/departments', form)
      setDepartments(prev => [data, ...prev])
      setForm({ name: '', slug: '', storage_quota_mb: 5000 })
      setShowForm(false)
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to create department')
    } finally {
      setCreating(false)
    }
  }

  const handleDelete = async (id) => {
    if (!confirm('Delete this department? This will not delete users or documents.')) return
    try {
      await api.delete(`/admin/departments/${id}`)
      setDepartments(prev => prev.filter(d => d.id !== id))
    } catch (err) {
      alert(err.response?.data?.detail || 'Failed to delete')
    }
  }

  const autoSlug = (name) => name.toLowerCase().replace(/\s+/g, '-').replace(/[^a-z0-9-]/g, '')

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <Building2 className="w-6 h-6 text-blue-400" />
            Department Management
          </h1>
          <p className="text-gray-400 mt-1">Configure isolated knowledge namespaces</p>
        </div>
        <button onClick={() => setShowForm(!showForm)} className="btn-primary flex items-center gap-2">
          <Plus className="w-4 h-4" />
          New Department
        </button>
      </div>

      {/* Create form */}
      {showForm && (
        <div className="card mb-6 border-blue-500/30 animate-slide-up">
          <h2 className="font-semibold text-white mb-4">Create Department</h2>
          <form onSubmit={handleCreate} className="space-y-4">
            {error && <div className="text-red-400 text-sm bg-red-500/10 border border-red-500/20 rounded-lg p-3">{error}</div>}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="label">Department Name</label>
                <input
                  className="input"
                  placeholder="e.g. Human Resources"
                  value={form.name}
                  onChange={e => {
                    const name = e.target.value
                    setForm({ ...form, name, slug: autoSlug(name) })
                  }}
                  required
                />
              </div>
              <div>
                <label className="label">Slug (URL identifier)</label>
                <input
                  className="input font-mono"
                  placeholder="e.g. human-resources"
                  value={form.slug}
                  onChange={e => setForm({ ...form, slug: e.target.value })}
                  required
                />
              </div>
            </div>
            <div>
              <label className="label">Storage Quota (MB)</label>
              <input
                type="number"
                className="input w-48"
                value={form.storage_quota_mb}
                onChange={e => setForm({ ...form, storage_quota_mb: parseInt(e.target.value) || 5000 })}
                min="100"
                max="100000"
              />
            </div>
            <div className="flex gap-3">
              <button type="submit" disabled={creating} className="btn-primary flex items-center gap-2">
                {creating ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
                {creating ? 'Creating...' : 'Create Department'}
              </button>
              <button type="button" onClick={() => setShowForm(false)} className="btn-ghost">Cancel</button>
            </div>
          </form>
        </div>
      )}

      {/* Department list */}
      {loading ? (
        <div className="space-y-3">
          {[1,2,3,4].map(i => <div key={i} className="h-20 bg-navy-700 rounded-lg animate-pulse" />)}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {departments.map(dept => (
            <div key={dept.id} className="card-hover">
              <div className="flex items-start justify-between">
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <div className="w-8 h-8 rounded-lg bg-blue-500/20 flex items-center justify-center">
                      <Building2 className="w-4 h-4 text-blue-400" />
                    </div>
                    <h3 className="font-semibold text-white">{dept.name}</h3>
                  </div>
                  <p className="text-xs font-mono text-gray-500 ml-10">{dept.slug}</p>
                </div>
                <button
                  onClick={() => handleDelete(dept.id)}
                  className="text-gray-600 hover:text-red-400 transition-colors p-1"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
              <div className="mt-3 flex items-center gap-4 text-xs text-gray-500">
                <span className="flex items-center gap-1">
                  <HardDrive className="w-3 h-3" />
                  {dept.storage_quota_mb.toLocaleString()} MB quota
                </span>
                <span>Created {formatDistanceToNow(new Date(dept.created_at), { addSuffix: true })}</span>
              </div>
            </div>
          ))}
        </div>
      )}

      {!loading && departments.length === 0 && (
        <div className="text-center py-16">
          <Building2 className="w-12 h-12 text-gray-600 mx-auto mb-3" />
          <p className="text-gray-400">No departments yet. Create your first one.</p>
        </div>
      )}
    </div>
  )
}
