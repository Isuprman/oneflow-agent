import { Navigate, Outlet, Route, Routes } from 'react-router-dom'
import ChatPage from './pages/ChatPage'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'
import SettingsPage from './pages/SettingsPage'
import { useAuthStore } from './store/auth'

function ProtectedRoute() {
  const isAuthed = useAuthStore((s) => s.isAuthed())
  if (!isAuthed) {
    return <Navigate to="/login" replace />
  }
  return <Outlet />
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route element={<ProtectedRoute />}>
        <Route path="/" element={<ChatPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*" element={<ChatPage />} />
      </Route>
    </Routes>
  )
}
