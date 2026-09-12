import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { login, me, register } from '../api/auth'
import AuthFrame from '../components/AuthFrame'
import { useAuthStore } from '../store/auth'

export default function RegisterPage() {
  const navigate = useNavigate()
  const setToken = useAuthStore((s) => s.setToken)
  const setUser = useAuthStore((s) => s.setUser)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setError(''); setLoading(true)
    try { await register(username, password); const token = await login(username, password); setToken(token.access_token); setUser(await me()); navigate('/') } catch (err) { setError(err instanceof Error ? err.message : '注册失败，请稍后重试') } finally { setLoading(false) }
  }
  return <AuthFrame><p className="auth-kicker">ONEFLOW / INITIALIZE</p><h1 className="auth-heading">创建身份</h1><p className="auth-subtitle">建立你的专属智能协作通道。</p><form onSubmit={handleSubmit}><div className="field"><label htmlFor="username">用户名</label><input id="username" required autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} /></div><div className="field"><label htmlFor="password">密码</label><input id="password" type="password" required minLength={6} autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} /></div>{error && <p className="form-error" role="alert">{error}</p>}<button className="primary-button auth-submit" disabled={loading} type="submit">{loading ? '正在创建…' : '创建并进入'}</button></form><p className="auth-switch">已有账号？ <Link to="/login">返回登录</Link></p></AuthFrame>
}
