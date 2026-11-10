# iCode TUI 原生设计语言规范

提炼自当前工作区（Textual 8.2.7、Dracula 基调主题）的成熟原生界面：设置屏、Agent 配置屏、会话浏览、Guides、聊天工具卡、chrome 与侧栏。用途：**新增或评审 TUI 界面/组件前，先对照本规范与第 16 节的参考索引复用既有模式**。文中行号以 2026-11-05 工作区为准，会随后续提交漂移，以规则本身为准。

一个前提判断：原生界面"精细感"不是来自某个单点技巧，而是来自**一套被到处一致执行的隐性语法**。用户看到的每一处输入框、每一条分隔符、每一个状态色都落在预期位置，视觉噪音因此极低。新界面偏离任何一条，破坏的不是那一处，而是整屏的一致性预期——这就是"感觉不如原生"的来源。

## 1. 设计原则（因果，不是口号）

1. **档位纪律**：每种视觉手段（底色、边框、文字色）只有全局固定的几档透明度，同一种"语法"处处一致。字段底色永远是 8%→12%，不存在某屏用 5% 的自由。
2. **递归层级**：容器嵌套时边框强度单调递减，层级不需要读者推断。
3. **语义色落点**：彩色只表达状态，落在边框、图标、前缀上；默认 chrome 整体压灰，彩色稀缺所以有效。
4. **装饰克制**：每行 ≤1–2 个字形，标题不带图标，emoji 仅限 Buddy 人格化区域。
5. **按信息量降级**：折叠行是读得成句的散文，单调用显示句子、多调用才退化计数；窄行协商时失败/中断信息永远保位。

## 2. 色彩与档位

调色板根（`app/tui/theme.py:38-46`）：primary `#AF87FF`（紫）、secondary `#5F5FAF`、warning `#FFAF5F`、error `#FF5F5F`、success `#5FFF87`、accent `#FF87D7`（粉）、foreground `#EEEEEE`；background/surface/panel/boost 全部 `#1C1C1C`。chrome 默认压灰（`theme.py:364-372`：border `#5F5F5F`、工具组标题 `#949494`）。

边框别名体系（`theme.py:208-239`）：`$tui-border-primary/-secondary/-success/-error/-warning/-accent/-foreground` 直接映射语义槽位；`$tui-border-neutral-gray`；`$tui-border-primary-darken-2/-3` 用于更暗一档的内框；`$tui-border-title-primary/-accent/-warning` 用于标题。全局 `border-opacity: 80%`。

**$foreground 透明度档位表**（唯一合法值）：

| 档位 | 用途 | 例 |
|---|---|---|
| 4% | 输入区底（最弱） | input_bar.py:890 |
| 5% | 卡片底 | config_card.py:38 |
| 6% | checkbox 底 | settings.tcss:97-105 |
| 8% | **字段静息底（全局字段语法）** | settings.tcss:115-149 |
| 12% | 字段聚焦底 | 同上 |
| 15% | 分区边框 / selector-label 底 | settings.tcss:52-54 |
| 25% | 禁用文字 | — |
| 35% | checkbox 关态标记 | settings.tcss:97 |
| 50% | locked / 未设值 | status_bar.py |
| 60% | ANSI Tab | chrys.tcss:266-280 |
| 75% | Tab 默认 | 同上 |
| 90% | label 文字 | — |

彩色档位：`$primary` 15%（光标行）/18%（TOC 光标）/25%（活动 Tab）/28%（聚焦）/30%（建议 hover）/40%（链接 hover）；`$accent` 20%（tag 底）；`$warning` 10/12/15% 三档。**新界面不得发明档位表以外的值。**

**复合色进入 Rich 的唯一通道**：`auto 60%` 这类值直接喂 Rich 会静默丢样式。必须走组件类 + `get_component_rich_style()`（参照 `tool_call.py::ToolCardHeader._zone_style`：取 full style 后 `without_color + Style.from_color(full.color)`），或纯色用 `rich_style_from_textual_color`（`util/rich_style.py`）。

## 3. 容器与边框递归

五级递归，强度单调递减：

