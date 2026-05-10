import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider } from './context/AuthContext'
import ProtectedRoute from './components/ProtectedRoute'
import AppLayout from './components/AppLayout'

import LandingPage from './pages/LandingPage'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'
import AdminLoginPage from './pages/AdminLoginPage'
import UserDashboard from './pages/UserDashboard'
import ChatPage from './pages/ChatPage'
import UploadPage from './pages/UploadPage'
import KnowledgeBasePage from './pages/KnowledgeBasePage'
import SettingsPage from './pages/SettingsPage'
import AdminDashboard from './pages/AdminDashboard'
import UserManagementPage from './pages/UserManagementPage'
import DeptManagementPage from './pages/DeptManagementPage'
import AuditLogPage from './pages/AuditLogPage'
import EvaluationsPage from './pages/EvaluationsPage'
import AnalyticsPage from './pages/AnalyticsPage'
import VoiceAgentPage from './pages/VoiceAgentPage'
import GoogleCallback from './pages/GoogleCallback'

function ProtectedApp({ children, ...props }) {
  return (
    <ProtectedRoute {...props}>
      <AppLayout>{children}</AppLayout>
    </ProtectedRoute>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          {/* Public */}
          <Route path="/" element={<LandingPage />} />
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route path="/admin/login" element={<AdminLoginPage />} />
          <Route path="/auth/google/callback" element={<GoogleCallback />} />

          {/* User routes */}
          <Route path="/dashboard" element={<ProtectedApp><UserDashboard /></ProtectedApp>} />
          <Route path="/chat" element={<ProtectedApp><ChatPage /></ProtectedApp>} />
          <Route path="/upload" element={<ProtectedApp><UploadPage /></ProtectedApp>} />
          <Route path="/knowledge" element={<ProtectedApp><KnowledgeBasePage /></ProtectedApp>} />
          <Route path="/settings" element={<ProtectedApp><SettingsPage /></ProtectedApp>} />
          <Route path="/analytics" element={<ProtectedApp><AnalyticsPage /></ProtectedApp>} />
          <Route path="/voice-agent" element={<ProtectedApp><VoiceAgentPage /></ProtectedApp>} />

          {/* Admin routes */}
          <Route path="/admin" element={<ProtectedApp requireAdmin><AdminDashboard /></ProtectedApp>} />
          <Route path="/admin/users" element={<ProtectedApp requireSuperAdmin><UserManagementPage /></ProtectedApp>} />
          <Route path="/admin/departments" element={<ProtectedApp requireAdmin><DeptManagementPage /></ProtectedApp>} />
          <Route path="/admin/audit-log" element={<ProtectedApp requireSuperAdmin><AuditLogPage /></ProtectedApp>} />
          <Route path="/admin/evaluations" element={<ProtectedApp requireSuperAdmin><EvaluationsPage /></ProtectedApp>} />

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  )
}
