# User-level Personalized Memory

User-level Personalized Memory, shortened to **Personalized Memory**, retains preferences, reasons for choices, conditional lessons and unfinished intentions that you want to carry into later tasks. It helps the agent avoid repeated questions, reuse relevant experience and correct earlier content when your needs change. Open it with `/memory` or the memory entry in the conversation footer.

## What to retain

Keep information that can change a future judgment or action in a recognizable situation, together with its conditions.

| Content | Scope |
| --- | --- |
| “For technical slides, I prefer diagrams alongside text and relatively dense layouts” | A personal preference across projects |
| “When this project's report stays stale, inspect the persisted artifact version first” | A lesson for this project only |
| “Use one text-only slide for this presentation” | A temporary task requirement, not automatically a lasting preference |

Project-scoped entries still belong to your private Personalized Memory library. They do not become shared team or organizational rules automatically. One failure must not become a permanent negative judgment about your abilities, personality or an approach.

When you ask the agent to remember a method from a configuration, document or analysis, ask it to retain the rule, its conditions and a concrete example or check. For example, ask it to study the built-in agents and remember the permissions, expected output and acceptance check for a read-only investigation agent. The example travels with the rule on recall. The details show a quotation from the analysis or material read. When suggestions are enabled, inferred lessons wait for review unless you explicitly ask to save them.

## Types, topics and scope

A memory is useful when it helps a later decision or action under stated conditions. Frequency is an observation, not proof of truth or a reason to delete rarely used knowledge.

| Type | Use |
| --- | --- |
| Preference | Contextual by default. Explicitly selected **Always available** collaboration preferences can be included across tasks, with at most two per automatic selection; current instructions still take priority |
| Decision | Retain a choice and its reasons for a related future tradeoff |
| Lesson | Retain an action, its conditions and exceptions; synthesized methods require review |
| Intention | A direction remains contextual knowledge; select **Keep as a follow-up** for a cross-session commitment |

The library filters by type, topic and workspace. Short topics such as `PPT`, `cache` and `release` participate in retrieval. **All** opens all workspaces for management; chat recall remains limited to personal entries and the current workspace.

## Cross-session follow-ups

Say “Remember to run a rollback drill before the next release; the next step is staging validation,” or create an intention and enable **Keep as a follow-up** under more options. Routine task steps stay in the session Todo. Agent suggestions require acceptance before becoming reminders.

The **Follow-ups** tab shows To do, In progress, Waiting, Later, Completed and Cancelled. **Continue** places the commitment and next step in the composer; press Enter to start. Existing drafts are preserved. **Mark done** stops reminders while retaining the record. Edit the entry to change other states or its reminder time.

Dates without an offset use local time. Automatic selection includes at most one due item; undated commitments are found by task relevance. Snoozed items are excluded until their date. Completed and cancelled items stop participating in recall. Waiting is not permission to execute. Reminders appear during app use, with no notification or execution process while iCode is closed. Buddy can show a due item when there are no current references.

## Link experiences and propose methods

Ask the agent to inspect related memories and propose a reusable method, retaining conditions and exceptions. Support, exception, derivation and merge relationships identify source versions and explain their relevance. A derived method always enters **Review**. Inspect its **Related evidence** before accepting it.

Recall can expand a matched memory to related evidence or a derived method by one hop, within the same five-entry and 6,000-character selection budget. Changed or paused source evidence makes a dependent method ineligible until reviewed against current sources. Editing prose alone does not refresh source versions. Atomic merge accepts only active memories of the same kind and scope, excludes independent follow-up tasks, and rejects the whole operation if any source version is stale.

The **Related evidence** section appears only on entries with explicit links. It shows the relationship, source version and reason; select a source title to open it. Shared topics help retrieval but do not automatically create supporting or causal relationships. There is currently no automatically generated relationship graph.

Use **Review together**, optionally after selecting entries or a topic, to put a review request in the composer. Submit it when ready. The agent can inspect related entries and, for a direct ID inspection, a bounded set of earlier revisions. A merge proposal explains what each source contributes and preserves its conditions. The originals remain active until you accept the proposal in `/memory` or confirm it in a later message. Confirmation checks every source version and merges the whole set atomically; a changed source requires a new review. Independent follow-up tasks are never merged as facts.

## Observe use and feedback

**This turn** records what was provided. **Agent reported use** records the agent's claim that it changed its advice; this does not establish a positive outcome. User feedback requires an explicit user statement or a library action.

