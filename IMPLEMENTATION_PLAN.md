# OneFlow 实施计划 — 长期记忆 + 多智能体编排

版本：v0.1
目标：把 OneFlow 从「会说会调的助手」升级为「有记忆、能编排子 Agent 的真 Agent」。
执行：Hermes 拆票 → codebuddy 逐张实施 → Hermes 逐张验收。全栈覆盖（后端+前端）。

## 范围（本轮做这两个）
### A. 长期记忆（Memory）
- 新表 user_memories：存每用户长期信息（偏好/事实/结论）。
- 新工具 remember(text)：LLM 在对话中判断值得记住的信息时调用（本身就是 function calling，很贴合 Agent 语义）。
- 引擎注入：每次对话开始时把该用户最近的记忆注入 system prompt，让回答带上记忆。
- 接口：GET /api/memories（看记忆）、DELETE /api/memories/{id}（删记忆）。
- 前端：设置页加「记忆」区块，可查看/删除。

### B. 多智能体编排（Multi-Agent）
- 定义 3 个子 Agent，各带受限工具集 + 各自人设：
  | 子Agent | 工具集 | 人设 |
  |---|---|---|
  | life（生活） | schedule_event, list_schedule, get_weather, calculate | 安排日程、查天气、算数 |
  | finance（财务） | add_expense, query_expense, calculate | 记账、查账、算数 |
  | travel（出行） | get_weather, search_hotel, calculate | 查天气、查酒店 |
- 总控 Agent 新增 delegate(agent_name, instruction) 工具：可以派任务给子 Agent；子 Agent 独立
  规划多步调用自己工具后返回结论，总控再汇总成最终回复。
- 子 Agent 复用同一 llm/工具/记忆链路，嵌套循环，步数上限收敛，结果回传给总控。
- 前端无需大改（trace 已通用渲染，能看到 delegate 步骤）。

## 不做（本轮）
- 向量库/语义检索记忆（先用「最近 N 条注入」，轻量）。
- 反思/自我纠错升级、定时主动式、RAG、用户自带工具。

## 分票
- M1（后端记忆）：UserMemory 模型 + remember 工具 + 引擎注入 + memories 接口
- M2（后端多智能体）：subagent 模块 + delegate 工具 + 引擎委派
- M3（前端记忆面板）：设置页加记忆查看/删除

## 验收标准（勾选）
- [ ] 用户说「我喜欢喝咖啡」→ agent 调 remember() 存库
- [ ] 新会话问「我今天想喝什么」→ 回答引用记忆
- [ ] GET/DELETE /api/memories 正常、按用户隔离
- [ ] 总控 delegate：一句话「帮我安排明天 3 点的会和查一下明天天气」→ 触发子 Agent 多步调用并汇总
- [ ] 测试全绿、无 mock（除测试）
- [ ] 前端设置页能看/删记忆
