# OneFlow — 一句话驱动的贾维斯式 AI Agent

任务导向私人 AI 管家：用户用一句自然语言下指令，Agent 自行拆解步骤、多次调用工具（function calling）、
核对结果并汇报，把任务真正执行完毕。核心是「LLM 决策 → 调工具 → 拿结果再决策」的 agent loop。

除了被动应答，OneFlow 还会**主动服务**：定时任务到点自动执行并语音播报、日程临期提醒、
每晚习惯洞察（发现你常做的事并建议沉淀为定时任务）。所有工具用真实 API / 真实数据库，**除测试外禁止 mock**。

## 技术栈
Python 3.12 · FastAPI · SQLite + SQLAlchemy · LiteLLM（多厂商 LLM）· APScheduler（后台调度）·
ddgs + BeautifulSoup（联网）· React 18 + TypeScript + Vite · react-three-fiber（3D 全息核心）· pytest

## 快速开始

```bash
cd ~/work/oneflow-agent
source .venv/bin/activate        # 虚拟环境已建好
# 1. 配置 .env（把你的 LLM 密钥填进去；也可在网页「设置」里每用户自填）
#    LLM_PROVIDER / LLM_MODEL / LLM_API_KEY
# 2. 启动后端（端口 8020，--reload 自动热更）
uvicorn app.main:app --port 8020 --reload
# 3. 启动前端（另开终端）
cd frontend && npm install && npm run dev   # → http://localhost:5178（/api 代理到 8020）
# 4. 验证
curl http://127.0.0.1:8020/api/health
```

打开 http://localhost:5178 注册登录，进「设置」填 LLM 密钥即可对话。

## 贾维斯体验

| 能力 | 说明 |
|---|---|
| 语音唤醒 | 常驻待命，唤醒词「贾维斯 / 小翼 / 你好小助手」，**同音字容错**（加维斯/小艺…也能唤醒），唤醒成功有上行音效 |
| 免唤醒连续对话 | 一次应答/播报结束后进入跟随窗口，直接说下一句即当指令，无需再喊唤醒词 |
| 可打断（barge-in） | 播报期间监听不断：听到**非播报内容**的人声立即掐掉播报、执行你的新指令（回声自动过滤） |
| 真流式 | SSE 实时推送：工具调用进度（`CALL xxx 调用中…`）+ 最终回复逐 token 打字机 |
| 语音播报 | 后端 edge-tts 合成 mp3（免费无 Key），真实播完才恢复监听；失败回退浏览器语音 |
| 主动播报 | 定时任务/日程提醒/习惯洞察 → 前端轮询拉取 → 右上角展示 + 自动语音播报 |
| 晨间简报 | 设置页一键开启：每天到点自动查天气+日程并主动播报（贾维斯式早安） |
| 3D 全息核心 | react-three-fiber 全息 AI 核心：待机呼吸、思考高速自转、**播报时随语音律动发光** |

> 语音识别用浏览器 Web Speech（Chrome 需可达 Google 服务，失败时页面会明确提示并自动关闭待命）。
> 语音识别/播报需真实浏览器并允许麦克风；headless 环境不可用。

## LLM 自选厂商（.env 或网页设置）
| 厂商 | LLM_PROVIDER | LLM_MODEL 示例 | 说明 |
|---|---|---|---|
| OpenAI | openai | gpt-4o-mini | 填你的 OpenAI Key |
| 云端 Qwen（百炼） | openai | qwen/qwen-plus | 兼容模式，LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1 |
| DeepSeek | deepseek | deepseek-chat / deepseek-reasoner | 思考模型已兼容（思维链多轮自动回传） |
| Anthropic | anthropic | claude-… | 填你的 Key |

> LLM 密钥既可在 .env 全局配置，也可在网页「设置」里每用户自填（agent 优先用用户配置）。
> 未填密钥时接口返回明确提示；瞬时错误（网络/限流/5xx）自动重试；调用失败不落库、不污染历史；
> 长会话历史按 token 预算自动裁剪（CONTEXT_BUDGET_CHARS，默认 48000 字符）。

