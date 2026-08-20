# OneFlow — 一句话驱动的自动化工作流 Agent

技术需求文档（TRD）
版本：v0.1
状态：草稿待评审
基于：PRD v0.1

---

## 1. 项目概述

OneFlow 是一个**任务导向的 AI Agent**：用户用一句自然语言下指令，Agent 自行拆解步骤、
多次调用工具、核对结果并汇报，把任务真正执行完毕。

- 核心：**LLM 决策 → function calling 执行 → 拿结果再决策** 的 agent loop。
- ASR / TTS 仅为可选语音壳（云 API），MVP 阶段可不含。
- 全云端：LLM / ASR / TTS 均为云服务，本地不跑模型。
- 所有工具基于真实数据与真实 API，**除测试外禁止任何 mock**（含订酒店）。

### 1.1 关键需求约束（来自 PRD 评审确认）
1. **LLM 厂商由用户自选**（可配置切换，不写死某一家）。
2. 记账 / 日程 / 订单数据用**真数据库**（SQLite）。
3. **除测试外禁止 mock 数据**：所有工具调真实 API / 真实库，未配置则明确报错，绝不伪造结果。

---

## 2. 开发环境与前置条件

### 2.1 本机开发环境（已审计）
| 项 | 版本 / 值 |
|---|---|
| 硬件 | Apple Silicon (arm64)，8 GB RAM |
| Python | 3.12.13 → `/opt/homebrew/bin/python3.12`（推荐用此建 venv） |
| SQLite | 3.43.2 |
| Node | v26.3.1 |
| Docker | 29.3.1 |
| 运行模式 | 开发在本机，模型 / 语音全走云端 API |

### 2.2 前置条件（首次搭建命令）
```bash
# 1. 建项目目录（已存在）
cd ~/work/oneflow-agent

# 2. 建 Python 3.12 虚拟环境
/opt/homebrew/bin/python3.12 -m venv .venv
source .venv/bin/activate

# 3. 安装依赖（见 requirements.txt，安装时锁定版本）
pip install --upgrade pip
pip install -r requirements.txt

# 4. 准备环境变量文件
cp .env.example .env   # 填入 LLM Provider / Model / API Key
```

### 2.3 云端服务与 Key 策略（原则：优先免费无 Key，需 Key 的由用户自填）
**总原则**：
1. 能免 Key 就免——工具优先接免费无 Key 的真实数据源。
2. 确实需要 Key 的（LLM 必填，订酒店 / 增强语音可选）→ 由**用户自行填写**（全局 `.env` 或每用户设置）。
3. 未填 Key 的工具调用返回**明确配置错误**，绝不返回伪造数据、绝不 mock。

| 组件 | 免费无 Key？ | 用户需填什么 | 说明 |
|---|---|---|---|
| LLM（必填） | 否 | `LLM_PROVIDER` / `LLM_MODEL` / `LLM_API_KEY` | 用户自选厂商并填自己的 Key |
| 天气 get_weather | ✅ 是（Open-Meteo） | 无 | 免费真实数据，无 Key |
| 计算 calculate | ✅ 是（ast 标准库） | 无 | 本地安全求值 |
| 记账 / 日程 | ✅ 是（本地 SQLite） | 无 | 真数据库，无需外部 Key |
| 订酒店 search_hotel | 否（真实酒店 API） | `HOTEL_API_KEY` / `HOTEL_BASE_URL`（可选） | 用户自填真实API；未填报错 |
| 语音 ASR（P1） | ✅ 优先浏览器 Web Speech API | 无 | 客户端免费无 Key |
| 语音 TTS（P1） | ✅ 优先 edge-tts / 浏览器 | 无 | 免费无 Key；亦支持用户自填的云 TTS |

> 未配置 Key 的云端服务，工具调用返回**明确配置错误**，绝不返回伪造数据、绝不 mock。

---

## 3. 技术选型

