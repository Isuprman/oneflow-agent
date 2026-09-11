import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { login, me } from '../api/auth'
import AuthFrame from '../components/AuthFrame'
import { useAuthStore } from '../store/auth'

export default function LoginPage() {
  const navigate = useNavigate()
  const setToken = useAuthStore((s) => s.setToken)
  const setUser = useAuthStore((s) => s.setUser)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setError('')
    setLoading(true)
    try {
      const token = await login(username, password)
      setToken(token.access_token)
      setUser(await me())
      navigate('/')
    } catch (err) {
      setError(err instanceof Error ? err.message : '登录失败，请稍后重试')
    } finally {
      setLoading(false)
    }
  }

  return <AuthFrame><p className="auth-kicker">ONEFLOW / VOICE INTERFACE</p><h1 className="auth-heading">欢迎回来</h1><p className="auth-subtitle">连接你的智能协作终端。</p><form onSubmit={handleSubmit}><div className="field"><label htmlFor="username">用户名</label><input id="username" required autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} /></div><div className="field"><label htmlFor="password">密码</label><input id="password" type="password" required autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} /></div>{error && <p className="form-error" role="alert">{error}</p>}<button className="primary-button auth-submit" disabled={loading} type="submit">{loading ? '正在验证…' : '进入终端'}</button></form><p className="auth-switch">还没有账号？ <Link to="/register">创建账号</Link></p></AuthFrame>
}
