import { act } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useHud } from '../useHud'

// HUD 显示通道的计时器语义：Toast/回显自动消失、hold 取消待发淡出、fade 重置计时器
beforeEach(() => { vi.useFakeTimers() })
afterEach(() => { vi.useRealTimers() })

function setup() {
  return renderHook(() => useHud()).result
}

describe('useHud', () => {
  it('showToast 弹出并在 2.5s 后自动消失', () => {
    const result = setup()
    act(() => result.current.showToast('出错了'))
    expect(result.current.toast).toBe('出错了')
    act(() => vi.advanceTimersByTime(2500))
    expect(result.current.toast).toBeNull()
  })

  it('showToast 重复调用重置计时器', () => {
    const result = setup()
    act(() => result.current.showToast('第一次'))
    act(() => vi.advanceTimersByTime(2000))
    act(() => result.current.showToast('第二次'))
    act(() => vi.advanceTimersByTime(2400))
    expect(result.current.toast).toBe('第二次')
    act(() => vi.advanceTimersByTime(200))
    expect(result.current.toast).toBeNull()
  })

  it('clearToast 立即清除并取消待发消失', () => {
    const result = setup()
    act(() => result.current.showToast('x'))
    act(() => result.current.clearToast())
    expect(result.current.toast).toBeNull()
    act(() => vi.advanceTimersByTime(3000))
    expect(result.current.toast).toBeNull()
  })

  it('showEcho 2s 自动消失', () => {
    const result = setup()
    act(() => result.current.showEcho('开灯'))
    expect(result.current.echo).toBe('开灯')
    act(() => vi.advanceTimersByTime(2000))
    expect(result.current.echo).toBeNull()
  })

  it('holdJarvisEcho 取消待发淡出（播报接管展示权），此后 fade 重新计时', () => {
    const result = setup()
    act(() => result.current.showJarvisEcho('回复'))
    act(() => result.current.fadeJarvisEcho(3500))
    act(() => vi.advanceTimersByTime(3000))
    act(() => result.current.holdJarvisEcho())
    act(() => vi.advanceTimersByTime(1000))
    // 原 3500ms 已过期，但被 hold 取消，文字保持
    expect(result.current.jarvisEcho).toBe('回复')
    act(() => result.current.fadeJarvisEcho(3500))
    act(() => vi.advanceTimersByTime(3500))
    expect(result.current.jarvisEcho).toBeNull()
  })

  it('fadeJarvisEcho 重复调用重置计时器', () => {
    const result = setup()
    act(() => result.current.showJarvisEcho('回复'))
    act(() => result.current.fadeJarvisEcho(6000))
    act(() => vi.advanceTimersByTime(5500))
    act(() => result.current.fadeJarvisEcho(6000))
    act(() => vi.advanceTimersByTime(5900))
    expect(result.current.jarvisEcho).toBe('回复')
    act(() => vi.advanceTimersByTime(200))
    expect(result.current.jarvisEcho).toBeNull()
  })

  it('showJarvisEcho(null) 立即清空', () => {
    const result = setup()
    act(() => result.current.showJarvisEcho('回复'))
    act(() => result.current.showJarvisEcho(null))
    expect(result.current.jarvisEcho).toBeNull()
  })
})
