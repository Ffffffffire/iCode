# Configure memory

Use `/memory` for personal experiences and decisions, or `/agents memory` for reference files loaded with an agent.

Follow the [personal memory demo](memory-demo.md) to try saving, cross-session use, correction, and stopping use.

## Personal memory

Personal memory keeps choices and their reasons, preferences, experience, and unfinished intentions that you want to carry into later tasks. A useful memory either helps with a recognizable future situation or preserves something you explicitly want to recall. One failed attempt should not become a lasting negative judgment about you or an approach.

| Content | Where it belongs |
| --- | --- |
| Personal preferences, reasons for choices, and durable intentions across tasks | Personal scope, such as presenting customer value and rollout before technical details |
| Repository constraints, project decisions, and project-specific lessons | This project only, such as checking artifact versions when that project's reports stay stale |
| Current progress, a one-time exception, or rapidly changing runtime state | The conversation, task summary, or todos; do not turn these into lasting rules by default |
| Whole reference documents, team conventions, and tool instructions | Reference files or project documentation; loading a file does not make it evidence of your preferences |

Project entries in your personal library remain under your control; they are not automatically published as team consensus. Shared knowledge needs separate review of its audience, evidence, and maintenance responsibility. A compaction summary can preserve unfinished work, but repeating a claim in summaries does not strengthen its evidence.

### Save a short memory

Click **Memory** in the conversation footer, or enter `/memory`. **Review** opens pending suggestions directly; a **sent** count opens **This turn** to inspect the memories provided to the agent. These indicators do not interrupt the conversation.

Click **+ New** (`Ctrl+N`), write what you want remembered, and press `Ctrl+Enter` to save. The first line becomes the title. Expand **More options** only if you need a different title, category, applicability condition, or reason to reconsider. **This project only** is checked by default; clear it for memories that apply across projects.

You can also explicitly ask the main agent to “remember…”, “can you please remember…”, or “update this memory…” in chat. It checks the current user request and saves directly, without creating a suggestion that needs a second confirmation. Negated requests and commands inside code or quotations cannot authorize a save on their own. An explicit “do not remember” also prevents a suggestion from that message, even with suggestions enabled. If a request is ambiguous or unrecognized, save it directly in `/memory`.

You can state a preference first and then ask “Polish this and please remember this preference.” The latest request authorizes saving; the source quote can come from your earlier message, without repeating all its content in the request. Intervening tool calls and results do not consume the recent visible-text evidence limit. Polishing should preserve the original scope without inventing confirmed outcomes, exceptions, or conclusions.

Chat extraction is limited to 600 characters per memory: one short conclusion and a future situation where it applies, adding a reason or condition for reconsidering it when relevant. Longer text is rejected for further distillation, never silently truncated. “Never add fields to a design” is too broad; “Before extending trajectory IR, establish a consumer; extend it when that consumer demonstrates how the fields change its output” remains actionable and open to new evidence. Manual editing still allows longer content, up to 2,400 characters.

Choose a saving policy at the bottom of the library. **Only when asked** is the default:

- **Only when asked:** ordinary conversation adds no automatic extraction request. A request such as “keep this preference for next time” is understood in context, polished and saved.
- **Remember clear preferences:** check each new turn, automatically save directly stated durable preferences, and propose inferred lessons, decisions and intentions for review. Previously enabled suggestions use this policy.
- **Review before saving:** extract automatically, but keep new memories pending review unless you explicitly ask to save them directly.

Automatic extraction uses the current conversation model and adds at most one automatic extraction request per new turn, increasing the wait before an answer begins. The footer shows **Memory · Checking**; successful writes show **Remembered: title** or **Memory ready for review: title**. Nothing is added when there is no useful new information. A failed extraction is reported without claiming a save or preventing the conversation from continuing.

Polishing normally produces one or two self-contained sentences, preserving meaning without invented exceptions or claims of verified benefits. Preferences, decisions and intentions require the user's own words; assistant text can only support a lesson awaiting review. Inspect the source and click **Remember** or **Skip**. A pending correction leaves accepted memory unchanged until you confirm it.

### Duplicates and corrections

- **Same content and conditions:** identical content, applicability, reconsideration condition, kind, and scope reuse the existing entry, even with a different title or surrounding whitespace. Repetition does not become new evidence.
- **The old conclusion is wrong:** say “Update this memory: …”. The agent must locate the original entry and revision. An unresolved or ambiguous target needs lookup or clarification, not a new competing entry. Chat corrections keep the existing personal/project scope; change scope in the editor.
- **This task is an exception:** state what you need this time. The current instruction wins without changing a lasting preference. Different applicability conditions can coexist.
- **It should not guide you while its correctness is uncertain:** choose **Pause** in `/memory`, then edit or restore after checking. Choose **Forget** and confirm if you no longer want it retained.

Extraction compares against a bounded set of existing memories to detect equivalent statements and actual corrections. A clear preference change can update its existing entry and retain the previous version. Scope, overlap and revision checks still run when writing. The comparison is bounded and model judgment is fallible, so not every paraphrased contradiction can be detected. You can pause an incorrect memory before you know the right replacement.

Pause an intention when completed or abandoned; a useful lesson from it can remain separately. Memories do not automatically expire with age and do not replace scheduled reminders. Continued use depends on whether their conditions still hold. Recheck changeable information such as software versions, paths, and job roles before relying on it.

### Use it when relevant

Choose a recall mode at the bottom of the library:

