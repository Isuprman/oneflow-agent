import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import SkillsSection from '../SkillsSection'
import type { LearnProposalOut } from '../../../api/learn'

const listMock = vi.fn()
const approveMock = vi.fn()
const rejectMock = vi.fn()

vi.mock('../../../api/learn', () => ({
  listLearnProposals: (...args: unknown[]) => listMock(...args),
  approveLearnProposal: (...args: unknown[]) => approveMock(...args),
  rejectLearnProposal: (...args: unknown[]) => rejectMock(...args),
}))

function pendingProposal(overrides: Partial<LearnProposalOut> = {}): LearnProposalOut {
  return {
    id: 7,
    slug: 'query_express',
    title: '查快递',
    description: '查询快递物流状态',
    status: 'pending',
    required_keys: { EXPRESS_API_KEY: '快递 API 密钥' },
    branch: 'skill/query_express',
    log: '',
    created_at: null,
    ...overrides,
  }
}

beforeEach(() => vi.clearAllMocks())

describe('SkillsSection 审批卡', () => {
  it('填入密钥后批准：以草稿中的 keys 调 approve 并显示上线信息', async () => {
    listMock.mockResolvedValue([pendingProposal()])
    approveMock.mockResolvedValue({ ok: true, message: '技能 query_express 已上线', tool_name: 'query_express', live: true })
    render(<SkillsSection />)

    await waitFor(() => expect(screen.getByText('query_express')).toBeTruthy())
    const input = screen.getByPlaceholderText('填入密钥后批准') as HTMLInputElement
    fireEvent.change(input, { target: { value: 'sk-test-1' } })
    fireEvent.click(screen.getByText('批准上线'))

    await waitFor(() => expect(approveMock).toHaveBeenCalledWith(7, { EXPRESS_API_KEY: 'sk-test-1' }))
    expect(await screen.findByText(/已热注册生效/)).toBeTruthy()
  })

  it('缺 key 返回 missing_keys：红字提示且不刷新列表', async () => {
    listMock.mockResolvedValue([pendingProposal()])
    approveMock.mockResolvedValue({ ok: false, missing_keys: { EXPRESS_API_KEY: '快递 API 密钥' } })
    render(<SkillsSection />)

    await waitFor(() => expect(screen.getByText('query_express')).toBeTruthy())
    fireEvent.click(screen.getByText('批准上线'))

    expect(await screen.findByText(/还缺这些密钥：EXPRESS_API_KEY/)).toBeTruthy()
    expect(screen.getByText('待审批')).toBeTruthy()
  })

  it('放弃：调 reject 并刷新', async () => {
    listMock.mockResolvedValue([pendingProposal()])
    rejectMock.mockResolvedValue({ ok: true, message: '已放弃 query_express' })
    render(<SkillsSection />)

    await waitFor(() => expect(screen.getByText('query_express')).toBeTruthy())
    fireEvent.click(screen.getByText('放弃'))

    await waitFor(() => expect(rejectMock).toHaveBeenCalledWith(7))
    expect(await screen.findByText(/已放弃 query_express/)).toBeTruthy()
  })
})