- **Skip this turn** excludes the entry from subsequent searches in this turn; the next turn evaluates it again.
- **Helpful** records your feedback for that version without automatically increasing credibility or scoring every memory in the answer.
- **Incorrect** records your correction and pauses the entry. Edit and restore it, or forget it.

Entry details show their own history. **Activity** shows creation, revision, provision, declared use, feedback and follow-up transitions. The default view shows the latest 128 events, with older records available through pagination. The complete local `personal-memory.activity.jsonl` beside the memory store retains sequence numbers, versions and available session/turn evidence for later personal trajectory analysis. Earlier use that was never recorded is not reconstructed.

## Get started

Existing version 1–3 libraries remain readable. Updating the library upgrades it to version 4 for separate recall records and review evidence. Local branches share the library; use a compatible iCode build after upgrading. Existing intentions do not automatically become commitments.

Enter `/memory` and choose a saving policy:

- **Only when asked:** the default. Ask to remember something, or say “keep this preference for next time.” Ordinary conversation does not trigger automatic extraction.
- **Remember clear preferences:** when the agent recognizes a directly stated durable preference, it saves it through a memory tool. Inferred habits and lessons await review.
- **Review before saving:** reusable information identified by the agent awaits review unless you explicitly ask to save it directly.

Previously enabled suggestions use **Remember clear preferences**. Ordinary tasks make no additional extraction request. Successful writes show **Remembered: title** or **Memory ready for review: title**. The agent interprets and polishes the content; the tool checks its evidence and revision before saving. With suggestions enabled, an actual context compression can also contribute candidates, as described below.

You can also choose **+ New**, enter the content and press `Ctrl+Enter`. Entries default to **This project only**; clear that option for use across projects.

## Tool summaries in the conversation

Memory calls use the existing tool groups and activity folds. Expand a group to inspect arguments and results. Running rows show memory lookup, preparation or pausing; a completed single call shows its actual receipt, such as **Saved memory**, **Memory to review** or **Memory unchanged**. A lookup does not establish that the answer used a memory.

Groups count memory lookups, write requests and pause requests separately, retaining failure and interruption counts. Activity folds and restored conversations use the same summaries. Older calls without a saving receipt keep a neutral description.

## Suggestions from context compression

With **Remember clear preferences** or **Review before saving**, an existing summarization request can contribute up to two personal memory suggestions. This does not make another extraction request or trigger compression earlier.

- Agent-submitted context summaries and generated current-task progress summaries can contribute. Mechanically clipped or concatenated summaries cannot.
- A suggestion needs a verbatim quotation from original user messages in the compressed range and a specific future use. Project details, progress, temporary instructions and assistant speculation do not belong in personal memory.
- Generation alone does not save anything. Only committed compression can save a **candidate**, with its source session, message and quotation. Even with clear-preference saving enabled, compression candidates never become active automatically or overwrite an existing memory.
- Repeated suggestions from the same evidence do not add entries or restore paused ones. Direct overlaps with active entries cannot overwrite them; use a conversational correction or the library editor.
- **Only when asked** and memory off disable these writes. Missing evidence, malformed suggestions or no useful personal content leave the task summary intact without repeated extraction attempts.

New candidates use the existing review notice and appear in `/memory` and Buddy's review entry. Review, activate or pause them there. The model can miss useful information or misjudge its value; explicitly asking to remember remains more reliable.

## Natural wording, polishing and updates

You can state a preference and then ask “polish and remember that preference” without repeating it. Polishing normally creates one or two self-contained sentences, with the original quotation stored separately. Suggestions added by the assistant are not automatically endorsed preferences. They must not introduce unsupported prohibitions, exceptions or claims of verified benefits.

With preference capture enabled, a clear lasting change such as “use moderate density for my technical slides from now on” can lead the agent to revise an existing entry through a tool. No fixed phrase is required; “keep doing it this way next time” can express a save request. Before writing, the agent inspects related active, pending and paused entries. The agent compares equivalent statements; exact duplicate writes reuse the existing entry without refreshing its date. Additions keep the original ID and still-valid conditions. Proposed corrections await confirmation; concurrent changes require another inspection.

When you clearly say that an experience no longer applies or a lasting goal is complete, the agent can pause the entry and record your words. Its content and history remain available in `/memory`, where you can restore it. A one-task exception, age or infrequent recall does not automatically retire a memory. Applicability still needs contextual judgment; mistaken interpretations can be corrected or paused.

