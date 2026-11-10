# Codex 与 Claude Code：记忆机制的一手证据

核实日期：2026-11-04。本文依据当日实际读取的官方在线文档，研究的是产品原生能力；未安装第三方记忆插件，也未对两个产品运行同一组效果基准。在线文档会继续变化，文中版本号只用于界定某项行为的最低版本，不代表已核实最新安装版本。

本机 `D:/dev/claude-code` 的 origin 是 `Ffffffffire/claude-code`，HEAD 为 `a99de1bb3c0c301b83b784abbcdb7a3674b2cd45`，提交日期 2026-03-31，提交说明为源码快照发布。它不是 Anthropic 官方仓库，本文没有用该快照推定当前产品行为。Codex 本机只发现可执行文件，未发现源码 checkout。

## Codex

**官方确认的机制。** 当前 Codex 有原生本地 Memories，不能只按 `AGENTS.md` 指令文件来描述。总功能默认关闭；开启后，读取已有记忆与允许当前会话贡献新记忆可分别控制，支持全局设置和 `/memories` 会话级选择。会话级选择不改全局设置。本地记忆与 ChatGPT 网页记忆是独立存储及控制面。[Memories](https://learn.chatgpt.com/docs/customization/memories)

生成采用后台处理合格历史会话的方式，会跳过仍活跃或过短的会话；官方另行提供逐会话抽取模型与全局整合模型的配置。配置默认值包括：至少闲置 6 小时、每次启动处理最多 16 个候选会话、仅考虑 30 天内的会话、剩余额度至少 25%，整合保留的近期原始记忆上限为 256。**这些是调度和整合边界，不是每条记忆的可信度。** `max_unused_days=30` 表示多久未使用后不再符合整合资格，不能解释成“30 天自动删除”或“30 天后事实失效”。[配置参考](https://learn.chatgpt.com/docs/config-file/config-reference)

存储位于 Codex home：新 CLI profile 默认选择 `memories_v2/`，已有 `memories/` 时默认沿用 v1；还存在读 v1、同时生成两个存储的迁移配置。官方把这些文件视为生成状态，允许检查，但不建议把手工改文件作为主要管理入口。界面提供开关、输入会话控制和整体清除；生成字段会处理秘密信息，并可配置排除使用过 MCP、网页或工具搜索等外部上下文的会话。[Memories](https://learn.chatgpt.com/docs/customization/memories)、[配置参考](https://learn.chatgpt.com/docs/config-file/config-reference)

官方明确区分用途：`AGENTS.md` 承载持续适用的项目或个人指令，Memories 延续既往工作中的有用上下文，Skills 封装可重复工作流程并按需展开。团队必须执行的规则应保存在版本管理的指令、文档及执行检查中，不能仅依靠回忆命中。`/compact` 则把当前会话较早的内容换成摘要；当前引用文档没有承诺这一动作会直接生成长期记忆。[Customization](https://learn.chatgpt.com/docs/customization/overview)、[Developer commands](https://learn.chatgpt.com/docs/developer-commands)

**尚未从这些官方页确认。** 具体召回排序、向量索引、事实级冲突裁决、逐条来源 schema、版本并发控制，以及把某次用户肯定归因到某条记忆的机制，均未获得足够公开细节。不能据此写成“没有”，也不能假定它们已实现。

**对 iCode 的借鉴判断。** 值得吸收的是独立的读写许可、来源控制、任务空闲与资源预算，而不是直接引入第二套后台抽取模型。若组织轨迹分析需要离线整合，可以采用明确预算和调度门槛；用户日常记忆仍应服从已确定的经济、低干扰写入策略。

## Claude Code

**官方确认的机制。** 当前本地会话的 auto memory 默认开启，模型根据未来会话是否有用决定保存，并非每个会话都写。条目分为 `user`、`feedback`、`project`、`reference`，分别表达用户背景或偏好、纠正或认可的做法、无法从代码推导的项目上下文、外部资料入口。它会避免重复保存代码或既有指令能直接提供的信息。[Auto memory](https://code.claude.com/docs/en/memory#auto-memory)

默认目录是 `~/.claude/projects/<project>/memory/`，同一仓库的 worktree 及子目录共享，仍是机器本地内容。**条目类型为 user，不代表默认跨所有项目共享。** 跨项目个人指令另有 `~/.claude/CLAUDE.md`；组织和团队指令也有独立层级。`MEMORY.md` 提供目录索引，主题文件使用普通文件工具按需读取；界面显示保存、读取记忆的简述，`/memory` 可开关和打开编辑。[Memory](https://code.claude.com/docs/en/memory)

读取预算有真实维护动作：启动只加载索引前 200 行或 25KB，以先达到的限制为准。接近预算时提醒模型精简；超过预算时，**文件写入已经成功**，随后向模型返回要求重写索引的错误，防止尾部长期不可见。官方建议一条入口一行，把详情分离到主题文件，并合并或移除过时入口。这项写入后的反馈从 v2.1.210 起提供；它不是语义冲突已经被可靠解决的证明。[索引超预算错误](https://code.claude.com/docs/en/errors#memory-index-is-over-its-read-limit)

普通历史会话的保留期与记忆寿命分开：清理旧会话的流程排除仍含内容的 auto memory 目录。记忆通过编辑或删除维护；不能把会话清理期限解释成记忆 TTL。[目录与清理](https://code.claude.com/docs/en/claude-directory#cleaned-up-automatically)

压缩会重读磁盘上的 auto memory 与项目根指令；按文件路径生效的规则、子目录指令则重新按需加载。文档确认了**压缩后恢复外部持久内容**，没有确认“压缩摘要自动转为长期条目”。`/context` 能检查实际加载内容。Skills 是可复用知识和流程，主体按需加载，不能把它与自动学习的事实混为同一种记忆。[压缩后保留项](https://code.claude.com/docs/en/context-window#what-survives-compaction)、[扩展机制](https://code.claude.com/docs/en/features-overview)

子代理可另外声明 `memory: user|project|local`，分别对应跨项目个人目录、可版本管理的项目目录、私有项目目录；这是代理自身知识的作用域。普通子代理不加载主会话的 auto memory，fork 继承父上下文是例外。启用持久记忆后，子代理获得相关读取和编辑工具。项目级共享仍需明确发布边界，不能据此认为私人偏好会自动成为组织规则。[子代理持久记忆](https://code.claude.com/docs/en/sub-agents#enable-persistent-memory)

**尚未从这些官方页确认。** 原生向量检索、事实级版本校验、自动冲突仲裁、逐条正负效果归因、完整 dream 流程，不能从可编辑 Markdown 和维护提示推导出来。指令文件仍是模型上下文，硬性阻断操作需要 Hooks 或权限机制。[扩展机制](https://code.claude.com/docs/en/features-overview)

**对 iCode 的借鉴判断。** 最值得吸收的是“短入口、按需详情、预算超限立即反馈”和 reference 类型体现的资料定位能力。对会变的内容，保留重新核实的入口可能比复制旧结论更有用。组织知识与个人偏好应有独立作用域，进入共享目录须经过明确转换，而不是换个保存位置。

## 主报告应保留的判断边界

- 两者都说明记忆、指令、技能、当前会话摘要有不同消费者和生命周期，不能把“有文件”统一评成“有长期个人记忆”。
- 文档可证明接口和已描述行为，不能证明实际召回率、污染率或收益。这里没有给产品打分或声称性能优劣。
- 上述产品没有在本次材料中提供足够的因果效果追踪细节；iCode 的后续方案应将“提供给模型”“模型声明采用”“用户对具体结果纠偏”分开设计，不能把召回次数当作有效证据。
- 对 iCode 的建议属于研究判断，需由主代理与现有代码核对，避免将已经实现的范围、原话核验、候选审核和压缩提交保护重新包装为新设计。
