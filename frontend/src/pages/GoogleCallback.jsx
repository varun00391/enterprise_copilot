import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Brain, Loader2 } from 'lucide-react'
import { useAuth } from '../context/AuthContext'

export default function GoogleCallback() {
  const navigate = useNavigate()
  const { loadUser } = useAuth()

  useEffect(() => {
    const searchParams = new URLSearchParams(window.location.search)
    const hashQs = window.location.hash?.startsWith('#')
      ? window.location.hash.slice(1)
      : ''
    const hashParams = new URLSearchParams(hashQs)

    let accessToken = hashParams.get('access_token') || searchParams.get('access_token')
    let refreshToken = hashParams.get('refresh_token') || searchParams.get('refresh_token')
    const fromOAuthHash = !!(hashParams.get('access_token') && hashParams.get('refresh_token'))

    // StrictMode remount can run after the hash was stripped; tokens may already be in localStorage.
    if (!accessToken || !refreshToken) {
      accessToken = localStorage.getItem('access_token')
      refreshToken = localStorage.getItem('refresh_token')
    }

    if (accessToken && refreshToken) {
      localStorage.setItem('access_token', accessToken)
      localStorage.setItem('refresh_token', refreshToken)
      if (fromOAuthHash) {
        window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}`)
      }

      void (async () => {
        try {
          const user = await loadUser()
          if (!user) {
            navigate('/login', { replace: true })
            return
          }
          const target =
            user.role === 'super_admin' || user.role === 'dept_admin' ? '/admin' : '/dashboard'
          // Defer past React commit so ProtectedRoute sees user (avoids bounce to /login).
          setTimeout(() => navigate(target, { replace: true }), 0)
        } catch {
          navigate('/login', { replace: true })
        }
      })()
      return
    }
    navigate('/login?error=oauth_failed')
  // Run once on mount; hash/query must not be wiped before we read tokens.
  // eslint-disable-next-line react-hooks/exhaustive-deps -- intentional
  }, [])

  return (
    <div className="flex min-h-screen items-center justify-center bg-navy-800">
      <div className="text-center">
        <div className="mb-4 flex justify-center">
          <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-blue-500">
            <Brain className="h-6 w-6 text-white" />
          </div>
        </div>
        <Loader2 className="mx-auto h-6 w-6 animate-spin text-blue-400" />
        <p className="mt-3 text-sm text-gray-400">Completing sign in…</p>
      </div>
    </div>
  )
}