| 组件 | 选型 | 版本 | 理由 |
|---|---|---|---|
| 语言 | Python | 3.12 | 生态最好，Agent 库齐全 |
| Web 框架 | FastAPI + Uvicorn | fastapi>=0.115, uvicorn>=0.30 | 异步、自动 OpenAPI、上手快 |
| LLM 多厂商 | **LiteLLM** | litellm>=1.49 | 统一 OpenAI/Anthropic/Qwen 等，满足"用户自选厂商" |
| DB 访问 | SQLAlchemy 2.0 | sqlalchemy>=2.0 | ORM + 原生 SQL 都支持 |
| 数据库 | SQLite | 3.43（系统自带） | 轻量、零部署，满足 MVP 数据需求 |
| 配置 | pydantic-settings + .env | pydantic>=2 | 类型安全读配置 |
| 天气工具 | Open-Meteo API | — | 免费无 Key、真实数据 |
| 计算工具 | 标准库 ast | — | 安全表达式求值，无第三方 |
| 订酒店工具 | 真实酒店搜索 API | P1 | 用户自填 Key；免费替代源优先，未配报错 |
| 测试 | pytest + httpx | pytest>=8 | 唯一允许 mock 的地方 |
| （可选）语音 | 浏览器 Web Speech / edge-tts 优先 | P1 | 免费无 Key；亦支持用户自填的云 ASR/TTS |

**LLM 厂商自选设计**：LiteLLM 通过 `provider` + `model` + `api_key` 配置切换，
实际请求统一走 OpenAI 兼容 function-calling 格式，LiteLLM 负责归一化各家差异。
Key 全部由用户自行填写（`.env` 或每用户设置）。

**Key 总原则（贯穿全项目）**：能免 Key 就免；需 Key 的用户自填；未填则工具明确报错，绝不 mock。

---

## 4. 系统架构

```
用户 ──(文字 / 云ASR)──> FastAPI 入口
                          │
                          v
                ┌─────────────────────────┐
                │       Agent Engine      │
                │   LiteLLM (云端 LLM)     │◄── OpenAI / Anthropic / Qwen ...
                │  · 理解意图 / 拆解步骤    │
                │  · 决策调哪个工具         │
                │  · 循环直到完成/熔断      │
                └───────────┬─────────────┘
                            │ 工具调用意图(JSON schema)
                            v
                  Tool Registry (工具注册表)
                  · 入参校验 → 执行 → 返回结果
                  │
        ┌─────────┼──────────────┬──────────────┐
        v         v              v              v
   Open-Meteo   SQLite(SQLA)   SQLite(SQLA)   真实酒店 API
   (天气)        (记账)         (日程)         (Amadeus)
                                           
                        工具调用轨迹 ──> tool_calls_log 表
```

### 4.1 数据流（一次对话）
1. 用户发一条消息 → 存 `messages`。
2. Agent Engine 把会话历史 + 工具 schema 发给云端 LLM。
3. LLM 返回：`tool_call`（要调某工具 + 参数）或直接回答。
4. 若是 `tool_call`：Tool Registry 校验入参 → 调真实 API/库 → 把结果回喂 LLM → 回到步骤 2，并把该次调用写入 `tool_calls_log`。
5. 若直接回答：作为最终回复存库并返回；达到 `max_steps`（默认 15）强制终止并汇报。

---

## 5. 功能模块详设

### 5.1 模块划分
```
oneflow/
├── app/
│   ├── main.py            # FastAPI 入口
│   ├── config.py          # .env 配置(provider/model/api_key 等)
│   ├── db.py              # SQLAlchemy engine / session
│   ├── models.py          # ORM 模型
│   ├── schemas.py         # Pydantic 请求/响应模型
│   ├── agent/
│   │   ├── engine.py      # agent loop 核心
│   │   ├── llm.py         # LiteLLM 封装 (tool calling 归一化)   ← 难点
│   │   └── prompts.py     # system prompt
│   ├── tools/
│   │   ├── registry.py    # 工具注册表 + 分发器             ← 难点
│   │   ├── weather.py     # get_weather → Open-Meteo(真实)
│   │   ├── expense.py     # add/query_expense → SQLite(真实)
│   │   ├── schedule.py    # schedule/list_schedule → SQLite(真实)
│   │   ├── calculator.py  # calculate → ast 安全求值(真实)
│   │   └── hotel.py       # search_hotel → 真实酒店 API(真实,未配报错)
│   └── routers/chat.py    # /api/chat 路由
└── tests/                 # 唯一允许 mock
```

### 5.2 Agent Engine（agent loop）伪代码
```python
async def run_agent(session: Session, conv_id: int, user_msg: str):
    # 1. 存用户消息
    add_message(session, conv_id, "user", user_msg)

    steps = 0
    while steps < config.max_steps:
        steps += 1
        # 2. 组装历史 + 工具 schema，调云端 LLM
        reply = await llm.chat_with_tools(history, tools=registry.schemas())
        # 3. 若 LLM 要求调工具
        if reply.tool_call:
            # 4. 校验入参 → 执行真实工具 → 记录轨迹
            result = registry.execute(reply.tool_call)
            log_tool_call(session, conv_id, reply.tool_call, result)
            # 5. 把工具结果回喂 LLM，继续循环
            history.append(tool_result_message(result))
            continue
        # 6. 直接回答 → 存库返回
        add_message(session, conv_id, "assistant", reply.text)
        return reply.text

    # 熔断：超步数
    msg = f"任务步骤过多({config.max_steps})，已终止。请把任务拆细一点。"
    add_message(session, conv_id, "assistant", msg)
    return msg
```

