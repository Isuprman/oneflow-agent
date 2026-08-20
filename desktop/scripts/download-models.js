// 下载本地语音识别模型（sherpa-onnx 流式中英双语 zipformer，约 100MB）
// 用法：cd desktop && npm run models
const fs = require('fs')
const path = require('path')
const https = require('https')
const { execSync } = require('child_process')

const MODEL_NAME = 'sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20'
const URL = `https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/${MODEL_NAME}.tar.bz2`
const MODELS_DIR = path.join(__dirname, '..', 'models')
const ARCHIVE = path.join(MODELS_DIR, `${MODEL_NAME}.tar.bz2`)

function download(url, dest) {
  return new Promise((resolve, reject) => {
    const file = fs.createWriteStream(dest)
    const get = (u) => {
      https.get(u, { headers: { 'User-Agent': 'OneFlow' } }, (res) => {
        // GitHub releases 302 到 CDN
        if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
          res.resume()
          return get(res.headers.location)
        }
        if (res.statusCode !== 200) {
          res.resume()
          return reject(new Error(`下载失败 HTTP ${res.statusCode}`))
        }
        const total = Number(res.headers['content-length'] || 0)
        let received = 0
        res.on('data', (chunk) => {
          received += chunk.length
          if (total) process.stdout.write(`\r下载中 ${(received / 1048576).toFixed(1)} / ${(total / 1048576).toFixed(1)} MB`)
        })
        res.pipe(file)
        file.on('finish', () => { file.close(); console.log('\n下载完成'); resolve() })
      }).on('error', (e) => { fs.unlink(dest, () => {}); reject(e) })
    }
    get(url)
  })
}

async function main() {
  const targetDir = path.join(MODELS_DIR, MODEL_NAME)
  if (fs.existsSync(path.join(targetDir, 'tokens.txt'))) {
    console.log('模型已存在，跳过下载：', targetDir)
    return
  }
  fs.mkdirSync(MODELS_DIR, { recursive: true })
  console.log('开始下载模型（约 100MB，请保持网络畅通）...')
  await download(URL, ARCHIVE)
  console.log('解压中...')
  execSync(`tar xjf "${ARCHIVE}" -C "${MODELS_DIR}"`, { stdio: 'inherit' })
  fs.unlinkSync(ARCHIVE)
  console.log('完成：', targetDir)
}

main().catch((e) => {
  console.error('模型下载失败：', e.message)
  console.error('可手动下载并解压到 desktop/models/：', URL)
  process.exit(1)
})
