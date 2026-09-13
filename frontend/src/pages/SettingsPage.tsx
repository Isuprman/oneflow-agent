import { Link } from 'react-router-dom'
import ParticleField from '../components/ParticleField'
import LlmSection from './settings/LlmSection'
import HotelSection from './settings/HotelSection'
import VoiceSection from './settings/VoiceSection'
import TasksSection from './settings/TasksSection'
import NotificationsSection from './settings/NotificationsSection'
import MemoriesSection from './settings/MemoriesSection'
import SkillsSection from './settings/SkillsSection'
import MarketSection from './settings/MarketSection'
import TrustSection from './settings/TrustSection'
import McpSection from './settings/McpSection'
import ScenesSection from './settings/ScenesSection'
import PrivacySection from './settings/PrivacySection'

// 控制台设置：纯布局壳；每个功能区块是 pages/settings/ 下的自包含组件（state/加载/交互随区块走）
export default function SettingsPage() {
  return (
    <main className="settings-page">
      <ParticleField />
      <div className="settings-wrap">
        <header className="settings-header">
          <div>
            <p className="section-kicker">SYSTEM CONFIGURATION</p>
            <h1>控制台设置</h1>
          </div>
          <Link className="back-link" to="/">返回聊天</Link>
        </header>

        <LlmSection />

        <HotelSection />

        <VoiceSection />

        <TasksSection />

        <NotificationsSection />

        <MemoriesSection />

        <SkillsSection />

        <MarketSection />

        <TrustSection />

        <McpSection />

        <ScenesSection />

        <PrivacySection />
      </div>
    </main>
  )
}