- **Automatic recall:** each new turn searches saved memories using the current question and project. Only matching memories are provided to the model, with their conditions and sources. The agent can refine the search for the decision or mechanism it is investigating.
- **Recall on request:** no automatic selection; ask the agent to search personal memory when needed. If its search terms find nothing, the current user request is searched as a fallback so shortened keywords do not lose the original task.
- **Memory off:** neither recall nor new suggestions are available. Existing memories remain in the library.

When a new turn does not recall anything automatically, **This turn** and the footer reference count clear the previous turn's references. A subsequent on-demand search displays its new results.

Changes apply to the next turn without restarting the agent; a completed chat correction also returns the actual saved content and revision to the agent. In **This turn**, expand **Why it was selected** to inspect matching terms and revisions changed since recall. This records what the agent received, not whether it applied the memory correctly. Matching currently uses Chinese and English terms plus project scope; it can miss paraphrases and does not establish that a condition is satisfied. Current instructions and verified facts take priority over history. The agent is instructed to explain its source when a memory changes its recommendation, and you can say that it does not apply to this task.

**Edit** preserves up to five earlier content revisions. **Pause** removes a memory from recall while retaining it; open **Paused** to **Restore** it. **Forget** is available directly on saved and paused memories and requires confirmation. Forgetting removes the memory, revisions, pending corrections, and recall references, but does not erase existing chat transcripts. Skipped suggestions remain in Paused too. `Ctrl+F` focuses search, `Down` enters the list, and `Esc` returns to the conversation.

Personal memories are stored locally in `personal-memory.json` in your user configuration directory. Recalled content is sent to your configured model service; extraction also sends bounded recent conversation and existing memories for comparison. Recall returns at most five memories with a combined rendered-content limit of 6,000 characters. Automatic extraction produces at most three entries per check, without scanning old session logs or running a background batch job. The library holds up to 500 memories and eight MiB, and reports when it is full. Personal memories are available to the main chat agent, including `icode run`; sub-agents and workflow agents do not receive this private library automatically.

## Reference files

The following settings apply to reference files configured in `/agents memory`.

## Prepare memory content

**Memory is added to the system prompt when the main agent loads.** iCode reads the memory files configured for the current main agent and provides their content to the agent as reference material. Memory content uses part of the model's context window and is sent to the model service with requests. Avoid including sensitive information such as secret keys or access tokens in memory.

**Sub-agents do not load memory.** Sub-agents neither inherit the main agent's loaded memory nor load memory from their own agent profiles. Agent nodes in [workflows](../running/workflows.md), however, load the memory configured in their agent profiles.

**Memory is suited to stable, reusable information.** iCode only loads memory files with the `.md` or `.txt` extension. Memory should contain information that can be reused across tasks, such as project conventions, background material, and frequently needed information. Keep it brief, clear, and up to date; instructions for a temporary task are better included directly in the current request.

**The default agents already use AGENTS.md as memory.** The main agents included with iCode, such as Code Agent, load `AGENTS.md` from the working directory. To add general project instructions, start by maintaining this file. If it is not needed, remove its entry from the "Memory" tab.

## Add a memory file

1. Enter `/agents memory` in the input field to open the current agent's "Memory" tab. To configure another main agent, select it from the list on the left.
2. Click "+ Add File" in the "Files" section.
3. Enter a path, or use "Browse" to select a `.md` or `.txt` file. With "Workspace relative" selected, enter a relative path, such as `AGENTS.md` or `docs/context.md`; otherwise, enter an absolute path.

    > **Note:** Relative paths are resolved against the current working directory when memory loads, rather than the directory where the agent profile was created. This lets the same agent load each project's own `AGENTS.md`. Relative paths must stay inside the working directory; use an absolute path for files outside it.
4. Click "Save", then close the agent configuration window.

## Add a memory folder

To load a set of reference files, click "+ Add Folder" in the "Folders" section. With "Workspace relative" selected, enter a relative path; otherwise, enter an absolute path. When finished, click "Save", then close the agent configuration window.

iCode first loads the `.md` and `.txt` files directly in the folder, then scans subfolders one level at a time. For each configured folder, it scans at most two levels of subfolders and loads at most 100 files. If an important file may fall outside these limits, add it separately in the "Files" section.

## Load and reload memory

If the same file is both added individually and discovered in a folder, it is loaded only once. The combined content from all memory sources is limited to 35,000 tokens. Individually added files load first, then folders. Once a file would exceed the limit, that file and all remaining files are skipped, and iCode displays a warning.

After switching working directories or changing the current agent profile, iCode reloads memory using the new paths.

iCode does not monitor loaded memory files for changes. After editing a file directly on disk, reload the main agent for the changes to take effect. For example, restart iCode, switch working directories, modify and save the current agent profile, or switch to another main agent and then switch back.

## Verify that memory is loaded

Enter `/runtime` in the input field, or click the file count at the right end of the status bar above the input field, to open "Runtime Details". Switch to the "Files" tab. This page lists the files actually loaded, grouped by their configured source. If the expected files appear in the list, memory has loaded.

If an expected file is missing, check the following:

* Does the path exist, and does the file have the `.md` or `.txt` extension?
* For a relative path, is the file in the current working directory?
* Does the entry type match the actual path? A file entry must point to a file, and a folder entry to a folder.
* Is there a warning that the content exceeds 35,000 tokens or that some files were skipped?
* Did you click "Save" after changing the configuration?
