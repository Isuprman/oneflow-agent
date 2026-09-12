import { act } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useChatStream } from '../useChatStream'

// 发送链路测试：mock streamChat 捕获回调，逐个驱动事件验证状态机
const streamChatMock = vi.fn()

vi.mock('../../api/chat', () => ({ streamChat: (...args: unknown[]) => streamChatMock(...args) }))
vi.mock('../../api/conversations', () => ({ listConversations: () => Promise.resolve([]) }))

type Captured = {
  conversationId: number | null
  message: string
  onDelta: (text: string) => void
  onDone: (resp: { reply: string; conversation_id: number }) => void
  onError: (e: Error) => void
  onStep: (step: { tool: string; status: 'calling' | 'done' }) => void
  onPending: (p: { tool: string; summary: string }) => void
}

function setup(activeId: number | null = 1) {
  const deps = {
    activeId,
    setActiveId: vi.fn(),
    setConversations: vi.fn(),
    sendingRef: { current: false },
    voiceOnRef: { current: false },
    resumeStandbyRef: { current: false },
    standbyOnRef: { current: false },
    standbyActionsRef: { current: { pause: vi.fn(), resume: vi.fn() } },
    showToast: vi.fn(),
    clearToast: vi.fn(),
    showEcho: vi.fn(),
    showJarvisEcho: vi.fn(),
    holdJarvisEcho: vi.fn(),
    fadeJarvisEcho: vi.fn(),
    setError: vi.fn(),
    bumpInteraction: vi.fn(),
    speakReply: vi.fn(),
  }
  const rendered = renderHook(() => useChatStream(deps))
  return { ...rendered, deps }
}

function captureStream(): Captured {
  expect(streamChatMock).toHaveBeenCalled()
  const args = streamChatMock.mock.calls[0]
  return {
    conversationId: args[0] as number | null,
    message: args[1] as string,
    onDelta: args[2],
    onDone: args[3],
    onError: args[4],
    onStep: args[5],
    onPending: args[6],
  }
}

beforeEach(() => vi.clearAllMocks())

describe('useChatStream', () => {
  it('空输入不发起请求', () => {
    const { result } = setup()
    act(() => result.current.doSend('   '))
    expect(streamChatMock).not.toHaveBeenCalled()
  })

  it('忙时明确提示，不静默丢弃第二条指令', () => {
    const { result, deps } = setup()
    streamChatMock.mockReturnValue(new Promise(() => {})) // 挂起：模拟进行中
    act(() => result.current.doSend('第一条'))
    act(() => result.current.doSend('第二条'))
    expect(streamChatMock).toHaveBeenCalledTimes(1)
    expect(deps.showToast).toHaveBeenCalledWith('正在处理上一件事，请稍候')
  })

  it('成功路径：增量进回显、完成后调 speakReply 并按 voiceOn 决定淡出', async () => {
    const { result, deps } = setup()
    streamChatMock.mockResolvedValue(undefined)
    act(() => result.current.doSend('北京天气'))
    const stream = captureStream()
    expect(stream.message).toBe('北京天气')
    expect(deps.showEcho).toHaveBeenCalledWith('北京天气')

    act(() => stream.onDelta('今天晴'))
    expect(deps.showJarvisEcho).toHaveBeenCalledWith('今天晴')
    expect(deps.holdJarvisEcho).toHaveBeenCalled()

    // onDone 手动驱动；streamChat 的 promise 微任务在 act 内冲刷，finally 才会复位 sending
    await act(async () => {
      stream.onDone({ reply: '今天晴，25 度', conversation_id: 1 })
      await Promise.resolve()
    })
    expect(deps.speakReply).toHaveBeenCalledWith('今天晴，25 度', true)
    // voiceOnRef=false：文字立即安排淡出；true 时由 speakReply 接管
    expect(deps.fadeJarvisEcho).toHaveBeenCalledWith(3500)
    expect(result.current.sending).toBe(false)
  })

  it('首条消息自动建会话：activeId 为 null 时回填并刷新列表', () => {
    const { result, deps } = setup(null)
    streamChatMock.mockResolvedValue(undefined)
    act(() => result.current.doSend('你好'))
    const stream = captureStream()
    expect(stream.conversationId).toBeNull()
    act(() => stream.onDone({ reply: '遵命', conversation_id: 5 }))
    expect(deps.setActiveId).toHaveBeenCalledWith(5)
  })

  it('错误路径：Toast 提示、清回显，且同轮 onDone 不再播报', () => {
    const { result, deps } = setup()
    streamChatMock.mockResolvedValue(undefined)
    act(() => result.current.doSend('查天气'))
    const stream = captureStream()

    act(() => stream.onError(new Error('boom')))
    expect(deps.showToast).toHaveBeenCalledWith('boom')
    expect(deps.showJarvisEcho).toHaveBeenCalledWith(null)

    act(() => stream.onDone({ reply: '错误文本', conversation_id: 1 }))
    expect(deps.speakReply).not.toHaveBeenCalled()
  })

  it('高危确认与工具步骤事件驱动状态', () => {
    const { result } = setup()
    streamChatMock.mockResolvedValue(undefined)
    act(() => result.current.doSend('记一笔'))
    const stream = captureStream()

    act(() => stream.onStep({ tool: 'add_expense', status: 'calling' }))
    expect(result.current.liveTool).toBe('add_expense')
    act(() => stream.onStep({ tool: 'add_expense', status: 'done' }))
    expect(result.current.liveTool).toBe('')

    act(() => stream.onPending({ tool: 'add_expense', summary: '记一笔支出' }))
    expect(result.current.pendingConfirm).toEqual({ tool: 'add_expense', summary: '记一笔支出' })
  })
})