```
L1 模态外框   border: round $tui-border-primary $border-opacity;
              border-title-color: $tui-border-title-primary; border-title-style: bold;
              background: $surface; padding: 0                 (settings.tcss:13-16)
L2 分区       border: round $tui-border-foreground 15%;
              border-title-color: $secondary; border-title-style: bold   (settings.tcss:52-54)
L3 卡片       background: $foreground 5%; border: solid $tui-border-foreground 15%;
              padding: 1 2                                  (config_card.py:38-41)
L4 卡内小节   border: solid $tui-border-foreground 15%; border-title-color: $text-muted  (mcp.py:418-424)
L5 内嵌列表盒 border: round $tui-border-primary-darken-3 $border-opacity     (tasks.py:101)
```

分隔线：分区竖线 `border-right: solid $tui-border-foreground 15%`，主分栏更强 45%（guides/screen.tcss:28），横向 `border-top: solid … 15%`（sessions/screen.tcss:59）。遮罩统一 `background: $background 40%`。

模态尺寸惯例：settings 92%/85%（max-height 48）、agents/models 95%/85%（60）、sessions 85%/80%、guides 94%/90%。侧栏面板 `width: 30%; min-width: 42; max-width: 60`（sidebar/panel.py:61-64）。

## 4. 布局骨架

- **设置行模式**（表单行的事实标准，`settings/rows.py:173-179` + settings.tcss:70-75/194-210）：`Horizontal` = label 定宽 **32** + 控件 `1fr max-width 44` + badges；说明文字独立成 hint 行，`└─` 前缀列宽 3、色 `$text-disabled`，hint 本体 `$text-muted`、出错换 `$error`。区块 `margin: 1 1 0 0`、行 `margin: 0 0 1 0`——"一行一空行"节奏。
- **双栏模式**（agents config.py:284-333）：左 OptionList `width 28` 无边框 `padding: 0 0 0 1`，右 `1fr` TabbedContent，底部 `dock: bottom; height: 3` 按钮行（左对齐动作 + `1fr` spacer + 右侧 Save/Close）。
- **表格模态**（sessions）：顶部过滤细线 + DataTable + 底部高 3 搜索框（round accent）。
- **窄屏适配**：每个屏在宽 < 阈值（通常 72 列）挂 `-compact` 类改纵向布局；侧栏有正常/紧凑两套文案（详见第 10 节）。

## 5. 控件语法

- **字段（输入/选择）**：`border: none; background: $foreground 8%`，聚焦 `12%`。这是全局唯一的输入控件外观，压平为 `height: 1`；多行 TextArea 例外，保留 round 边框 + border_title 当标签。
- **Select**：SelectCurrent 压平同字段语法；SelectOverlay `round` 边框、`max-height: 8~9`；选项文本必须包 `Text(...)` 防 profile 名被解析为 markup（rows.py:388-391）。
- **Checkbox**：关 `color: $foreground 35%`、开 `color: $success`，底均 6%（六处 tcss 完全一致，可照抄）。
- **按钮三型**：标准（透明底、hover `$block-hover-background`）；链接式（`background: $primary 20%; color: $primary; text-style: none`，hover 40%，settings.tcss:155-176）；删除 `✕`（`variant="error"`、透明底、`min-width: 3`，config_card.py:82-90）。
- **Tabs**：默认 `$foreground 75%`、活动 `background: $primary 25% + bold`；ANSI 降级 60%/40%；下划线 bar 两态都钉 `$foreground 15%` 防闪烁（chrys.tcss:266-292）。
- **微交互**：hover/背景变化加 `transition: background 150ms linear`（chrys.tcss:540-542）。

## 6. 列表模式

- **双行制条目**（agents config.py:432-449，列表项的事实标准）：`Content.assemble((f"{prefix}{label}", "bold"), (f"\n{description}", "dim"))`；当前项前缀 `"◦ "`；组间插入 None 分隔项。
- 勾选列若存在必须**常驻**（未激活时用空格占位），否则首次标记会造成整列位移。
- 状态前缀点族：`●` 运行 / `◦` 暗态（hooks.py、background_tasks.py）。
- 匹配高亮：命中词 `$warning` + `reverse=True`；仅为上下文出现的行 `stylize("italic")`（sessions/screen.py:440-449）。
- 滚动纪律：`scrollbar-size: 1 1` + 内容可滚时 `scrollbar-gutter: stable`（防行横移）；列表容器无边框。
- 选中态沿用 OptionList 默认 block-cursor 配色，不自绘。

## 7. 空态与加载

