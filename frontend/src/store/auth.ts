import { create } from 'zustand'
import type { UserOut } from '../api/types'
import { me } from '../api/auth'

interface AuthState {
  token: string | null
  user: UserOut | null
  isAuthed: () => boolean
  setToken: (token: string | null) => void
  setUser: (user: UserOut | null) => void
  logout: () => void
}

const storedToken = localStorage.getItem('oneflow_token')

export const useAuthStore = create<AuthState>()((set, get) => ({
  token: storedToken,
  user: null,
  isAuthed: () => Boolean(get().token),
  setToken: (token) => {
    set({ token })
    if (token) {
      localStorage.setItem('oneflow_token', token)
    } else {
      localStorage.removeItem('oneflow_token')
    }
  },
  setUser: (user) => set({ user }),
  logout: () => {
    set({ token: null, user: null })
    localStorage.removeItem('oneflow_token')
  },
}))

// 启动时校验已恢复的 token，若 /me 失败（如 401）则清除登录态
if (storedToken) {
  me()
    .then((user) => useAuthStore.getState().setUser(user))
    .catch(() => useAuthStore.getState().logout())
}
