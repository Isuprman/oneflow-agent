import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import tseslint from 'typescript-eslint'

// OneFlow 前端 lint —— 把 ARCHITECTURE.md 的落位规则机器化：
// 1) api/ 之外禁止直接 import axios（网络请求必须走 api/ 域文件）
// 2) react-hooks 钩子规则强制；exhaustive-deps 仅告警（语音链路大量依赖最新实现 ref 模式）
// 3) no-explicit-any 关闭：SpeechRecognition 等浏览器 API 不在 lib.dom 类型里，语音栈显式用 any
export default tseslint.config(
  { ignores: ['dist', 'node_modules', 'src.bak-*/**'] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      globals: globals.browser,
    },
    plugins: {
      'react-hooks': reactHooks,
    },
    rules: {
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'warn',
      'no-empty': ['error', { allowEmptyCatch: true }],
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: ['axios'],
              message: '网络请求统一走 src/api/ 域文件（共用 api/http.ts 实例与错误处理）。',
            },
          ],
        },
      ],
      '@typescript-eslint/no-explicit-any': 'off',
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
    },
  },
  {
    // api 层是 axios 的唯一合法使用方
    files: ['src/api/**'],
    rules: {
      'no-restricted-imports': 'off',
    },
  },
)
