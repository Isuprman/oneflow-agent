import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { MotionConfig, AnimatePresence, motion, type Variants } from 'framer-motion'
import LearnProposalCard from '../components/LearnProposalCard'
import AiCore from '../components/AiCore'
import ParticleField from '../components/ParticleField'
import SceneFX from '../components/SceneFX'
import CommandDock from '../components/CommandDock'
import HoloTray from '../components/HoloTray'
import HudCorners from '../components/HudCorners'
import TelemetryStrip from '../components/TelemetryStrip'
import { getPrefs } from '../prefs'
import { useAuthStore } from '../store/auth'
import { getDesktopBridge } from '../lib/speech/bridge'
import { unlockAudio } from '../lib/speech/tone'
import { useConversations } from '../hooks/useConversations'
import { useHud } from '../hooks/useHud'
import { useCoreReactive } from '../hooks/useCoreReactive'
import { useStandby } from '../hooks/useStandby'
import { useTtsPlayback } from '../hooks/useTtsPlayback'
import { useProactive } from '../hooks/useProactive'
import { useChatStream } from '../hooks/useChatStream'

/** 全息 glitch-in 入场：轻微位移 + 透明度 + blur 收敛；用户/AI 分别。 */
const msgVariants: Record<'user' | 'assistant', Variants> = {
  user: {
    hidden: { opacity: 0, y: 16, filter: 'blur(6px)' },
    show: { opacity: 1, y: 0, filter: 'blur(0px)', transition: { duration: 0.3, ease: 'easeOut' } },
  },
  assistant: {
    hidden: { opacity: 0, y: -10, filter: 'blur(9px)' },
    show: {
      opacity: 1,
      y: 0,
      x: [0, 1.6, -1.2, 0],
      filter: ['blur(9px)', 'blur(4px)', 'blur(0px)'],
      transition: { duration: 0.32, ease: 'easeOut' },
    },
  },
}

