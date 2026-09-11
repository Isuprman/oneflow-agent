import { http, getErrorMessage } from './http'

export interface McpServerOut {
  id: number
  name: string
  command: string
  url: string
  env_json: string
  enabled: boolean
  status: 'connected' | 'error' | 'off'
  tools: string[]
  created_at: string | null
}

export interface McpServerIn {
  name: string
  command?: string
  url?: string
  enabled?: boolean
}

export async function listMcpServers(): Promise<McpServerOut[]> {
  try {
    const resp = await http.get('/mcp')
    return resp.data as McpServerOut[]
  } catch (error) {
    throw new Error(getErrorMessage(error))
  }
}

export async function addMcpServer(data: McpServerIn): Promise<McpServerOut> {
  try {
    const resp = await http.post('/mcp', data)
    return resp.data as McpServerOut
  } catch (error) {
    throw new Error(getErrorMessage(error))
  }
}

export async function toggleMcpServer(id: number, enabled: boolean): Promise<McpServerOut> {
  try {
    const resp = await http.put(`/mcp/${id}`, { enabled })
    return resp.data as McpServerOut
  } catch (error) {
    throw new Error(getErrorMessage(error))
  }
}

export async function deleteMcpServer(id: number): Promise<void> {
  try {
    await http.delete(`/mcp/${id}`)
  } catch (error) {
    throw new Error(getErrorMessage(error))
  }
}

export async function refreshMcpServer(name: string): Promise<McpServerOut> {
  try {
    const resp = await http.post(`/mcp/${name}/refresh`)
    return resp.data as McpServerOut
  } catch (error) {
    throw new Error(getErrorMessage(error))
  }
}
