// 设置页内置 LLM 提供商与模型列表。
// 前端只负责展示与表单默认值；deepseek 等新增由后端处理，前端只是多一个提供商选项。
export const LLM_PROVIDERS: Record<string, { label: string; models: string[]; defaultBaseUrl?: string }> = {
  openai: { label: 'OpenAI', models: ['gpt-5.6-sol', 'gpt-5.6-luna', 'gpt-5.6-sol-ultrafast'], defaultBaseUrl: '' },
  anthropic: { label: 'Anthropic', models: ['claude-opus-5', 'claude-opus-4.6'], defaultBaseUrl: '' },
  deepseek: { label: 'DeepSeek', models: ['deepseek-v4-pro', 'deepseek-v4-flash'], defaultBaseUrl: 'https://api.deepseek.com' },
  qwen: { label: 'Qwen', models: ['qwen3.8-max', 'qwen3.6-max-preview'], defaultBaseUrl: '' },
}

// 首次进入 / 清空后的默认表单取值
export const DEFAULT_LLM_PROVIDER = 'deepseek'
export const DEFAULT_LLM_MODEL = 'deepseek-v4-flash'
export const DEFAULT_LLM_BASE_URL = 'https://api.deepseek.com'
