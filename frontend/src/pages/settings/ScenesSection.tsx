import { useEffect, useState } from 'react'
import { createScene, deleteScene, listScenes, runScene, toggleScene, type SceneInfo } from '../../api/scenes'
import HudCorners from '../../components/HudCorners'

// 情境剧本：预置指令集，聊天里发「场景 名字」或本页「立即执行」一键顺序跑
export default function ScenesSection() {
  const [scenes, setScenes] = useState<SceneInfo[]>([])
  const [sceneError, setSceneError] = useState('')
  const [sceneName, setSceneName] = useState('')
  const [sceneStepsText, setSceneStepsText] = useState('')
  const [addingScene, setAddingScene] = useState(false)
  const [sceneBusyId, setSceneBusyId] = useState<number | null>(null)
  const [sceneToast, setSceneToast] = useState('')

  useEffect(() => {
    listScenes().then(setScenes).catch((reason: unknown) => setSceneError(reason instanceof Error ? reason.message : String(reason)))
  }, [])

  const showSceneToast = (message: string) => {
    setSceneToast(message)
    window.setTimeout(() => setSceneToast(''), 3000)
  }
  const addScene = async () => {
    setAddingScene(true); setSceneError('')
    try {
      const steps = sceneStepsText.split('\n').map((line) => line.trim()).filter(Boolean)
      const created = await createScene(sceneName.trim(), steps)
      setScenes((previous) => [...previous, created])
      setSceneName(''); setSceneStepsText('')
      showSceneToast(`剧本「${created.name}」已保存（${created.step_count} 步）`)
    } catch (reason) {
      setSceneError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setAddingScene(false)
    }
  }
  const toggleSceneItem = async (item: SceneInfo) => {
    setSceneBusyId(item.id); setSceneError('')
    try {
      const updated = await toggleScene(item.id, !item.enabled)
      setScenes((previous) => previous.map((it) => (it.id === item.id ? updated : it)))
    } catch (reason) {
      setSceneError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setSceneBusyId(null)
    }
  }
  const removeSceneItem = async (item: SceneInfo) => {
    setSceneBusyId(item.id); setSceneError('')
    try {
      await deleteScene(item.id)
      setScenes((previous) => previous.filter((it) => it.id !== item.id))
    } catch (reason) {
      setSceneError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setSceneBusyId(null)
    }
  }
  const executeScene = async (item: SceneInfo) => {
    setSceneBusyId(item.id); setSceneError('')
    try {
      const results = await runScene(item.id)
      const ok = results.filter((result) => result.success).length
      showSceneToast(`「${item.name}」执行完成：${ok}/${results.length} 步成功`)
    } catch (reason) {
      setSceneError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setSceneBusyId(null)
    }
  }

  return (
    <section className="section-card">
      <HudCorners />
      <header className="module-head">
        <div>
          <p className="module-head__kicker">SCENES</p>
          <h2>情境剧本</h2>
        </div>
        <span className={`led ${scenes.some((s) => s.enabled) ? 'is-ready' : ''}`} aria-hidden="true" />
      </header>
      <p className="section-description">预置一串指令，在聊天里发「场景 名字」即可按顺序执行；单步失败不中断后续。</p>

      {sceneError && <p className="error-note" role="alert">{sceneError}</p>}
      {sceneToast && <p className="success-note">{sceneToast}</p>}
      {scenes.length === 0 ? (
        <p className="empty-copy">暂无情境剧本。在下方新建一个试试。</p>
      ) : (
        <ul className="memory-list">
          {scenes.map((item) => (
            <li className="memory-row" key={item.id}>
              <div className="memory-row__copy">
                <p>
                  <strong>{item.name}</strong>{' '}
                  <span className="ledger-hint">{item.step_count} 步</span>
                </p>
                <p>{item.steps[0]}{item.step_count > 1 ? ` …` : ''}</p>
              </div>
              <button
                type="button"
                className={`toggle-chip ${item.enabled ? 'is-on' : ''}`}
                style={{ padding: '4px 10px' }}
                disabled={sceneBusyId === item.id}
                onClick={() => void toggleSceneItem(item)}
              >
                <span className="toggle-chip__state">{item.enabled ? 'ON' : 'OFF'}</span>
              </button>
              <button
                type="button"
                className="outline-button"
                disabled={sceneBusyId === item.id}
                onClick={() => void executeScene(item)}
              >
                立即执行
              </button>
              <button
                type="button"
                className="outline-button"
                disabled={sceneBusyId === item.id}
                onClick={() => void removeSceneItem(item)}
              >
                删除
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="ledger">
        <div className="ledger-field">
          <label htmlFor="scene-name">剧本名</label>
          <input
            id="scene-name"
            value={sceneName}
            onChange={(event) => setSceneName(event.target.value)}
            placeholder="出差 / 晨间准备 ..."
          />
        </div>
        <div className="ledger-field ledger-field--full">
          <label htmlFor="scene-steps">步骤（每行一条指令，最多 10 行）</label>
          <textarea
            id="scene-steps"
            rows={4}
            value={sceneStepsText}
            onChange={(event) => setSceneStepsText(event.target.value)}
            placeholder={'查一下今天的天气\n汇总今天的日程'}
          />
        </div>
      </div>
      <div className="save-bar">
        <button
          className="primary-button"
          disabled={addingScene || !sceneName.trim() || sceneStepsText.split('\n').filter((line) => line.trim()).length === 0}
          onClick={() => void addScene()}
        >
          {addingScene ? '保存中…' : '保存剧本'}
        </button>
      </div>
    </section>
  )
}
