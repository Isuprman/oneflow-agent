// OneFlow 桌面端 — Electron 主进程
// 职责：拉起 FastAPI 后端 → 等待健康检查 → 打开窗口加载应用；托盘常驻；本地 ASR IPC。
const { app, BrowserWindow, Tray, Menu, nativeImage, ipcMain, shell } = require('electron')
const { spawn } = require('child_process')
const http = require('http')
const path = require('path')
const fs = require('fs')

const PROJECT_ROOT = path.join(__dirname, '..')
const BACKEND_PORT = 8020
const APP_URL = `http://localhost:${BACKEND_PORT}`

// 音频完全解锁：WebAudio/Audio 播放无需用户手势（贾维斯的声音不能被浏览器策略卡住）
app.commandLine.appendSwitch('autoplay-policy', 'no-user-gesture-required')

let mainWindow = null
let tray = null
let backendProcess = null
let quitting = false

const asr = require('./asr')

// ---------- 后端管理 ----------

function startBackend() {
  const python = path.join(PROJECT_ROOT, '.venv', 'bin', 'uvicorn')
  if (!fs.existsSync(python)) {
    console.error('[desktop] 找不到 .venv/bin/uvicorn，请先在项目根目录建好虚拟环境')
    return
  }
  backendProcess = spawn(python, ['app.main:app', '--port', String(BACKEND_PORT)], {
    cwd: PROJECT_ROOT,
    env: { ...process.env },
    stdio: 'inherit',
  })
  backendProcess.on('exit', (code) => {
    console.log(`[desktop] 后端退出 code=${code}`)
    if (!quitting) {
      // 意外退出：3 秒后自愈重启
      setTimeout(startBackend, 3000)
    }
  })
}

function waitForBackend(timeoutMs = 30000) {
  const startedAt = Date.now()
  return new Promise((resolve) => {
    const probe = () => {
      const req = http.get(`${APP_URL}/api/health`, (res) => {
        res.resume()
        if (res.statusCode === 200) return resolve(true)
        retry()
      })
      req.on('error', retry)
      req.setTimeout(1500, () => { req.destroy(); retry() })
    }
    const retry = () => {
      if (Date.now() - startedAt > timeoutMs) return resolve(false)
      setTimeout(probe, 500)
    }
    probe()
  })
}

// ---------- 窗口与托盘 ----------

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 900,
    minHeight: 600,
    title: 'OneFlow',
    backgroundColor: '#0F1420',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  })

  mainWindow.loadURL(APP_URL)

  // 关闭即收进托盘（贾维斯常驻）；真正退出走托盘菜单
  mainWindow.on('close', (event) => {
    if (!quitting) {
      event.preventDefault()
      mainWindow.hide()
    }
  })
}

function createTray() {
  const iconPath = path.join(__dirname, 'icon.png')
  if (!fs.existsSync(iconPath)) return
  const icon = nativeImage.createFromPath(iconPath).resize({ width: 18, height: 18 })
  tray = new Tray(icon)
  tray.setToolTip('OneFlow — 贾维斯')
  tray.setContextMenu(
    Menu.buildFromTemplate([
      {
        label: '打开 OneFlow',
        click: () => {
          if (mainWindow) {
            mainWindow.show()
            mainWindow.focus()
          }
        },
      },
      { type: 'separator' },
      {
        label: '退出',
        click: () => {
          quitting = true
          app.quit()
        },
      },
    ]),
  )
  tray.on('click', () => {
    if (mainWindow) {
      mainWindow.show()
      mainWindow.focus()
    }
  })
}

// ---------- 本地 ASR IPC ----------

ipcMain.on('asr:available', (event) => {
  event.returnValue = asr.modelsReady()
})

ipcMain.on('asr:start', (event) => {
  const ok = asr.start((payload) => {
    if (!event.sender.isDestroyed()) event.sender.send('asr:event', payload)
  })
  console.log(`[desktop] 本地语音引擎启动${ok ? '成功' : '失败'}`)
  if (!ok && !event.sender.isDestroyed()) {
    event.sender.send('asr:event', { type: 'error', text: '本地语音引擎启动失败' })
  }
})

ipcMain.on('asr:stop', () => {
  asr.stop()
})

// 渲染进程送来 Int16 PCM → 转 Float32 喂引擎
ipcMain.on('asr:audio', (_event, samplesInt16) => {
  if (!samplesInt16) return
  const int16 = samplesInt16 instanceof Int16Array ? samplesInt16 : new Int16Array(samplesInt16)
  const float32 = new Float32Array(int16.length)
  for (let i = 0; i < int16.length; i++) float32[i] = int16[i] / 32768.0
  asr.feed(float32)
})

// 语音链路决策日志（唤醒命中/派发/丢弃），排查语音交互问题的第一手证据
ipcMain.on('asr:log', (_event, message) => {
  console.log(`[voice] ${message}`)
})

// ---------- 生命周期 ----------

app.whenReady().then(async () => {
  startBackend()
  const ok = await waitForBackend()
  if (!ok) console.error('[desktop] 后端启动超时，窗口仍将打开（可等待自愈重启）')
  createWindow()
  createTray()
})

app.on('window-all-closed', () => {
  // macOS 习惯：不退出，托盘常驻
})

app.on('before-quit', () => {
  quitting = true
  asr.stop()
  if (backendProcess) {
    backendProcess.kill('SIGTERM')
    backendProcess = null
  }
})
