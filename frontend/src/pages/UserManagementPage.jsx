import { useState, useEffect } from 'react'
import { Users, Search, Filter, Edit2, Check, X, Loader2, UserCheck, UserX } from 'lucide-react'
import api from '../lib/api'
import { formatDistanceToNow } from 'date-fns'
import clsx from 'clsx'

const roleColors = {
  user: 'badge-blue',
  dept_admin: 'badge-yellow',
  super_admin: 'bg-purple-500/20 text-purple-300',
}

function EditRow({ user, departments, onSave, onCancel }) {
  const [form, setForm] = useState({ name: user.name, role: user.role, dept_id: user.dept_id || '', is_active: user.is_active })
  const [saving, setSaving] = useState(false)

  const handleSave = async () => {
    setSaving(true)
    await onSave(user.id, form)
    setSaving(false)
  }

  return (
    <tr className="bg-blue-500/5 border-y border-blue-500/20">
      <td className="px-4 py-3">
        <input className="input py-1.5 text-sm" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} />
      </td>
      <td className="px-4 py-3 text-sm text-gray-400">{user.email}</td>
      <td className="px-4 py-3">
        <select className="input py-1.5 text-sm" value={form.role} onChange={e => setForm({ ...form, role: e.target.value })}>
          <option value="user">user</option>
          <option value="dept_admin">dept_admin</option>
          <option value="super_admin">super_admin</option>
        </select>
      </td>
      <td className="px-4 py-3">
        <select className="input py-1.5 text-sm" value={form.dept_id} onChange={e => setForm({ ...form, dept_id: e.target.value })}>
          <option value="">No dept</option>
          {departments.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}
        </select>
      </td>
      <td className="px-4 py-3">
        <button
          onClick={() => setForm({ ...form, is_active: !form.is_active })}
          className={clsx('badge', form.is_active ? 'badge-green' : 'badge-red')}
        >
          {form.is_active ? 'Active' : 'Inactive'}
        </button>
      </td>
      <td className="px-4 py-3">
        <div className="flex items-center gap-2">
          <button onClick={handleSave} disabled={saving} className="p-1.5 rounded-lg bg-green-500/20 text-green-400 hover:bg-green-500/30">
            {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
          </button>
          <button onClick={onCancel} className="p-1.5 rounded-lg bg-red-500/10 text-red-400 hover:bg-red-500/20">
            <X className="w-4 h-4" />
          </button>
        </div>
      </td>
    </tr>
  )
}

export default function UserManagementPage() {
  const [users, setUsers] = useState([])
  const [departments, setDepartments] = useState([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [editingId, setEditingId] = useState(null)

  useEffect(() => {
    Promise.all([api.get('/admin/users?limit=100'), api.get('/admin/departments')])
      .then(([u, d]) => { setUsers(u.data); setDepartments(d.data) })
      .finally(() => setLoading(false))
  }, [])

  const handleSave = async (userId, form) => {
    try {
      const { data } = await api.put(`/admin/users/${userId}`, {
        name: form.name,
        role: form.role,
        dept_id: form.dept_id || null,
        is_active: form.is_active,
      })
      setUsers(prev => prev.map(u => u.id === userId ? data : u))
      setEditingId(null)
    } catch (err) {
      alert(err.response?.data?.detail || 'Update failed')
    }
  }

  const filtered = users.filter(u =>
    u.name.toLowerCase().includes(search.toLowerCase()) ||
    u.email.toLowerCase().includes(search.toLowerCase())
  )

  const getDeptName = (deptId) => departments.find(d => d.id === deptId)?.name || '—'

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <Users className="w-6 h-6 text-blue-400" />
            User Management
          </h1>
          <p className="text-gray-400 mt-1">{users.length} users across all departments</p>
        </div>
      </div>

      <div className="relative mb-5">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
        <input className="input pl-10" placeholder="Search users..." value={search} onChange={e => setSearch(e.target.value)} />
      </div>

      {loading ? (
        <div className="space-y-3">
          {[1,2,3,4,5].map(i => <div key={i} className="h-14 bg-navy-700 rounded-lg animate-pulse" />)}
        </div>
      ) : (
        <div className="card p-0 overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="border-b border-navy-600">
                {['Name', 'Email', 'Role', 'Department', 'Status', 'Actions'].map(h => (
                  <th key={h} className="text-left px-4 py-3 text-xs font-medium text-gray-400 uppercase tracking-wider">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-navy-700">
              {filtered.map(u => (
                editingId === u.id
                  ? <EditRow key={u.id} user={u} departments={departments} onSave={handleSave} onCancel={() => setEditingId(null)} />
                  : (
                    <tr key={u.id} className="hover:bg-navy-700/50 transition-colors">
                      <td className="px-4 py-3">
                        <p className="text-sm font-medium text-white">{u.name}</p>
                        <p className="text-xs text-gray-600">
                          Joined {formatDistanceToNow(new Date(u.created_at), { addSuffix: true })}
                        </p>
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-400">{u.email}</td>
                      <td className="px-4 py-3">
                        <span className={`badge ${roleColors[u.role] || 'badge-blue'}`}>{u.role}</span>
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-400">{getDeptName(u.dept_id)}</td>
                      <td className="px-4 py-3">
                        <span className={`badge ${u.is_active ? 'badge-green' : 'badge-red'}`}>
                          {u.is_active ? 'Active' : 'Inactive'}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <button
                          onClick={() => setEditingId(u.id)}
                          className="p-1.5 text-gray-500 hover:text-blue-400 hover:bg-blue-500/10 rounded-lg transition-colors"
                        >
                          <Edit2 className="w-4 h-4" />
                        </button>
                      </td>
                    </tr>
                  )
              ))}
            </tbody>
          </table>
          {filtered.length === 0 && (
            <p className="text-center text-gray-500 py-10 text-sm">No users found</p>
          )}
        </div>
      )}
    </div>
  )
}
