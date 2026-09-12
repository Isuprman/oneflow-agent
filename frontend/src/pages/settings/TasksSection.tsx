import { useEffect, useState } from 'react'
import { deleteTask, listTasks, updateTask } from '../../api/tasks'
import type { TaskInfo } from '../../api/types'
import HudCorners from '../../components/HudCorners'
import { formatTime } from './shared'

const WEEKDAY_LABELS = ['', '周一', '周二', '周三', '周四', '周五', '周六', '周日']

// 定时任务管理（晨间简报在语音区块有专属开关，此处不重复展示）
export default function TasksSection() {
  const [tasks, setTasks] = useState<TaskInfo[]>([])
  const [taskError, setTaskError] = useState('')

  useEffect(() => {
    listTasks().then(setTasks).catch((reason: unknown) => setTaskError(reason instanceof Error ? reason.message : String(reason)))
  }, [])

  const toggleTask = async (task: TaskInfo) => {
    setTaskError('')
    try {
      const updated = await updateTask(task.id, { enabled: !task.enabled })
      setTasks((previous) => previous.map((item) => (item.id === task.id ? updated : item)))
    } catch (reason) {
      setTaskError(reason instanceof Error ? reason.message : String(reason))
    }
  }
  const removeTask = async (task: TaskInfo) => {
    setTaskError('')
    try {
      await deleteTask(task.id)
      setTasks((previous) => previous.filter((item) => item.id !== task.id))
    } catch (reason) {
      setTaskError(reason instanceof Error ? reason.message : String(reason))
    }
  }

  return (
    <section className="section-card">
      <HudCorners />
      <header className="module-head">
        <div>
          <p className="module-head__kicker">SCHEDULED TASKS</p>
          <h2>定时任务</h2>
        </div>
        <span className={`led ${tasks.some((task) => task.enabled) ? 'is-ready' : ''}`} aria-hidden="true" />
      </header>
      <p className="section-description">到点后自动执行并主动播报的任务；也可以直接对贾维斯说“取消某某任务”。</p>

      {taskError && <p className="error-note" role="alert">{taskError}</p>}
      {tasks.length === 0 ? (
        <p className="empty-copy">暂无定时任务。试着对贾维斯说：“每天晚上9点提醒我喝水”。</p>
      ) : (
        <div className="toggle-list">
          {tasks.map((task) => (
            <div key={task.id} className="toggle-chip">
              <span className="toggle-chip__body">
                <span className="toggle-chip__label">{task.title}</span>
                <span className="toggle-chip__desc">
                  {task.kind_label}
                  {task.kind === 'weekly' && task.weekday ? ` ${WEEKDAY_LABELS[task.weekday]}` : ''}
                  {` ${String(task.hour).padStart(2, '0')}:${String(task.minute).padStart(2, '0')}`}
                  {task.next_run_at ? ` · 下次：${formatTime(task.next_run_at)}` : ' · 已停用'}
                </span>
              </span>
              <button
                type="button"
                className={`toggle-chip ${task.enabled ? 'is-on' : ''}`}
                style={{ padding: '4px 10px' }}
                onClick={() => void toggleTask(task)}
              >
                <span className="toggle-chip__state">{task.enabled ? 'ON' : 'OFF'}</span>
              </button>
              <button type="button" className="outline-button" onClick={() => void removeTask(task)}>删除</button>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}