- **空态**：`HatchedEmptyState`——满宽 `╲` 影线（`$hatch-color` = foreground 15%）+ 居中带衬空格标签（`" No saved sessions. "`），height 5，标签 `$text-muted` 且按宽度适配（hatch.py）。侧栏空态用居中 `SidebarEmptyStateLabel`。
- **加载**：`ChrysLoadingIndicator`（5 个渐变 `●` 点，`$primary`，居中）；动画关闭时退化为本地化 "Loading..."。
- **运行态不额外占空**：折叠行用闪烁点 + 扫光带替代箭头，等待行用呼吸点（`·→•→●`），全部有静态降级。

## 8. 状态色与徽章

- **工具卡状态边框**（语义色=边框色的范式，tool_call.py:1320-1347）：运行 `round $tui-border-primary 50%` / 成功 `success 30%` / 失败 `error 50%` / 拒绝 `warning 50%`，边框色与标题色联动切换。
- **border_title / border_subtitle 双轨元数据**：参数摘要进 title（截 120），状态/时长/分辨率进右对齐 subtitle（tool_call.py:1389-1401）。
- **徽章语法**（chrys.tcss:156-217）：实底徽章 `$primary` 底 + 按钮前景色粗体；语义按模式换色——manual `$primary` / auto `$warning` / bypass `$error`；计数徽章 `$warning`、>0 才显示。
- **彩色标签**：`background: $accent 20%; color: $accent; bold`，**hover 一律反转为 `$foreground` 底 + `$background` 字**（chrys.tcss:167-211、status_bar.py:254-283）。
- **警示条**：`color: $warning; background: $warning 15%`（config.tcss:152-159）。
- 状态闪现：`-warn` = warning 色 + 15% 底、`-error` = error 色、`-caution` = warning 无底。

## 9. 排版纪律

- 分隔符**全局唯一** `" · "`（半角点两侧空格）。不引入 `|`、`—`、` / ` 混用。
- 时长/时间统一降级：`120ms → 45s → 2m 5s → 1h 4m → 1d 4h`（tool_call.py:506-522）；同屏不得出现多种时间粒度（ISO 全串、`[:10]`、`[:19]` 混用是反例）。
- 截断：动态适配宽度用 `…`（含路径中切保文件名），固定预算用 `...`。
- 字重/样式语义：bold = 区块标题（$secondary）/工具名/活动 Tab；dim = 标签、hint、描述、元信息；italic 仅辅助信息（占位、未设值、非匹配行）；大写只用于应用级徽章。继承 unwanted bold 时显式 `text-style: not bold`。
- **折叠行是散文**："Read src/app.py" 而非 "read: 1 file"；单调用显示句子，多调用才计数，计数用 `$text-warning`、失败 `$text-error`（single_call_row.py、fold_rows.py）。

## 10. 图标体系

- **纯 Unicode 几何/文本符号，零 emoji**（唯一例外：Buddy 人格区 `✨`/`🔇`）。
- 状态：`✓` 成功 `✗` 失败 `✕` 删除钮 `■` 取消 `○` 结束 `◌` 排队 `⊘` 阻塞 `→` 分离 `↻` 重试 `╌` 跳过。
- 折叠：`▸/▾` 折叠行、`▶/▼` 卡片；翻页 `›`（page_navigator）。
- 结构：树形 hint `└─`、空态影线 `╲`、footer 静息 `⠿`、spinner `⠋⠙⠹…`（动画关→静态 `●`）。
- **密度规则**：每行 ≤1–2 个字形（行首状态图标/箭头）；标题、区块名、头部不带图标；设置整屏仅两枚。
- **成对规则**：同类并列入口要么都有字形、要么都没有（`▤ Notes n` 配 `◇ Review n`，不允许一个有一个没有）；开关用点族 `●/○`，不用 emoji 🔔。

## 11. 动效

Braille spinner 全局共享（`util/spinner.py`）；扫光带 2s 过境余弦衰减、呼吸点 1.2s（shimmer.py）；hover 背景 `transition 150ms`。所有动画必须有"动画关闭"静态降级（终端能力/用户偏好）。

## 12. 文本安全（强制）

动态文本（系统、profile、模型、工具、用户、文件、记忆标题）一律 `Text(...)` / `Content.from_text(..., markup=False)` / `Static(markup=False)` / `notify(..., markup=False)`；外部文本过 `sanitize_legacy_block/scalar` 或 `sanitize_source_text`；确需拼进 markup 模板时先 `escape()`。裸 `str` 进 notify/label 是注入面（`list[int]` 会渲染成 `list`，`[/x]` 直接抛 MarkupError）。