## 内置工具（14 个，真实数据，无 mock）
| 工具 | 数据源 | Key |
|---|---|---|
| get_weather | Open-Meteo | 免费无 Key |
| calculate | ast 标准库安全求值 | 本地 |
| add_expense / query_expense | SQLite 真数据库 | 本地 |
| schedule_event / list_schedule | SQLite 真数据库 | 本地 |
| remember | 长期记忆：记住偏好/事实，跨会话注入 | SQLite 真库 |
| search_hotel | 用户自填 URL+Key | 需用户配置 |
| delegate | 多智能体编排：委派 生活/财务/出行 子 Agent（均可联网） | 内置 |
| create/list/cancel_scheduled_task | 定时任务：到点自动跑 agent 并主动播报 | 本地 |
| web_search | DuckDuckGo 联网搜索 | 免费无 Key |
| read_webpage | 网页正文提取（去噪+截断） | 免费 |

## 后台调度（APScheduler）
- **30s 轮询**：到期定时任务在用户「定时播报」会话里自动跑一遍 agent（可自己调工具）→ 产出通知
- **日程提醒**：日程开始前 5 分钟自动推送提醒（防重复）
- **习惯学习**：每晚 21 点后统计近 7 天工具使用，高频行为（≥3 次）主动建议沉淀为定时任务，每人每天最多一次
- 一次性任务跑完自动停用；周期任务自动推进到下一次；服务重启即自愈

## 接口一览
| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/auth/register · /login | 注册 / 登录（JWT） |
| GET | /api/auth/me | 当前用户 |
| POST | /api/chat | 发指令 → {reply, steps, trace} |
| POST | /api/chat/stream | SSE 真流式：step（工具进度）/ delta（正文增量）/ error / done |
| GET/POST/DELETE | /api/conversations… | 会话管理 / 消息 / 轨迹 |
| GET | /api/notifications?unread= | 主动通知（定时播报/日程提醒/习惯洞察） |
| POST | /api/notifications/{id}/read | 标记已读 |
| GET/PUT | /api/briefing | 晨间简报开关与时间 |
| GET/PUT | /api/settings/llm · /hotel | 每用户 LLM / 订酒店配置 |
| POST | /api/tts | edge-tts 语音合成 → audio/mpeg |
| GET/DELETE | /api/memories… | 长期记忆查看/删除 |
| GET | /api/health | 健康检查 |

## 测试
```bash
.venv/bin/python -m pytest tests/ -q   # 111 个用例全绿（仅测试允许 mock）
```
覆盖：agent loop / 真流式 SSE / 错误不落库 / 上下文裁剪 / 思维链回传 / 调度引擎（下次执行计算、
到期执行、日程提醒防重复）/ 定时任务工具 / 晨间简报 / 习惯洞察 / 通知路由 / 联网工具 / 各工具与鉴权。

## 验收状态
- ✅ P0 后端：登录鉴权 · agent loop 多步工具调用 · 真实工具 · 无 mock
- ✅ 多智能体编排：delegate 委派生活/财务/出行子 Agent，汇总回报
- ✅ 长期记忆：remember 工具 + 自动注入 + 设置页管理
- ✅ 贾维斯语音：常驻待命（同音字容错唤醒）· 免唤醒连续对话 · 可打断（barge-in + 回声过滤）· edge-tts 播报 · 唤醒音效
- ✅ 真流式 SSE：工具进度 + 逐 token 回复；错误处理（瞬时重试、失败不落库）；历史按预算裁剪
- ✅ 主动服务：定时任务到点跑 agent 播报 · 日程临期提醒 · 晨间简报一键开启 · 每晚习惯洞察
- ✅ 联网能力：web_search + read_webpage，子 Agent 均可用
- ✅ DeepSeek 思考模型兼容（reasoning_content 多轮回传 + 落库）
- ✅ 3D 全息前端：全息核心随播报律动 · 深空 HUD · 打字机/动效 · 功能全保留
- ⏭ 下一步可选：拍照/截图记账（多模态）· 自定义子智能体 · 语义记忆召回（向量）· 浏览器推送通知 · RAG · Telegram 入口 · Docker