// 聊天页装配层：各领域 hook 的接线与 JSX；状态与逻辑在 hooks/ 内自包含。
// 发送↔播报↔待命互相调用，沿用「最新实现 ref」模式解环（standby.bind / 共享镜像 ref）。
export default function ChatPage() {
  const navigate = useNavigate()
  const user = useAuthStore((state) => state.user)
  const logout = useAuthStore((state) => state.logout)
  const hud = useHud()
  // 回调里只依赖 useHud 的稳定原语（解构引用），避免依赖整个每渲染新建的 hud 对象
  const { setError, showToast, clearToast, showEcho, showJarvisEcho, holdJarvisEcho, fadeJarvisEcho } = hud
  const [trayOpen, setTrayOpen] = useState(false)
  const [showInput] = useState(() => getPrefs().showInput)
  const [micAvailable] = useState(() => typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getUserMedia)

  const convo = useConversations(setError, () => chat.setInput(''))
  const core = useCoreReactive(micAvailable, setError)
  const { reactiveLevelRef } = core

  // 忙闲镜像 ref：发送/播报 hook 写入，轮询 hook 读取（避免 interval 闭包过期）
  const sendingRef = useRef(false)

  const standby = useStandby({ setError, showJarvisEcho })
  const tts = useTtsPlayback({
    standbyOnRef: standby.standbyOnRef,
    resumeStandbyRef: standby.resumeStandbyRef,
    standbyActionsRef: standby.standbyActionsRef,
    holdJarvisEcho, fadeJarvisEcho,
    beginSpeakAnim: core.beginSpeakAnim, endSpeakAnim: core.endSpeakAnim,
  })
  const proactive = useProactive({
    sendingRef, voiceLiveRef: tts.voiceLiveRef, standbyOnRef: standby.standbyOnRef, voiceOnRef: tts.voiceOnRef,
    speakReply: tts.speakReply, showJarvisEcho, holdJarvisEcho, fadeJarvisEcho,
  })
  const chat = useChatStream({
    activeId: convo.activeId, setActiveId: convo.setActiveId, setConversations: convo.setConversations,
    sendingRef, voiceOnRef: tts.voiceOnRef,
    resumeStandbyRef: standby.resumeStandbyRef, standbyOnRef: standby.standbyOnRef, standbyActionsRef: standby.standbyActionsRef,
    showToast, clearToast, showEcho, showJarvisEcho, holdJarvisEcho, fadeJarvisEcho, setError,
    bumpInteraction: proactive.bumpInteraction, speakReply: tts.speakReply,
  })
  // 唤醒派发需要发送/播报的最新实现：渲染期注入（与原 handleWakeRef 模式一致）
  standby.bind({
    doSend: chat.doSend, speakReply: tts.speakReply, sendingRef,
    voiceLiveRef: tts.voiceLiveRef, speakChainRef: tts.speakChainRef, lastSpeakEndRef: tts.lastSpeakEndRef,
    bumpInteraction: proactive.bumpInteraction,
  })

  // 音频解锁（浏览器自动播放限制）：首次用户手势创建/resume AudioContext
  useEffect(() => {
    const unlock = () => { unlockAudio(); const audio = new Audio(); audio.src = 'data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQAAAAA='; audio.volume = 0; audio.play().catch(() => {}); window.removeEventListener('pointerdown', unlock); window.removeEventListener('keydown', unlock) }
    window.addEventListener('pointerdown', unlock); window.addEventListener('keydown', unlock)
    // 桌面端但本地语音模型未下载：提示下载方式，自动回退浏览器识别
    const bridge = getDesktopBridge()
    if (bridge && !bridge.asrAvailable()) setError('本地语音模型未下载：在 desktop 目录执行 npm run models（当前已回退浏览器识别）')
    return () => { if (transcriptTimerRef.current !== null) window.clearTimeout(transcriptTimerRef.current); window.removeEventListener('pointerdown', unlock); window.removeEventListener('keydown', unlock) }
  }, [setError])

  const { conversations, activeId, messages, loadingMessages, expandedTraces, setExpandedTraces, newChat } = convo
  const { input, setInput, sending, liveTool, pendingConfirm, corePulse, doSend } = chat
  const { standbyOn, wakeStatus, standbyLive, convoOn } = standby
  const { voiceLive } = tts

  const hasConversation = messages.length > 0
  const coreState = sending ? 'thinking' : voiceLive ? 'speaking' : standbyOn ? 'standby' : undefined
  const telemetry = sending ? (liveTool ? `CALL ${liveTool} 调用中…` : 'THINKING 思考中…') : voiceLive ? 'SPEAKING 播报中…' : convoOn ? '对话中 · 说「退下」结束' : standbyOn ? 'STANDBY 正在监听…' : 'SYSTEM READY 就绪'
  const standbyText = standbyOn ? (standbyLive ? `转写 ${standbyLive}` : wakeStatus) : ''
  const sysStatus = sending ? (liveTool ? 'CALL' : 'THINK') : voiceLive ? 'SPEAK' : convoOn ? 'TALK' : standbyOn ? 'STANDBY' : 'READY'

  // 转写展示：说话时显示，静音 ~2.2s 后淡出消失（仅影响右上角展示态，不动识别主流程）
  const [shownTranscript, setShownTranscript] = useState('')
  const transcriptTimerRef = useRef<number | null>(null)
  useEffect(() => {
    if (!standbyOn) {
      if (transcriptTimerRef.current !== null) window.clearTimeout(transcriptTimerRef.current)
      transcriptTimerRef.current = null
      setShownTranscript('')
      return
    }
    if (standbyText) {
      setShownTranscript(standbyText)
      if (transcriptTimerRef.current !== null) window.clearTimeout(transcriptTimerRef.current)
      transcriptTimerRef.current = window.setTimeout(() => {
        transcriptTimerRef.current = null
        setShownTranscript('')
      }, 2200)
    } else {
      setShownTranscript('')
    }
  }, [standbyText, standbyOn])

  return (
    <MotionConfig reducedMotion="user">
      <div className="hud-shell">
        <ParticleField />
        <SceneFX />
        <AnimatePresence>
          {hud.echo && (
            <motion.div
              className="hud-echo"
              initial={{ opacity: 0, y: -6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -4 }}
              transition={{ duration: 0.2, ease: 'easeOut' }}
              aria-live="polite"
            >
              <span className="holo-card__role">OPERATOR</span>
              <span className="holo-card__copy">{hud.echo}</span>
            </motion.div>
          )}
        </AnimatePresence>
        <AnimatePresence>
          {hud.jarvisEcho && (
            <motion.div
              className="hud-jarvis"
              initial={{ opacity: 0, y: -6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -4 }}
              transition={{ duration: 0.22, ease: 'easeOut' }}
              aria-live="polite"
            >
              <span className="holo-card__role">JARVIS</span>
              <span className="holo-card__copy">{hud.jarvisEcho}</span>
            </motion.div>
          )}
        </AnimatePresence>
        <AnimatePresence>
          {hud.toast && (
            <div className="hud-toast" role="alert">
              <motion.div
                className="hud-toast__inner"
                initial={{ opacity: 0, y: -8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -6 }}
                transition={{ duration: 0.22, ease: 'easeOut' }}
              >
                <span className="hud-toast__icon">⚠</span>
                <span className="hud-toast__msg">{hud.toast}</span>
              </motion.div>
            </div>
          )}
        </AnimatePresence>
        <TelemetryStrip sessionId={activeId} status={sysStatus} />
        {/* 成长档案入口：左上角玻璃徽标（与右上角回显对称），跳转 /journal */}
        <Link
          className="hud-action"
          to="/journal"
          style={{ position: 'absolute', top: 18, left: 24, zIndex: 40, display: 'inline-flex', alignItems: 'center', gap: 8 }}
        >
          <span
            aria-hidden="true"
            style={{
              width: 7,
              height: 7,
              flex: 'none',
              border: '1px solid rgba(56,189,248,.65)',
              boxShadow: '0 0 6px rgba(56,189,248,.4)',
              transform: 'rotate(45deg)',
            }}
          />
          成长档案
        </Link>
        <HoloTray
          open={trayOpen}
          onToggle={() => setTrayOpen((value) => !value)}
          conversations={conversations}
          activeId={activeId}
          onSelect={convo.selectConversation}
          onNew={() => void newChat()}
        />
        <main className="war-stage">
          <div className="stage-core">
            <motion.div
              className={`stage-core__inner ${hasConversation ? 'stage-core__inner--behind' : ''}`}
              initial={{ opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ duration: 0.3, ease: 'easeOut' }}
            >
              <AiCore state={coreState} compact={hasConversation} pulse={corePulse} reactiveLevelRef={reactiveLevelRef} />
            </motion.div>
          </div>

          {hud.error && <p className="feedback" role="alert">{hud.error}</p>}

          {loadingMessages ? (
            <div className="stage-center">
              <span className="stage-scanline" aria-hidden="true" />
              <p className="loading-state">正在读取会话…</p>
            </div>
          ) : !hasConversation ? (
            <div className="stage-empty">
              <motion.p
                className="tagline"
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.28, delay: 0.08, ease: 'easeOut' }}
              >
                我在，等待指令
              </motion.p>
              <div className="core-status">
                <span className={`core-dot ${standbyOn || sending ? 'is-live' : ''}`} />
                <span className="core-status__label">{standbyOn ? 'STANDBY LISTENING' : 'SYSTEM READY'}</span>
              </div>
            </div>
          ) : (
            <div className="holo-timeline">
              <span className="timeline-rail" aria-hidden="true" />
              {messages.map((message) => (
                <motion.div
                  key={message.id}
                  className={`holo-message ${message.role}${message.isStreaming ? ' is-streaming' : ''}`}
                  variants={msgVariants[message.role]}
                  initial="hidden"
                  animate="show"
                >
                  <div className={`holo-card ${message.role === 'assistant' ? 'holo-card--core' : ''}`}>
                    <HudCorners />
                    <span className="holo-card__role" title={message.role === 'user' ? '操作员（您）' : 'AI 贾维斯'}>{message.role === 'user' ? 'OPERATOR' : 'JARVIS'}</span>
                    <div className="holo-card__copy">
                      {message.content}
                      {message.isStreaming && <span className="type-cursor">▍</span>}
                    </div>
                    {message.role === 'assistant' && <LearnProposalCard content={message.content} />}
                    {message.trace && message.trace.length > 0 && (
                      <>
                        <button
                          className="trace-toggle"
                          onClick={() => setExpandedTraces((previous) => { const next = new Set(previous); if (next.has(message.id)) next.delete(message.id); else next.add(message.id); return next })}
                        >
                          {expandedTraces.has(message.id) ? '▾' : '▸'} 工具轨迹（{message.trace.length}步）
                        </button>
                        {expandedTraces.has(message.id) && (
                          <div className="trace-block">
                            {message.trace.map((step, index) => (
                              <div className="trace-step" key={`${step.tool}-${index}`}>
                                <div className="trace-step__head">
                                  <span>{step.tool}</span>
                                  <span className={step.success ? 'trace-success' : 'trace-failure'}>{step.success ? '成功' : '失败'}</span>
                                </div>
                                <p>参数：{JSON.stringify(step.arguments)}</p>
                                <p>结果：{JSON.stringify(step.result)}</p>
                              </div>
                            ))}
                          </div>
                        )}
                      </>
                    )}
                  </div>
                </motion.div>
              ))}
            </div>
          )}
        </main>

        {pendingConfirm && !sending && (
          <div className="confirm-bar" role="alertdialog" aria-label="高危操作确认">
            <span className="confirm-bar__text">{pendingConfirm.summary}</span>
            <button className="confirm-bar__btn confirm-bar__btn--ok" onClick={() => doSend('确认')}>确认执行</button>
            <button className="confirm-bar__btn" onClick={() => doSend('取消')}>取消</button>
          </div>
        )}

        <CommandDock
          input={input}
          onInput={setInput}
          onSend={() => doSend(input)}
          sending={sending}
          showInput={showInput}
          username={user?.username ?? ''}
          onLogout={() => { logout(); navigate('/login') }}
          telemetry={telemetry}
          transcript={shownTranscript}
        />
      </div>
    </MotionConfig>
  )
}
