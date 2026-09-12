import { http } from './http'

export interface LearnProposalOut {
  id: number
  slug: string
  title: string
  description: string
  status: string
  required_keys: Record<string, string>
  branch: string
  log: string
  created_at: string | null
}

export async function acquireSkill(request: string): Promise<LearnProposalOut> {
  const resp = await http.post('/learn/acquire', { request })
  return resp.data
}

export async function listLearnProposals(): Promise<LearnProposalOut[]> {
  const resp = await http.get('/learn/proposals')
  return resp.data
}

export async function approveLearnProposal(
  id: number,
  keys: Record<string, string>,
): Promise<{ ok: boolean; message?: string; tool_name?: string; live?: boolean; missing_keys?: Record<string, string> }> {
  const resp = await http.post(`/learn/proposals/${id}/approve`, { keys })
  return resp.data
}

export async function rejectLearnProposal(id: number): Promise<{ ok: boolean; message: string }> {
  const resp = await http.post(`/learn/proposals/${id}/reject`)
  return resp.data
}