### 5.3 LLM 封装（多厂商归一化，难点）伪代码
```python
# llm.py — 用 LiteLLM 归一化各家 function calling
from litellm import acompletion
# config: provider=openai|anthropic|qwen|zhipu...  model=...  api_key=...
async def chat_with_tools(history, tools):
    resp = await acompletion(
        model=config.model,          # 例如 openai/gpt-4o-mini 或 anthropic/claude-...
        messages=history,
        tools=tools,                 # OpenAI 兼容 tool schema
        tool_choice="auto",
        api_key=config.api_key,
    )
    # LiteLLM 自动把各家 tool_call 归一化成统一结构
    msg = resp.choices[0].message
    if msg.tool_calls:
        tc = msg.tool_calls[0]
        return ToolReply(tool_call=ToolCall(name=tc.function.name,
                                            arguments=json.loads(tc.function.arguments)))
    return ToolReply(text=msg.content)
```
> 说明：LiteLLM 在同一 `model` 字段里用 `厂商/模型名` 标识，从而"用户自选 LLM 厂商"。

---

## 6. 数据库设计（SQLite，SQLAlchemy DDL）

```sql
-- 用户
CREATE TABLE users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 会话
CREATE TABLE conversations (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title      TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 消息
CREATE TABLE messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL,                -- user / assistant / tool
    content         TEXT,
    tool_call       TEXT,                         -- 触发工具时的 JSON（如有）
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 工具调用轨迹（审计 / 演示 / 回放）
CREATE TABLE tool_calls_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    tool_name       TEXT NOT NULL,
    arguments       TEXT,                         -- JSON
    result          TEXT,                         -- JSON
    success         INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 账目（真实业务数据）
CREATE TABLE expenses (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    amount     REAL NOT NULL,
    category   TEXT,
    note       TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 日程（真实业务数据）
CREATE TABLE schedules (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title      TEXT NOT NULL,
    start_at   TEXT NOT NULL,
    end_at     TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

配置表可选：`settings(key TEXT PRIMARY KEY, value TEXT)`，用于存每个用户的 LLM 偏好。

索引：`expenses(user_id, created_at)`、`schedules(user_id, start_at)`、
`messages(conversation_id)`、`tool_calls_log(conversation_id)`。

---

## 7. API 设计

Base URL：`http://127.0.0.1:8000`

### 7.1 健康检查
`GET /api/health`
```json
200 { "status": "ok", "llm_provider": "openai", "llm_model": "gpt-4o-mini" }
```

### 7.2 聊天（核心）
`POST /api/chat`
```json
// 请求
{ "conversation_id": 3, "user_id": 1, "message": "帮我查明天北京天气，下雨就记一笔带伞的账" }
// 响应
{
  "conversation_id": 3,
  "reply": "明天北京小雨，已为你记了一笔'提醒带伞'的账。",
  "steps": 3,
  "trace": [ {"tool":"get_weather","args":{...},"result":{...}},
             {"tool":"add_expense","args":{...},"result":{...}} ]
}
```
- `conversation_id` 为空则新建会话。
- `trace` 为该次 agent loop 的工具调用轨迹（演示/审计用）。

### 7.3 会话管理
```
GET  /api/conversations?user_id=1           # 会话列表
GET  /api/conversations/{id}/messages       # 会话消息
GET  /api/conversations/{id}/trace          # 会话工具调用轨迹
POST /api/conversations                     # 建会话
DELETE /api/conversations/{id}              # 删会话
```

### 7.4 用户（MVP 简化）
```
POST /api/users            # 注册 {username, password} -> {id}
POST /api/auth/login       # 登录 -> {token}
```

### 7.5 业务查询（可选，供前端直接看数据）
```
GET /api/expenses?user_id=1
GET /api/schedules?user_id=1
```

---

## 8. 项目目录结构

