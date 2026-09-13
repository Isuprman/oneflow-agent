import { act } from 'react'
import { waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useTtsPlayback } from '../useTtsPlayback'

// 播报管道测试：mock 合成请求与音频播放，splitSentences 用真实实现
const ttsMock = vi.fn()
const playBlobMock = vi.fn()
const speakFallbackMock = vi.fn()

vi.mock('../../api/tts', () => ({ tts: (...args: unknown[]) => ttsMock(...args) }))
vi.mock('../../lib/speech/playback', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/speech/playback')>()
  return {
    ...actual,
    playBlob: (...args: unknown[]) => playBlobMock(...args),
    speak: (...args: unknown[]) => speakFallbackMock(...args),
  }
})

function setPrefs(voice: boolean) {
  localStorage.setItem('oneflow_prefs', JSON.stringify({
    standby: false, voice, audioDrive: false, showInput: false,
    ttsVoice: 'zh-CN-XiaoxiaoNeural', chitchat: false,
  }))
}

function setup() {
  const opts = {
    standbyOnRef: { current: false },
    resumeStandbyRef: { current: false },
    standbyActionsRef: { current: { pause: vi.fn(), resume: vi.fn() } },
    holdJarvisEcho: vi.fn(),
    fadeJarvisEcho: vi.fn(),
    beginSpeakAnim: vi.fn(),
    endSpeakAnim: vi.fn(),
  }
  const rendered = renderHook(() => useTtsPlayback(opts))
  return { ...rendered, opts }
}

beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
})

describe('useTtsPlayback', () => {
  it('播完整段：voiceLive 复位、回显安排淡出、声动收尾', async () => {
    setPrefs(true)
    ttsMock.mockResolvedValue(new Blob(['x']))
    playBlobMock.mockResolvedValue(undefined)
    const { result, opts } = setup()

    act(() => result.current.speakReply('你好。先生。'))
    expect(result.current.voiceLive).toBe(true)
    await waitFor(() => expect(result.current.voiceLive).toBe(false))

    expect(playBlobMock).toHaveBeenCalledTimes(2)
    expect(opts.holdJarvisEcho).toHaveBeenCalled()
    expect(opts.fadeJarvisEcho).toHaveBeenCalledWith(3500)
    expect(opts.beginSpeakAnim).toHaveBeenCalled()
    expect(opts.endSpeakAnim).toHaveBeenCalled()
  })

  it('单句合成失败回退浏览器语音，不播音频', async () => {
    setPrefs(true)
    ttsMock.mockRejectedValue(new Error('合成失败'))
    speakFallbackMock.mockResolvedValue(undefined)
    const { result } = setup()

    act(() => result.current.speakReply('你好。先生。'))
    await waitFor(() => expect(result.current.voiceLive).toBe(false))

    expect(speakFallbackMock).toHaveBeenCalledTimes(2)
    expect(playBlobMock).not.toHaveBeenCalled()
  })

  it('播放被打断：剩余句子不再播，等安全网收尾', async () => {
    setPrefs(true)
    ttsMock.mockResolvedValue(new Blob(['x']))
    playBlobMock.mockRejectedValueOnce(new Error('interrupted'))
    const { result, opts } = setup()

    act(() => result.current.speakReply('你好。先生。'))
    await waitFor(() => expect(playBlobMock).toHaveBeenCalledTimes(1))
    await act(async () => { await Promise.resolve() })
    // 第二句不再播，且不安排正常淡出（finish 未执行）
    expect(playBlobMock).toHaveBeenCalledTimes(1)
    expect(result.current.voiceLive).toBe(true)
    expect(opts.fadeJarvisEcho).not.toHaveBeenCalledWith(3500)
  })

  it('voiceOn 关闭时 speakReply 整体 no-op', async () => {
    setPrefs(false)
    const { result } = setup()

    act(() => result.current.speakReply('你好。先生。'))
    await act(async () => { await Promise.resolve() })
    expect(result.current.voiceLive).toBe(false)
    expect(ttsMock).not.toHaveBeenCalled()
  })
})