Judgment can still be wrong. After a save notice, inspect the actual content, personal or project scope, source and revision in `/memory`.

If a save attempt is rejected, the footer shows **Memory · Not saved**. Hover for the attempted title and a short explanation; the tool result retains the detailed reason. Repeated failures for the same title and reason in one turn do not repeat the notice. A successful save clears it. Quoted evidence can come from any still-visible message, including an earlier preference followed by a later save request. Already-compressed original text is not reconstructed or guessed.

## What recall records tell you

**This turn** shows the entries and revisions supplied to the model, matching terms, retrieval reasons and sources. Reasons distinguish memory IDs, titles, keywords, related terminology, similar spelling and continuation of the previous task. Records retain the latest recall state for a bounded number of conversations, not a complete history of every turn's use.

**L0** provides explicitly selected always-available preferences and at most one due follow-up. **L1** searches the opening task. When a request clearly asks for separate checks, such as verifying rollback and checking staging configuration, each check has its own candidate ranking. Results share the same prompt budget. **L2** checks concrete details of a proposed local action, such as the target file or a command's output argument, before tools execute. Ordinary edits within the same action reuse its check. A change in the deliverable can trigger another check at the same path. A check without new evidence leaves the receipt and the supplement budget untouched. Up to two L2 supplements are allowed per turn. On-request and off modes disable L2. **L3** lets the agent search explicitly before choosing a format, approach or risk level. It can search with up to two alternative phrasings of the same decision, using one supplement. Details identify the stage.

Filenames and code identifiers provide additional cues: `retry_policy.py` and `RetryPolicy` can find memories about “retry policy,” and the reverse query also works. Literal names remain searchable, while `C++`, `C#` and `.NET` stay distinct. This does not provide general semantic understanding. Derived memories with outdated source revisions, completed or deferred follow-ups, and entries excluded for this turn do not consume the available entries' candidate window.

Only new evidence relevant to a concrete action can defer its batch of local changes. For example, a PowerPoint output can surface slide preferences. Reading a PowerPoint source or mentioning it in prose continues normally. The tool result reports which actions are still pending and gives the evidence to the agent. The agent checks applicability before reissuing the appropriate actions through the normal approval policy. Parallel calls share one complete memory payload. Suppressing a version already supplied to the model leaves the candidate ranking and admission unchanged.

For example, “Fix startup” may lead the agent to edit `.bashrc`. An action check can recover a preference to explain shell configuration changes before editing. Checks use bounded local lexical retrieval and operate on locally controlled actions. Deferral gives the main agent another interaction to reconsider its proposed action. Linked evidence and exceptions can accompany task-relevant memories in L1 or L3, within the same budget. Standing preferences and due follow-ups are supplied independently.

| Question | Current capability |
| --- | --- |
| Which memories were offered, and why were they selected? | Inspect them in This turn |
| Which did the model actually apply, and which recommendation changed? | The agent can report use and its reason; this is distinct from provision and does not independently establish benefit |
| Did the user affirm or reject the effect of a particular memory? | Unknown effect, inapplicable retrieval and incorrect content remain distinct. Explicit feedback is linked to the entry and version; silence and agent-reported use do not establish benefit |
| Can new statements correct earlier content? | Clear preference changes and save or correction requests can be recognized; this is not complete outcome attribution |
| Can ineffective or outdated memories be paused? | A clear user statement that an entry no longer applies or an intention is complete can lead to a tool-based pause with a recorded reason. Age, rare use and general feedback do not cause retirement; deletion still requires confirmation in the library |

Retrieval starts with active personal or current-project entries, then combines titles, applicability conditions, keywords and common English/Chinese terminology. For example, “PowerPoint,” “幻灯片” and “演示文稿” can find a PPT preference. Generic terms such as “user” or “effect” no longer select entries on their own. A preference conditioned on making slides is not automatically recalled for a website just because both mention diagrams and dense layouts.

Ask to look up a memory by its ID or title to locate a specific entry. IDs accept prefixes of at least eight characters when unique within the available scope. A bounded fallback handles distinctive English spelling errors. Explicit short follow-ups such as “continue” refer to the recent user task; a new task does not inherit the previous topic.

These rules reduce misses caused by wording changes and short follow-ups, but do not understand every paraphrase or implicit condition. If an entry is missed, supply its title, topic or applicability context. If it is selected in the wrong situation, check its conditions; one irrelevant recall does not establish that the memory itself is useless.

