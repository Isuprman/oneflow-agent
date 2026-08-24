// 打包前置：把本机项目绝对路径写入 project-root.json（gitignore），供打包后的 .app 定位后端
const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..', '..')
const distIndex = path.join(root, 'frontend', 'dist', 'index.html')
if (!fs.existsSync(distIndex)) {
  console.error('[prebuild] frontend/dist 不存在，请先在 frontend/ 执行 npm run build')
  process.exit(1)
}
fs.writeFileSync(
  path.join(__dirname, '..', 'project-root.json'),
  JSON.stringify({ root }, null, 2) + '\n',
)
console.log('[prebuild] project-root.json ->', root)