```
~/work/oneflow-agent/
├── .env.example                # 配置模板（不提交真实 key）
├── .gitignore
├── requirements.txt
├── README.md
├── TRD.md                      # 本文档
├── PRD.md                      # 产品文档
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI 入口 + 路由挂载
│   ├── config.py               # pydantic-settings 读 .env
│   ├── db.py                   # SQLAlchemy engine/session + 建表
│   ├── models.py               # ORM 模型
│   ├── schemas.py              # Pydantic schemas
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── engine.py           # agent loop
│   │   ├── llm.py              # LiteLLM 封装
│   │   └── prompts.py          # system prompt
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── registry.py         # 工具注册表 + 分发
│   │   ├── weather.py
│   │   ├── expense.py
│   │   ├── schedule.py
│   │   ├── calculator.py
│   │   └── hotel.py
│   └── routers/
│       ├── __init__.py
│       └── chat.py             # /api/chat + 会话
└── tests/
    ├── test_weather.py
    ├── test_expense.py
    ├── test_calculator.py
    ├── test_registry.py        # 允许 mock 的地方
    └── test_agent_loop.py
```

---

## 9. MVP 最小可行版本（P0）

**目标**：文字输入一条指令 → Agent 自由规划 → 连续调真实工具完成 → 汇报 + 轨迹。

MVP 范围（2–3 天）：
1. FastAPI 骨架 + `GET /api/health`。
2. SQLite 建表（users/conv/messages/tool_calls_log/expenses/schedules）。
3. Tool Registry + 4 个真实工具：天气(Open-Meteo)、记账(add/query → SQLite)、
   日程(schedule/list → SQLite)、计算(ast)。
4. LiteLLM 多厂商封装 + agent loop（含 max_steps 熔断 + 失败重试回喂）。
5. `POST /api/chat` 返回 `reply + trace`。
6. 测试覆盖（允许 mock 的仅限测试代码）。

**MVP 不含**：订酒店真实 API（P1）、语音 ASR/TTS（P1）、Web 前端（P2）、
用户登录鉴权完整版（MVP 先用 `user_id` 简化）。

---

## 10. 分阶段实施计划

### P0 — MVP（2–3 天）
- Day 1：项目骨架 + 数据库 + 配置 + /api/health。
- Day 2：Tool Registry + 天气/记账/日程/计算 4 工具（真实）。
- Day 3：LiteLLM 封装 + agent loop + /api/chat + trace + 测试。
- 交付：CLI/API 一句多步指令跑通，含 agent loop 轨迹打印。

### P1 — 订酒店 + 语音 + 会话完整化（3–5 天）
- 订酒店：接入真实酒店搜索 API（Amadeus 免费层），未配 Key 则明确报错。
- 语音：接云 ASR（指令入口）+ 云 TTS（回答出口）。
- 用户登录鉴权 + 会话彻底按用户隔离 + 追问。

### P2 — 进阶（可选）
- Web 前端界面。
- 流式 + 打断（barge-in，WebRTC/SSE）。
- Docker 部署 + 更多真实行业工具。

---

## 11. 部署方案

### 11.1 本地开发启动
```bash
cd ~/work/oneflow-agent
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
# 验证
curl http://127.0.0.1:8000/api/health
```

### 11.2 环境变量（.env）
```env
# LLM（用户自选厂商，三选一填）
LLM_PROVIDER=openai            # openai | anthropic | qwen | zhipu | ...
LLM_MODEL=gpt-4o-mini          # 或 claude-... / qwen-... 与 provider 对应
LLM_API_KEY=sk-xxxx

# 订酒店真实 API（P1，可选；不填则工具明确报错，绝不 mock）
HOTEL_API_KEY=
HOTEL_BASE_URL=

# 语音（P1，可选。默认免费无 Key：ASR 用浏览器 Web Speech，TTS 用 edge-tts）
# 若想用其它云 ASR/TTS，自行填写下面几项（用户自填 Key）
ASR_PROVIDER=            # 留空 = 用免费无 Key 的浏览器 Web Speech
ASR_API_KEY=
TTS_PROVIDER=            # 留空 = 用免费无 Key 的 edge-tts
TTS_API_KEY=

# Agent
MAX_STEPS=15
DB_PATH=./oneflow.db
```

### 11.3 云端部署（P2，Docker）
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY app/ ./app/
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```
```bash
docker build -t oneflow .
docker run -d --env-file .env -p 8000:8000 -v $(pwd)/data:/app/data oneflow
```

---

## 12. 关键难点与解决方案

### 难点 1：多厂商 LLM 的 function calling 差异
不同厂商工具调用格式不统一（OpenAI `tool_calls`、Anthropic `tool_use`、百度/Qwen 各有差异）。
解决：统一走 **LiteLLM**，它把各家工具调用归一化为 OpenAI 兼容结构；业务代码只面对一种格式。
切换厂商只需改 `LLM_PROVIDER` / `LLM_MODEL`，代码零改动。

### 难点 2：安全表达式求值（calculate）
`eval()` 直接执行有注入风险。
解决：用 `ast` 解析成 AST，白名单允许 `BinOp/Num/UnaryOp`，其他节点一律拒绝：
```python
import ast, operator as op
_ops = {ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul,
        ast.Div: op.truediv, ast.Pow: op.pow, ast.USub: op.neg}