In **Edit → More options**, add up to six alternative retrieval phrases. They apply to that entry and become searchable after saving. Library search also uses the recall engine's terminology and spelling matches, across the states and workspaces selected in the filters. It is not limited to the agent's five-entry shortlist. Automatic recall treats a hash embedded in an ordinary task as text; a deliberate `memory <ID>` lookup still works. Long questions retain both their beginning and end for matching.

Automatic recall drops matches substantially weaker than the best result instead of filling the allowance with broad topic overlap. Explicit searches retain a wider set of related results for deliberate inspection.

“That was good” does not prove that every recalled memory helped. Silence is not endorsement. A poor answer also does not establish that a particular memory caused the problem. The system does not automatically use these signals to accumulate reliability scores, change retrieval ranking or discard entries.

## Personalized Memory in Buddy

With a Buddy already hatched, open the sidebar's **Buddy** tab. Beneath its level, a note shows the title and a short excerpt of a reference for this task. Press `Ctrl+G` if the sidebar is hidden. Use `/buddy hatch` to create a Buddy, or keep using `/memory` for the complete memory library.

- Use **‹ / ›** to browse references. The page counter opens their full list. Status refreshes preserve your place; recall for a new task starts at the first entry.
- Click the body to open that entry, or hover to read its full content. With no current references, a due follow-up takes priority. A weekly review summary can appear when related memories accumulate, recurring corrections span sessions, or items need review. Pending suggestions no longer keep a permanent badge or preview visible.
- **Saved** counts active entries available in the current project. **Review** opens the weekly summary's relevant queue: when the summary covers memories that need organizing in the current scope it opens **To organize**, otherwise it keeps opening candidates or the usual view. Opening it dismisses that summary. Narrow sidebars use symbols and counts, with full names on hover. Candidates are always available from `/memory`.
- **○ / ● Alerts** controls recall notices and weekly summaries, and defaults to off. Summaries occur during normal use, at most once in seven days, with no background model or notification process. Three entries under one topic or corrections in three sessions can prompt a review; this does not prove a stable habit. Repeated refreshes and browsing do not create another summary. Buddy mute suppresses announcements.
- Mouse clicks leave no selected row and do not pet the Buddy. Keyboard users can move focus with `Tab` and turn a page or open an entry with `Enter`.

The panel does not switch tabs or open dialogs automatically. References do not establish that the answer used a memory or that its effect was verified. After a revision, pause or deletion, an old receipt is no longer presented as a reference to the current entry. With memory off, references disappear; pending suggestions remain manageable.

## Give feedback and correct problems

| Situation | What you can do |
| --- | --- |
| It does not apply this time, but the lasting preference is valid | State that this is a one-time exception. Current instructions take priority without rewriting the lasting preference |
| The entry was wrong, or your lasting preference changed | State the correct content and scope, then check that the existing entry was revised |
| Valid content was used in the wrong situation | Narrow **When to use** in the editor rather than discarding a useful lesson because of one irrelevant recall |
| It should stop being used, but you do not yet know the correction | State which memory should stop applying and check the tool's pause confirmation, or choose **Pause** in `/memory` |
| You no longer want to retain it | Choose **Forget** and confirm deletion |
| It helped, and you want to retain the specific lesson | Explain what worked under which conditions, then request a save or update; general praise does not automatically reinforce every memory |

Paused entries stop participating in subsequent recall and can be restored. Forgetting removes the entry, revisions, pending corrections, recall references and local activity content, including dependent derived or merged memories. Existing chat history is not erased. Incomplete cleanup reports an error and can be retried. Rare use does not establish low value; entries do not expire solely because they are old.

## Review and maintenance

Search updates after a short pause; press `Enter` to open the current results immediately. Each row shows a title, state, scope, version and update time. Review, This turn and Follow-ups counts follow the selected filters. Opening related evidence clears filters that would hide the target. Editor labels remain visible after typing; errors appear above Save and focus the affected field. Entries support up to six topics (1–40 characters each) and six retrieval phrases (2–80 characters each).

A different title, topic or retrieval phrase does not create a new fact. Edit the existing entry to change these details. A chat proposal cannot recreate a paused fact; explicitly restore its original entry instead.

The panel starts with focus on its list: use `↑/↓` to navigate, `Enter` for details, `Tab / Shift+Tab` between controls and `Ctrl+F` for search. In search, `Esc` clears the query, then returns to the list. In details, `Esc` returns to the list; from the list it closes the panel. `Delete` opens a forget confirmation. `Ctrl+N` creates a memory and `Ctrl+R` refreshes.

