import { http, getErrorMessage } from './http'

export interface PlanStepOut {
  idx: number
  description: string
  status: 'todo' | 'doing' | 'done' | 'blocked'
  note: string | null
}

export interface PlanOut {
  id: number
  title: string
  goal: string
  status: 'active' | 'paused' | 'done' | 'cancelled'
  steps: PlanStepOut[]
  created_at: string | null
}

export async function listPlans(): Promise<PlanOut[]> {
  try {
    const resp = await http.get('/plans')
    return resp.data as PlanOut[]
  } catch (error) {
    throw new Error(getErrorMessage(error), { cause: error })
  }
}

export async function setPlanStatus(id: number, status: PlanOut['status']): Promise<PlanOut> {
  try {
    const resp = await http.put(`/plans/${id}/status`, { status })
    return resp.data as PlanOut
  } catch (error) {
    throw new Error(getErrorMessage(error), { cause: error })
  }
}
