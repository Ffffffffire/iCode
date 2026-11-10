# Hermes Agent 与 Pi：记忆机制核验

核验日期：2026-11-04。用途：供 iCode 个性化记忆横向比较与方案决策使用；这是源码和官方文档调研，不是实际运行、质量评测或延迟基准。

Hermes 公开主分支核验版本为 [`9302ba9e212c63ba24cdf1f47f26b47bcd3b042e`](https://github.com/NousResearch/hermes-agent/commit/9302ba9e212c63ba24cdf1f47f26b47bcd3b042e)，提交时间 2026-11-03 23:28:59 UTC。本地 `D:/dev/hermes-agent` 的 remote 指向同一官方仓库，但 HEAD 为 `99ad2d1372d3b5ff9134e9d8930fed6de4fc7b62`，提交时间 2026-05-11，不能代表当前实现；本轮未修改该 checkout。

Pi 当前官方仓库已为 `earendil-works/pi`，包名为 `@earendil-works/pi-coding-agent`；旧 `badlogic/pi-mono` API 会重定向。核验版本为 [`676af1d777ef6f04b6bc8daf4cf3b9b1799cff4d`](https://github.com/earendil-works/pi/commit/676af1d777ef6f04b6bc8daf4cf3b9b1799cff4d)，提交时间 2026-11-03 22:56:31 UTC。[当前官方 README](https://github.com/earendil-works/pi/blob/676af1d777ef6f04b6bc8daf4cf3b9b1799cff4d/packages/coding-agent/README.md)

## Hermes Agent

- **原生边界｜代码确认。** `MEMORY.md` 保存常驻事实，`USER.md` 保存用户画像，默认容量分别为 2,200、1,375 字符。会话开始冻结到 system prompt，工具写盘不在同一会话逐次改写该前缀。当前工具提示要求只记跨任务成立的事实，将任务相关流程、偏好和纠正转入 skill。这是“小型常驻画像 + 按任务加载技能”的选择，不能直接等同于 iCode 的条件化偏好检索。[工具](https://github.com/NousResearch/hermes-agent/blob/9302ba9e212c63ba24cdf1f47f26b47bcd3b042e/tools/memory_tool.py#L373) · [容量与存储](https://github.com/NousResearch/hermes-agent/blob/9302ba9e212c63ba24cdf1f47f26b47bcd3b042e/tools/memory_tool_store.py#L188)
- **写入与纠偏｜代码确认。** `memory` 暴露 add/patch/remove；精确重复不新增，不是语义去重。patch 只替换唯一匹配片段；整条 replace 已从模型接口移除，防止模型误删同条其他事实。批量操作按最终容量校验，文件锁内重读后原子写入。后台复盘的 patch/remove 即使关闭一般审批也须暂存；审批绑定原目标全文，目标已变则拒绝，避免旧判断覆盖新修正。[存储实现](https://github.com/NousResearch/hermes-agent/blob/9302ba9e212c63ba24cdf1f47f26b47bcd3b042e/tools/memory_tool_store.py#L350) · [后台门控与批准重放](https://github.com/NousResearch/hermes-agent/blob/9302ba9e212c63ba24cdf1f47f26b47bcd3b042e/tools/memory_tool.py#L179)
- **历史检索｜代码确认。** `session_search` 用 SQLite FTS5 返回原始消息，无额外 LLM 摘要。按会话谱系去重、自动任务降权、子代理和集成会话隐藏；默认充分展开第一项，其余保留锚点，可继续定位阅读。源码明确指出重复 cron 词汇会淹没用户真实历史；这是检索来源治理，不是增加一种相似度就能替代。[搜索实现](https://github.com/NousResearch/hermes-agent/blob/9302ba9e212c63ba24cdf1f47f26b47bcd3b042e/tools/session_search_tool.py#L1)
- **压缩联动｜代码确认。** 外部 provider 有 `on_pre_compress`、真实会话结束及切换钩子。压缩 checkpoint v2 提供规范化 user/assistant 原始证据，排除既有压缩摘要、系统消息和工具行；严格 checkpoint 要求 provider 声明支持，否则拒绝，不能把旧的 best-effort hook 当作可靠落盘保证。这是接口契约，不代表内置两份 Markdown 自动执行语义提炼。[provider 契约](https://github.com/NousResearch/hermes-agent/blob/9302ba9e212c63ba24cdf1f47f26b47bcd3b042e/agent/memory_provider.py#L35) · [证据筛选与调用](https://github.com/NousResearch/hermes-agent/blob/9302ba9e212c63ba24cdf1f47f26b47bcd3b042e/agent/conversation_compression.py#L1819)
- **自动成本与感知｜文档确认。** 还有回合后 background review，默认使用主模型；可以独立禁用，仍保留手动 `/refine`，并限制累计输入 token、记录独立用量。通知可关闭、简述或展开变更；关闭通知不等于关闭提炼。本项目用户已经拒绝频繁额外提炼，因此应借鉴批准与回执，不照搬后台复盘。[官方记忆文档](https://hermes-agent.nousresearch.com/docs/user-guide/features/memory#controlling-memory-writes-write_approval)
- **扩展和组织边界｜文档、代码确认。** 只允许一个外部 memory provider 与内置存储并存；语义检索、用户建模等能力依 provider，不能全部记作原生能力。profile 绑定要求独立实例、路径、租户和调用身份；多用户共享会话还需逐回合作者身份。隔离不等于组织知识审批和提升治理，后者本轮未确认。[provider 文档](https://hermes-agent.nousresearch.com/docs/user-guide/features/memory-providers) · [身份契约](https://github.com/NousResearch/hermes-agent/blob/9302ba9e212c63ba24cdf1f47f26b47bcd3b042e/agent/memory_provider.py#L84)

**证据分歧：** 当前官方记忆文档仍将“已完成工作日记”列为可保存内容，而上述当前工具 schema 明确要求跳过 completed-work logs，任务经验进入技能。报告应保留此差异，以实际工具提示描述运行指导，不能拼接成一套无矛盾策略。[文档](https://hermes-agent.nousresearch.com/docs/user-guide/features/memory) · [工具 schema](https://github.com/NousResearch/hermes-agent/blob/9302ba9e212c63ba24cdf1f47f26b47bcd3b042e/tools/memory_tool.py#L384)。`RecallStatus` 契约要求只报告最近一次实际注入，避免沿用旧计数；这证明的是提供了什么，未证明模型采用正确或记忆产生正效益。[召回状态契约](https://github.com/NousResearch/hermes-agent/blob/9302ba9e212c63ba24cdf1f47f26b47bcd3b042e/agent/memory_provider.py#L146)

## Pi coding agent

- **原生边界｜代码、文档确认。** 当前核心工具为 read/bash/powershell/edit/write/grep/find/ls，没有原生 memory 工具。官方核心资料提供上下文文件、技能、持久会话、压缩和扩展接口；本轮未发现原生的个人记忆抽取、冲突合并、遗忘或跨会话语义库。用户与项目的 `AGENTS.md` 等文件是指令加载，不能直接标成自动学习个人记忆。[核心工具注册](https://github.com/earendil-works/pi/blob/676af1d777ef6f04b6bc8daf4cf3b9b1799cff4d/packages/coding-agent/src/core/tools/index.ts) · [配置与上下文文件](https://github.com/earendil-works/pi/blob/676af1d777ef6f04b6bc8daf4cf3b9b1799cff4d/packages/coding-agent/docs/configuration.md)
- **短期连续性｜文档确认。** JSONL 保存会话树，模型读取当前分支。压缩在原记录之外追加 summary 和保留边界，下一请求使用摘要加近期消息；原始消息仍在。分支切换可以产生分支摘要。这是任务上下文维护，既没有把所有摘要自动升级为个人事实，也没有给长期个人库定义条目容量或淘汰策略。[会话语义](https://github.com/earendil-works/pi/blob/676af1d777ef6f04b6bc8daf4cf3b9b1799cff4d/packages/coding-agent/docs/sessions.md) · [压缩](https://github.com/earendil-works/pi/blob/676af1d777ef6f04b6bc8daf4cf3b9b1799cff4d/packages/coding-agent/docs/compaction.md)
- **可移植的联动点｜文档确认。** `session_before_compact` 可取消或提供摘要；`session_compact` 携带已经保存的压缩条目；取消、失败另有 `session_compact_failed`。这支持扩展在压缩成功后发布候选、失败时不发布，避免把“开始生成摘要”误当成“摘要已提交”。自定义摘要可传 usage 纳入会话用量，联动成本可以观察。[扩展事件](https://github.com/earendil-works/pi/blob/676af1d777ef6f04b6bc8daf4cf3b9b1799cff4d/packages/coding-agent/docs/extensions.md#session_before_compact--session_compact)
- **状态与界面分离｜文档确认。** 工具 `content` 供模型消费，`details` 可保留界面与状态数据；`appendEntry()` 配合 `registerEntryRenderer()` 持久呈现 TUI 内容而不送入模型。状态恢复要求使用 `getBranch()`，不能扫描所有分支把已放弃的选择拼成同一历史。这对 iCode 记忆工具摘要、展开依据和回滚后的记忆归属比另建一套对话记录更有参考价值。[扩展状态与渲染](https://github.com/earendil-works/pi/blob/676af1d777ef6f04b6bc8daf4cf3b9b1799cff4d/packages/coding-agent/docs/extensions.md#state-management)
- **个人与组织｜支持性推论。** 仓库级指令、技能及包可以团队复用；不能由此推断具备个人证据向组织结论提升、权限继承、审批或撤销传播。若采用 Pi 扩展路线，长期记忆的所有者、使用范围、检索算法和生命周期由扩展承担，原生宿主提供事件和 UI 边界。[资源配置](https://github.com/earendil-works/pi/blob/676af1d777ef6f04b6bc8daf4cf3b9b1799cff4d/packages/coding-agent/docs/configuration.md) · [官方定位](https://github.com/earendil-works/pi/blob/676af1d777ef6f04b6bc8daf4cf3b9b1799cff4d/packages/coding-agent/README.md)

生态边界：Pi 包目录里的 `pi-compact` 介绍了用户确认的事实、模型候选、按需历史查询及成功压缩后提交记录，但它属于第三方扩展，仅能说明这些接口有具体使用者，不能计入 Pi 原生能力；本轮未安装或运行，也未将 `pi-hermes-memory` 归入 Pi 原生。[Pi 官方包目录所载扩展说明](https://pi.dev/packages/pi-compact?name=pi-coding-agent)

## 对 iCode 决策的影响

以下是基于上述证据的设计判断，尚不是本地实现差距或完成状态的断言：

1. **先治理证据与作用域，再堆检索通道。** 召回失败可能来自自动生成记录挤占、压缩副本重复、错误分支和错误所有者。索引应能区分用户原话、摘要、助手推断和实际引用关系；重复加工不能增加独立证据量。少量全局画像和较多条件化经验应使用不同的读取预算。
2. **合并应是可检查的修改事务。** 借鉴唯一定位、局部修订、版本或原文前置条件、整批最终容量检查；避免为了省容量整条覆盖，或者旧候选覆盖用户新更正。先保证改对对象、保留仍成立的条件，再讨论自动语义合并。
3. **压缩产物是候选的入口，原始证据才是依据。** 保留 iCode 复用现有压缩调用的路线；候选关联原话与来源分支，确认压缩提交后再发布，失败不留下成功回执。不要通过反复读取上一轮摘要“确认”同一事实，也不要增加每回合后台模型复盘。
4. **用户感知与模型输入分别预算。** TUI 可以持续保留保存、候选、提供给模型、纠偏等事实，模型只收到与当前任务相关的最小记忆。UI 不应把“已注入”显示成“已采用”或“有效”；负面反馈要能落到具体条目和版本。
5. **组织扩展先定义提升边界。** 用户个人偏好不因放入共享后端而变成组织知识。未来组织候选需要有共同适用条件、证据来源、明确批准者及撤销方式；保留接口与身份隔离即可，不必现在引入多 provider 或独立知识图谱。

本轮仅研究公开文档与公开源码。没有运行 Hermes/Pi，也没有完成真实个人记忆场景的横向测试，不能据此声称任一方案召回更准、效果更好或延迟更低。官方文档可变化，关键实现链接均固定到本轮读取的提交。
