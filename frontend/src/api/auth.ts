import { http, getErrorMessage } from './http'
import type { TokenOut, UserOut } from './types'

export async function register(username: string, password: string): Promise<UserOut> {
  try {
    const resp = await http.post('/auth/register', { username, password })
    return resp.data as UserOut
  } catch (error) {
    throw new Error(getErrorMessage(error))
  }
}

export async function login(username: string, password: string): Promise<TokenOut> {
  try {
    const resp = await http.post('/auth/login', { username, password })
    return resp.data as TokenOut
  } catch (error) {
    throw new Error(getErrorMessage(error))
  }
}

export async function me(): Promise<UserOut> {
  try {
    const resp = await http.get('/auth/me')
    return resp.data as UserOut
  } catch (error) {
    throw new Error(getErrorMessage(error))
  }
}
