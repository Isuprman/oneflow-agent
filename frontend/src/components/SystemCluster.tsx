import { motion } from 'framer-motion'
import { Link } from 'react-router-dom'
import HudCorners from './HudCorners'

interface SystemClusterProps {
  username: string
  onLogout: () => void
}

/** 命令坞上方的身份块：用户名 · 设置 · 退出（仅身份，状态与转写分别并入命令坞/右上角）。 */
export default function SystemCluster({ username, onLogout }: SystemClusterProps) {
  return (
    <motion.div
      className="system-cluster"
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.24, ease: 'easeOut' }}
    >
      <HudCorners />
      <div className="sys-row">
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
    </motion.div>
  )
}