**When this no longer applies** describes when a memory should stop guiding the answer. For example, a preference for dense technical slides may not suit distant projection or a nontechnical audience. Recheck or update the preference in those situations; it is not deleted automatically. Leave this field empty when no specific condition is known.

- Mark rows with **Select** or `Space`, then remember, pause or forget the selection. Press `Esc` or **Deselect** to clear all marks without losing your position; changing tabs also clears the selection. Each operation accepts up to 25 entries and checks all selected versions before committing; a concurrent edit rejects the whole operation. A pending alternative does not block your explicit correction to an active memory. Repeated candidates with the same title and situation require review of the existing entry.
- The library shows entry count and file size, with no entry-count quota. The footer review badge covers memories to review, similar content and repeated skips; clicking it opens **To organize**. A 64 MiB file integrity guard remains. The most recent revision stays readily available; **Earlier revisions** loads complete older evidence on demand. Legacy revisions are preserved before compaction, and interrupted migration can resume.
- Details count provision, agent-reported use, user skips and agent skips within the current version's last five recorded recall turns. Explicit helpful feedback is counted separately and can come from other conversations. Skips in at least three distinct recall turns prompt a review of usage conditions. Counts come from the recent activity retained locally and may omit older history; they are not reliability scores. The last recorded recall date is shown when available, without treating age as expiry.
- **Helpful** and **Incorrect** can be recorded for an active entry even in a different conversation. These buttons refer to the currently displayed version. **Skip this turn** requires that exact version in the current recall. Earlier versions remain visible in the activity history.
- **Activity → Earlier activity** pages through the full local journal, 100 events at a time. **Latest** returns to recent events. A loading state temporarily disables paging controls; switching tabs and pressing `Esc` to close remain available. New pages start at the top, and read failures preserve the current page. Appended activity, edits and recall preserve the page being read. Forgetting clears any old page that may contain deleted content.
- Support and exception links, as well as derived methods, stop being used when their referenced source revision changes or is paused. Review and update the relationship before using it again. A completed or cancelled follow-up must be explicitly reopened as **To do** before progress can resume.

Memories you explicitly skipped in three distinct turns remain active and appear in **To organize** with a review reason so you can refine their conditions. If all three refer to the same normalized query and workspace, only automatic retrieval in that context is suppressed. Other contexts and explicit queries remain available. This does not generalize suppression to every semantically similar situation. Edit the conditions or choose **Keep conditions** to clear these retrieval exclusions. New content versions start fresh evidence.

### To organize

**To organize** is the only review queue. It lists non-archived memories that need organizing for one of four reasons: similar content in the same type and scope (ignoring case, full-width forms and spacing), a changed or paused source, repeated **Skip this turn** feedback on the current version, or an entry marked for review. A memory with several reasons appears once, and its details list every reason. Similar-content details name each member of the group by title or ID, including members hidden by the current filters, and never name another workspace. Age, rare recall, silence, being provided, an agent-side skip, candidate status alone, a weekly summary group and a hidden filter are not reasons.

The view follows the current workspace, personal or project scope, type, topic and search filters. Reasons are computed from the whole library, so a filter hides rows without erasing their reason. Mark rows as usual, up to 25 at a time. A mark stays only while its row is visible in the queue with the same version: a filter change, refresh or version change drops it, and restoring a filter does not bring it back. Browsing, filtering and selecting never write to the library, and switching tabs still clears the marks.

Use **Review together** to put the selected IDs and versions in the composer; press Enter to send. With no selection but a topic filter or search text, the request carries only that context and no IDs. With neither, the view asks you to select something first and keeps the panel open. A draft that cannot be replaced keeps the panel, the draft and the selection. The agent proposes a synthesis or merge, and merging or pausing still needs your confirmation.

An empty view says either that no memories need organizing or that none match the current filters; neither means the library is empty or that content was deleted.

The footer review badge opens **To organize**, and so does Buddy's **Review** entry when that weekly summary's members need organizing in the current scope. When the only issue is a changed source, the footer keeps its normal browse target. **Saved**, the page counter, entry clicks and the `/memory` Saved/Review/This turn/Follow-ups/Activity/Paused/All tabs never change target because of an earlier weekly summary or a pending queue item.

