# ARCHITECTURE — 代码落位规则

> 给未来的开发者（尤其是 AI 会话）的地图。**加功能前先查这张表，把代码放对地方。**
> 本项目的真实教训：功能只往同一个文件里堆，设置页长到 976 行、调度器塞进 8 种职责、
> 聊天页攒下 29 个 useState——后来花了一整轮重构才拆开。每加一个功能，先问
> 「它属于下面哪个既有模式」；新建一个 100 行的小文件，永远好过给 700 行的大文件再加一段。

## 后端（app/）

| 要加什么 | 放哪 | 模式与约束 |
|---|---|---|
| agent 可调用的新工具 | `tools/<name>.py` | `@tool` 注册进 registry，schema 自动生成；写操作在 registry 标记 `needs_confirmation` |
| 新主动服务（后台定时跑的） | `jobs/<name>.py` + 在 `jobs/__init__.py` 的 REGISTRY 追加一项 | 契约：`{label, hour_gate, async run(db, now)}`。**不改 scheduler.tick**；label 就是失败自报文案，写成人话 |
| agent 内部的新关注点 | 按域拆模块：记忆 `agent/memory_recall.py`、确认 `agent/confirm.py`、委派 `agent/subagent.py` | `engine.run_agent` 只留主循环；拆出时保持 engine 命名空间可导入（测试契约，见下） |
| 新 API 端点 | `routers/<域>.py` | 一个路由文件一个域；在 `main.py` include_router |
| 需要调 LLM 的轻量任务 | `learn/<域>.py`（companion/interview/checkup/habit…） | 每用户配置从 `user_cfg` 取；无 key 必须可静默降级 |
| 新数据表 | `models.py` 追加 | 单文件当前可读（15+ 张表）；模型过 25 张再考虑拆包 |
| 子智能体 | `agent/subagent.py` 的 SUB_AGENTS 或 CustomAgent 表 | delegate 动态路由，工具白名单在 agent 配置里 |

**测试契约（改名前先 grep tests/）**：`app.agent.engine` 的 `run_agent` / `execute` 模块属性、
`_recall_memories` 导出、`app.scheduler` 的 `tick` / `compute_next_run` / `notify_system_error` /
`run_care_rules` / `run_habit_insights`、`scheduler.SessionLocal` 可被 monkeypatch——
这些名字被现有测试直接 import 或 patch，重构时必须保持或同步改测试。

## 前端（frontend/src/）

| 要加什么 | 放哪 | 模式与约束 |
|---|---|---|
| 调后端接口 | `api/<路由名>.ts`（与后端路由一一对应） | 共用 `api/http.ts` 的 axios 实例与 `getErrorMessage`；禁止在组件里裸 fetch |
| 设置页新区块 | `pages/settings/<Name>Section.tsx`，SettingsPage 挂一行 | 自包含：state、数据加载、handlers、专属常量全随区块走；SettingsPage 只做布局 |
| 聊天页新能力 | `hooks/use<域>.ts` | hook 拥有自己的 state 与清理；跨 hook 协作用 ref / 显式回调参数传递，别造全局单例 |
| 语音相关子能力 | `lib/speech/<域>.ts`（wake/asr/local/playback/tone/bridge） | wake 状态机被两条识别通道共享；改唤醒逻辑先读 wake.ts |
| 新页面 | `pages/<Name>Page.tsx` + `App.tsx` 路由 | 页面是装配层：只留 hook 接线、派生值、JSX；逻辑进 hooks/ |

## 通用红线（防再次拥挤）

1. **单文件软上限 ~400 行**：接近就按域拆。判断标准不是行数而是"改一个功能要翻几个互不相关的段落"。
2. **先找模式再写代码**：上表没有的模式，先建模式（目录 + 一个样板文件）再实现，别开先例散装塞。
3. **测试禁止模块级修改全局状态**（`settings.*` 等）：模块级赋值在 pytest 收集阶段就生效，会污染
   整场运行（曾让 test_agent_loop / test_companion 全套跑必败、单跑通过）。需要改全局用
   monkeypatch，且依赖全局前提的用例应在用例内钉住前提。
4. **行为零变化的纯重构**：每步小提交，提交前 `pytest tests/ -q`（后端）/ `npm run build`（前端）
   必须全绿；依靠 258 个测试兜底，发现行为差异立即回退定位。
5. **mock 只许出现在 tests/**：生产代码一律真实 API / 真实数据库（README 既有铁律）。