def safe_eval(expr: str):
    tree = ast.parse(expr, mode="eval").body
    def _eval(node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.BinOp):
            return _ops[type(node.op)](_eval(node.left), _eval(node.right))
        if isinstance(node, ast.UnaryOp):
            return _ops[type(node.op)](_eval(node.operand))
        raise ValueError("不支持的表达式")
    return _eval(tree)
```

### 难点 3：工具调用失败与重试，避免死循环
工具可能因参数错误 / 云端 5xx / Key 未配而失败。
解决：
- 错误文本**回喂 LLM**，让它改参数或换方案重试。
- `MAX_STEPS` 熔断，超限强制终止并汇报。
- Tool Registry 统一 try/except，返回结构化 `{success:false, error}`，
  与成功的 `{success:true, ...}` 结构一致，便于 LLM 理解。

### 难点 4：工具 schema 与实现分离，热插拔
每加一个工具要同时维护"schema 声明"与"执行函数"，容易不一致。
解决：用**装饰器式注册表**，schema 与函数写在一起：
```python
# registry.py
_REGISTRY = {}
def tool(name, description, parameters: dict):
    def deco(fn):
        _REGISTRY[name] = {"fn": fn, "description": description, "parameters": parameters}
        return fn
    return deco

def schemas():  # 生成供 LLM 的 tools list
    return [{"type":"function","function":{...}} for ...]
def execute(name, args):  # 分发执行 + 结果包装
    ...
```

### 难点 5：保证"无 mock"（真实数据红线）
误解风险：工具误用占位/假数据，违背需求。
解决：
- 每个工具只允许两种出口：真实 API 返回，或真实 DB 查询。
- 依赖外部 Key 的工具若未配置，返回**明确配置错误**（`该功能未配置 HOTEL_API_KEY`），
  **绝不**返回编造结果。
- pytest 中才允许用 mock 替换外部 API（唯一豁免）。

---

## 13. 验收标准

### P0 验收（可勾选）
- [ ] `pip install -r requirements.txt` 后 `uvicorn app.main:app` 能起，`/api/health` 返回 `ok` 与当前 provider/model。
- [ ] 一句话能连续调用 **≥2 个真实工具**完成任务（如"查明天北京天气，下雨就记一笔账"）。
- [ ] `get_weather` 返回 Open-Meteo 真实数据（非伪造）。
- [ ] `add_expense` / `query_expense` 写入并读取 SQLite 真实数据。
- [ ] `schedule_event` / `list_schedule` 写入并读取 SQLite 真实数据。
- [ ] `calculate` 能算，且传入危险表达式（如 `__import__('os')`）被拒绝。
- [ ] 工具失败能回喂重试；`MAX_STEPS` 熔断生效，不无限循环。
- [ ] `POST /api/chat` 返回 `reply` + `trace`，trace 含每次工具调用参数与结果。
- [ ] 无任何 mock 数据出现在 `app/` 生产代码中（仅在 `tests/`）。
- [ ] 切一个 LLM 厂商（如 openai→qwen）只改 `.env` 即可，代码零改动。

### P1 验收
- [ ] `search_hotel` 调真实酒店 API；未配 `HOTEL_API_KEY` 时返回明确配置错误，不造假。
- [ ] 语音指令进入 agent 流程：默认走免费无 Key 的浏览器 Web Speech（ASR）+ edge-tts（TTS）即可跑通；亦支持用户自填的云 ASR/TTS。
- [ ] 会话按用户隔离，支持连续追问。

---

## 14. 开放问题（待确认）
1. 订酒店真实 API 具体接哪家（优先找免费 / 无 Key 的真实源；确实要 Key 的由用户自填，TRD 先按可配置 `HOTEL_API_KEY`/`HOTEL_BASE_URL` 设计，如你有渠道请告知）。
2. MVP 阶段用户鉴权做到什么程度（先用 `user_id` 简化，P1 再上完整登录？）。
3. 天气用 Open-Meteo（免费无 Key）是否可接受——按你的原则它已是最优免费源，建议保留。
