import { motion } from 'framer-motion'
import { Link } from 'react-router-dom'
import HudCorners from './HudCorners'

interface CommandDockProps {
  input: string
  onInput: (value: string) => void
  onSend: () => void
  sending: boolean
  showInput: boolean
  username: string
  onLogout: () => void
  /** 状态文字（STANDBY 正在监听… / THINKING 思考中… / SPEAKING 播报中… / READY 就绪）。 */
  telemetry?: string
  /** 转写（正在监听同行内联展示）。 */
  transcript?: string
}

/** 底部悬浮玻璃命令坞：身份行(用户名·设置·退出) → 状态+转写同行 → 输入框（设置页开启时显示）。
 *  待命监听/声音驱动/唤醒词提示统一在设置页管理，此处不再展示开关。 */
export default function CommandDock({
  input,
  onInput,
  onSend,
  sending,
  showInput,
  username,
  onLogout,
  telemetry,
  transcript,
}: CommandDockProps) {
  return (
    <div className="command-dock-wrap">
      <motion.div
        className="command-dock"
        initial={{ y: 44, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ duration: 0.28, ease: 'easeOut' }}
      >
        <HudCorners />
        <div className="dock-identity">
          <span className="sys-identity">
            <span className="sys-identity__dot" />
            {username}
          </span>
          <Link className="sys-link" to="/settings">
            设置
          </Link>
          <button className="sys-link" onClick={onLogout}>
            退出
          </button>
        </div>
        <div className="dock-telemetry">
          <span
            className={`telemetry-dot ${sending ? 'is-thinking' : ''}`}
            aria-hidden="true"
          />
          <span className="dock-telemetry__text">{telemetry}</span>
          {transcript && <span className="dock-telemetry__transcript">{transcript}</span>}
        </div>
        {showInput && (
          <div className="dock-line">
            <input
              className="dock-input"
              aria-label="输入指令"
              value={input}
              onChange={(event) => onInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault()
                  onSend()
                }
              }}
              placeholder="输入指令，按 Enter 发送"
              spellCheck={false}
            />
            <button
              className="dock-send"
              disabled={sending || !input.trim()}
              onClick={onSend}
              aria-label="发送"
            >
              {sending ? <span className="dock-send__busy" /> : '发送'}
            </button>
          </div>
        )}
      </motion.div>
    </div>
  )
}
