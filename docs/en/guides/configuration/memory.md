# Configure memory

Use `/memory` for personal experiences and decisions, or `/agents memory` for reference files loaded with an agent.

## Personal memory

Enter `/memory` to open the memory library. The list shows active memories, suggestions awaiting review, archived memories, and the latest recall for this session. Select a memory to read its rationale, when to use it, when to reconsider it, source quote, and earlier revisions.

Click **+ New** to save a decision, preference, lesson, or unfinished intention. Give it a specific title, the experience and its rationale, and a future situation where it would help. **This project only** limits recall to the current working directory; clear it for a memory that applies across projects.

With **Allow suggestions** enabled, the main agent can propose memories during a conversation. Suggestions include a quote checked against a recent visible message and its source session. An assistant's quote is evidence of what it said, not proof that its conclusion is correct. Review suggestions and click **Activate** before they can be recalled. A suggested correction leaves the accepted memory unchanged until you activate it.

Choose a recall mode at the top:

- **Automatic recall:** each new turn searches active memories using the current question and project. Only matching memories are provided to the model, with their conditions and sources. The agent can refine the search for the decision or mechanism it is investigating.
- **Recall on request:** no automatic selection; ask the agent to search personal memory when needed.
- **Memory off:** neither recall nor new suggestions are available. Existing memories remain in the library.

Changes apply to the next turn without restarting the agent. The latest-recall view shows matched terms and identifies memories revised since that recall. A match means the memory was retrieved, not that its advice was correct or applied successfully. Automatic matching is lexical, supports Chinese and English, and checks project scope; it does not prove that a condition is satisfied. The agent must check applicability against the current task.

**Edit** preserves up to five earlier content revisions. **Archive** removes a memory from recall while retaining it for review; use this when an intention is finished or an experience is no longer applicable. **Forget** removes the memory, its revisions, pending corrections, and recall references after confirmation. It does not erase existing chat transcripts that already contained it.

Personal memories are stored locally in `personal-memory.json` in your user configuration directory. Only recalled content is sent to your configured model service. Recall returns at most five memories with a combined rendered-content limit of 6,000 characters; it does not scan old session logs. The library holds up to 500 memories and eight MiB, and reports when it is full. Suggestions are produced through tool calls in the current conversation; there is no background batch-extraction job. Personal memories are available to the main chat agent, including `icode run`; sub-agents and workflow agents do not receive this private library automatically.

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
