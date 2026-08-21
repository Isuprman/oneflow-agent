// OneFlow 桌面端本地语音引擎 — sherpa-onnx-node 流式中文识别（原生绑定，M1 NEON 加速）
// 职责：接收渲染进程的 16kHz PCM → 流式解码 → 推送 partial/final 事件。
// 断句用引擎内置端点检测（isEndpoint），比能量 VAD 更准；另加单句时长上限兜底。
const fs = require('fs')
const path = require('path')

const MODELS_DIR = path.join(__dirname, 'models', 'sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20')

const MAX_UTTERANCE_MS = 20000 // 单句最长时长兜底，防端点检测不触发时卡死

let sherpa = null
let recognizer = null
let stream = null
let running = false
let emit = () => {}

let lastText = ''
let utteranceMs = 0

function _pick(...candidates) {
  for (const file of candidates) {
    if (fs.existsSync(path.join(MODELS_DIR, file))) return path.join(MODELS_DIR, file)
  }
  return null
}

function modelPaths() {
  // int8 优先（更小更快），缺失时回退非量化版
  const encoder = _pick('encoder-epoch-99-avg-1.int8.onnx', 'encoder-epoch-99-avg-1.onnx')
  const decoder = _pick('decoder-epoch-99-avg-1.onnx')
  const joiner = _pick('joiner-epoch-99-avg-1.int8.onnx', 'joiner-epoch-99-avg-1.onnx')
  const tokens = _pick('tokens.txt')
  if (!encoder || !decoder || !joiner || !tokens) return null
  return { encoder, decoder, joiner, tokens }
}

function modelsReady() {
  return modelPaths() !== null
}

function initRecognizer() {
  if (recognizer) return true
  const paths = modelPaths()
  if (!paths) return false
  try {
    sherpa = require('sherpa-onnx-node')
    recognizer = new sherpa.OnlineRecognizer({
      featConfig: { sampleRate: 16000, featureDim: 80 },
      modelConfig: {
        transducer: {
          encoder: paths.encoder,
          decoder: paths.decoder,
          joiner: paths.joiner,
        },
        tokens: paths.tokens,
        numThreads: 2,
        provider: 'cpu',
      },
      decodingMethod: 'greedy_search',
      maxActivePaths: 4,
      // 内置端点检测：静音 0.8s 即断句（比默认更灵敏，指令场景响应快）
      enableEndpoint: true,
      rule1MinTrailingSilence: 1.2,
      rule2MinTrailingSilence: 0.8,
      rule3MinUtteranceLength: 20,
    })
    return true
  } catch (e) {
    console.error('[asr] 初始化失败:', e)
    recognizer = null
    return false
  }
}

function resetStream() {
  if (stream && recognizer) {
    try { recognizer.reset(stream) } catch { /* 忽略 */ }
  }
  lastText = ''
  utteranceMs = 0
}

/** 启动识别管线；emitFn 接收 {type:'partial'|'final'|'error', text} 事件。
 *  返回 true=就绪；false=模型/引擎不可用（已通过 error 事件告知原因）。 */
function start(emitFn) {
  emit = emitFn || (() => {})
  if (!initRecognizer()) {
    emit({ type: 'error', text: '本地语音模型未就绪，请先运行 npm run models 下载' })
    return false
  }
  if (!stream) stream = recognizer.createStream()
  resetStream()
  running = true
  return true
}

function stop() {
  running = false
}

/** 喂入一帧 16kHz Float32 音频（渲染进程已重采样）。 */
function feed(samplesFloat32) {
  if (!running || !stream || !recognizer) return
  utteranceMs += (samplesFloat32.length / 16000) * 1000

  stream.acceptWaveform({ sampleRate: 16000, samples: samplesFloat32 })
  while (recognizer.isReady(stream)) {
    recognizer.decode(stream)
  }

  const isEndpoint = recognizer.isEndpoint(stream)
  const text = (recognizer.getResult(stream).text || '').replace(/\s+/g, '').trim()

  if (text && text !== lastText) {
    lastText = text
    emit({ type: 'partial', text })
  }

  // 断句：引擎端点检测命中，或单句超长兜底
  if ((isEndpoint || utteranceMs >= MAX_UTTERANCE_MS) && lastText) {
    const finalText = lastText
    resetStream()
    emit({ type: 'final', text: finalText })
  } else if (isEndpoint) {
    resetStream()
  }
}

module.exports = { start, stop, feed, modelsReady }
