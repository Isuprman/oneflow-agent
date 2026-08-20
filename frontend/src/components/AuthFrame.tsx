import type { ReactNode } from 'react'
import AiCore from './AiCore'
import ParticleField from './ParticleField'

export default function AuthFrame({ children }: { children: ReactNode }) {
  return (
    <main className="auth-frame">
      <ParticleField />
      <div className="auth-frame__core"><AiCore compact /></div>
      <section className="auth-panel">{children}</section>
    </main>
  )
}