## 13. 工程红线（性能与结构，摘要自 AGENTS.md TUI 节）

- App 级样式更新/recompose/relayout 是 O(挂载转录) 成本：焦点切换、overlay 开关、小面板切换不得触发 MainScreen restyle；setter 幂等、值不变不发事件。
- 隐藏用 `display: False/True`，不用 `-hidden` 类/visibility；常驻 chrome 用 `set_widget(s)_visibility_without_layout`。
- 高频更新 label：固定宽 + `update(..., layout=False)`；流式正文限频渲染。
- 滚动容器内先 `await remove` 再 `mount`，包 `app.batch_update()` 防 `scroll_y` 钳 0。
- `call_later/call_after_refresh` 返回 False 表示被拒，需释放挂起状态；`prevent()` 不得跨 `await`（用 `messages_disabled`）。
- 可取消任务路径的 widget 移除必须走 `remove_shielded`。
- Screen `CSS` 有作用域、`CSS_PATH` 没有；`DEFAULT_CSS` 不以定义类名开头的规则只匹配后代。
- 常驻 widget 的周期定时器 Hide 时 `pause()`、Show 时 `resume()`。
- 新增任何 restyle/recompose 路径需要带转录量的性能回归测试。

## 14. 反例清单（评审时逐条对照）

1. 同一列并存多种"块"定义（margin / thick 左边框 / 裸 Collapsible）——一列只允许一种分区语言。
2. 发明档位表以外的透明度（如字段用 5%）。
3. emoji 与几何符号混用、字形不成对、上下文错配的徽章文案复用（为 20 列徽章设计的文案拼进屏内正文）。
4. placeholder-only 表单（填值后字段语义消失）；错误提示远离触发点或随滚动消失。
5. 同屏多种时间粒度、一行两种分隔符。
6. 页签计数不对称（只有某个页签带数字）。
7. 勾选列后出现造成整列位移；提示文字只在不再需要时出现。
8. 列表项单行标题、无元信息（混合视图无法分辨状态）。
9. 指示器/徽章无语义色分层（错误态与空闲态同色）。
10. 聊天流内给工具行加高调装饰（原生意图是安静；要统一就把侧栏调低，不是把聊天流调高）。

## 15. 新界面检查清单

1. 外框是否 `round $tui-border-primary $border-opacity` + `$surface` 底 + 粗体 title？
2. 字段是否全部 `border: none` + `$foreground 8%→12%`？
3. 分区是否用 `border_title`（$secondary/$text-muted 粗体）而非 Static 大标题？一列是否只有一种块语言？
4. 动态文本是否全部 `Text/markup=False`？外部文本是否 sanitize？
5. 状态色是否落在边框/图标/前缀而非整片背景？语义映射是否与第 8 节一致？
6. 分隔符是否只有 ` · `？时间是否走统一降级函数？
7. 图标是否纯 Unicode、≤2/行、成对、标题无图标？
8. 空态是否 HatchedEmptyState？加载是否 ChrysLoadingIndicator？
9. 窄屏 `-compact` 是否处理？徽章文案是否在可用宽度内不被截断？
10. 是否触发了 App 级 restyle/recompose？高频更新是否限频/`layout=False`？

## 16. 参考索引（抄哪里）

| 要抄什么 | 去哪里 |
|---|---|
| 模态外壳/分区递归/字段语法/checkbox/链接按钮/hint 树 | `screens/settings/`（settings.tcss + rows.py） |
| 双栏列表+详情/双行列表项/底部按钮行 | `screens/agents/config.py + config.tcss` |
| 表格模态/命中高亮/italic 过滤 | `screens/sessions/` |
| 状态边框系统/border_title 双轨/复合色进 Rich | `widgets/chat/tool_call.py`（ToolCardHeader） |
| 折叠行散文/窄行协商/计数 | `widgets/chat/fold_rows.py + single_call_row.py` |
| 卡片（可折叠）/删除钮 | `widgets/sidebar/config_card.py` |
| 空态/加载/扫光/呼吸点 | `widgets/…/hatch.py、loading.py、shimmer.py` |
| 徽章/Tab/hover 反转/transition | `chrys.tcss`、`widgets/chrome/` |