Three outcomes have different consequences. **Effect unknown** means the latest use has no explicit feedback; repeated provision does not cause retirement. **Skip this turn** excludes the current recall; an agent's own skip remains an observation and never trains a lasting user preference. **Incorrect** requires your explicit correction, pauses the entry immediately and retains its source and history until you revise or restore it. Maintenance restores legacy automatic quarantines caused solely by missing feedback or repeated skips, while preserving explicit pauses. Unreviewed candidates still archive after 30 days and remain inspectable and restorable. Large maintenance queues retain every activity record and resume after interruption.

If a proposed write is very similar to an existing fact in the same situation, the rejection names that entry. Revise its ID, or explain the distinct situation before saving a separate memory. The system does not silently merge different claims.

If an operation would change too many related entries at once, it is rejected without changing the library. Reduce a batch selection before retrying. A single memory with many still-needed related entries can also reach this limit; the interface does not yet provide bulk relationship removal.

A successful save clears the failure indicator; confirming unchanged content does not repeat the save notification. If recall is unavailable, the footer shows **Mem · Unavailable** until a successful read. A failed action check leaves normal tool execution available. The warning is reported once until recovery; a later failure is reported again. Batch actions lock their controls while submitting and retain the selection on failure so you can resolve the cause and retry. Refreshing unmarks entries that have changed; review their new content before selecting them again.

In headless runs, save and rejection receipts appear in the normal stderr progress stream; `icode run --json` does not provide these progress receipts. ACP clients can gate `chrys/personal_memory` notifications on the advertised capability. They receive the saved entry's ID, version, state and title, or a rejection code and reason, without the full library. Candidate management remains available through `/memory`.

## Other features called memory

| Mechanism | Entry point and purpose |
| --- | --- |
| **Personalized Memory** | `/memory`: retain your preferences and conditional experience, select relevant entries for a task, and inspect sources, revise, pause or forget them |
| **Agent memory-file configuration** | `/agents memory`: load `AGENTS.md`, Markdown or text reference files for an agent. File content and configuration determine what is loaded; loading a file does not establish a personal preference |
| **Context-compaction summaries** | Continue work within the current conversation. A summary does not automatically become confirmed long-term Personalized Memory |

In this guide, **Personalized Memory** means the first mechanism. For adding and loading reference files, see [memory-file configuration](../configuration/memory.md). Loading a document or repeating a statement in summaries does not independently strengthen the evidence for a preference.

## Recall controls and cost

**Automatic recall** selects entries for the current question and project. **Recall on request** waits for you to ask. **Memory off** stops chat reads and writes while leaving the library editor available. **Only when asked** disables automatic extraction without disabling automatic recall.

The main agent calls memory tools when useful. There is no per-turn extraction request or second model inside a write tool. Local recall remains available for ordinary tasks. Recognition and polishing use the main agent's normal reasoning, and inspection and writing have normal tool-call costs. A chat-written memory contains at most 600 characters. A lesson with an example or check may use up to 1,600 characters for its body and example together. Each recall returns at most five entries / 6,000 rendered characters. One turn permits at most three supplementary retrievals; L2 consumes a slot only when new memories are found, using at most two and reserving one for deliberate recall. Read-only candidate checks that find nothing new do not consume slots. The shared budget is 15 distinct supplied entries and 18,000 rendered characters; automatically replaying an already supplied version does not charge those characters twice. Pre-write inspection has a separate eight-entry / 12,000-character shortlist; it is comparison material and never claims to cover the whole library. The model may miss a useful preference; an explicit request or the editor provides a way to save it.

Local retrieval and Buddy notices add no extraction-model calls. A deferred action requires the main agent to reconsider before reissuing it. Repeated queries use a local hot cache. Corrections, pauses and deletions invalidate derived results, including changes made by another instance. Equivalent wording is not counted as independent supporting evidence. Cache hits and frequent use do not increase a memory's authority.

Recall records are stored separately from the catalog, so ordinary retrieval does not rewrite all saved memories. Corrections, deletion, review evidence and recall still use consistent versions across windows. Active, current entries participate automatically; explicit inspection can also show pending, paused and review-required material.

For backup or migration, keep `personal-memory.json`, `personal-memory.recalls.json` and `personal-memory.activity.jsonl` together. Mismatched newer records are reported rather than silently overwriting history. Older implementations cannot read the new format.

Memories are stored locally. Recalled entries and entries inspected before writing are sent to your configured main model. Pending and paused content is comparison material, not active advice. The feature does not scan all old chats or run a background batch job. The main chat agent can use Personalized Memory; sub-agents and workflow agents do not automatically receive this private library.
