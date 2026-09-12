import { http, getErrorMessage } from './http'

export interface Milestone {
  date: string | null
  title: string
}

export interface JournalData {
  first_skill: Milestone | null
  learned_count: number
  rejected_count: number
  milestones: Milestone[]
  total_tool_calls: number
}

/** 成长档案：学会技能数/调用量/里程碑时间线（里程碑按时间升序，最早即「第一个技能」）。 */
export async function getJournal(): Promise<JournalData> {
  try {
    const resp = await http.get('/journal')
    return resp.data as JournalData
  } catch (error) {
    throw new Error(getErrorMessage(error), { cause: error })
  }
}
