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

## Get started

Enter `/memory` and choose a saving policy:

- **Only when asked:** the default. Ask to remember something, or say “keep this preference for next time.” Ordinary conversation does not trigger automatic extraction.
- **Remember clear preferences:** check each new turn, save directly stated durable preferences immediately, and propose inferred lessons and other conclusions for review.
- **Review before saving:** automatically extracted content awaits review unless you explicitly ask to save it directly.

Previously enabled suggestions use **Remember clear preferences**. The footer shows **Memory · Checking** during extraction. Successful writes show **Remembered: title** or **Memory ready for review: title**. No entry is added when there is nothing useful to retain.

You can also choose **+ New**, enter the content and press `Ctrl+Enter`. Entries default to **This project only**; clear that option for use across projects.

## Natural wording, polishing and updates

You can state a preference and then ask “polish and remember that preference” without repeating it. Polishing normally creates one or two self-contained sentences, with the original quotation stored separately. Suggestions added by the assistant are not automatically endorsed preferences. They must not introduce unsupported prohibitions, exceptions or claims of verified benefits.

With automatic extraction enabled, a clear lasting change such as “use moderate density for my technical slides from now on” can revise the existing entry without a fixed “update memory” phrase. With extraction disabled, explicitly ask to update the preference. Equivalent statements should reuse an entry. Revisions preserve earlier versions; a proposed correction does not overwrite accepted content until you confirm it.

Judgment can still be wrong. After a save notice, inspect the actual content, personal or project scope, source and revision in `/memory`.

## What recall records tell you

**This turn** shows the entries and revisions supplied to the model, matching terms and sources. Records retain the latest recall state for a bounded number of conversations, not a complete history of every turn's use.

| Question | Current capability |
| --- | --- |
| Which memories were offered, and why were they selected? | Inspect them in This turn |
| Which did the model actually apply, and which recommendation changed? | Not tracked automatically; recall alone does not establish use |
| Did the user affirm or reject the effect of a particular memory? | No per-memory attribution or positive/negative outcome statistics |
| Can new statements correct earlier content? | Clear preference changes and save or correction requests can be recognized; this is not complete outcome attribution |
| Are ineffective or outdated memories automatically paused or deleted? | No; use Pause or Forget in the library |

Retrieval currently relies mainly on matching terms. Generic terms such as the Chinese words for “user” or “effect” can bring in unrelated entries. Retrieving a technical-slide preference while discussing the memory mechanism indicates a relevance problem with that selection; it does not establish that the preference is useless when making technical slides.

“That was good” does not prove that every recalled memory helped. Silence is not endorsement. A poor answer also does not establish that a particular memory caused the problem. The system does not automatically use these signals to accumulate reliability scores, change retrieval ranking or discard entries.

## Give feedback and correct problems

| Situation | What you can do |
| --- | --- |
| It does not apply this time, but the lasting preference is valid | State that this is a one-time exception. Current instructions take priority without rewriting the lasting preference |
| The entry was wrong, or your lasting preference changed | State the correct content and scope, then check that the existing entry was revised |
| Valid content was used in the wrong situation | Narrow **When to use** in the editor rather than discarding a useful lesson because of one irrelevant recall |
| It should stop being used, but you do not yet know the correction | Choose **Pause** in `/memory`. Mentioning the problem in chat does not mean the entry was automatically paused |
| You no longer want to retain it | Choose **Forget** and confirm deletion |
| It helped, and you want to retain the specific lesson | Explain what worked under which conditions, then request a save or update; general praise does not automatically reinforce every memory |

Paused entries stop participating in subsequent recall and can be restored. Forgetting removes the entry, related revisions, pending corrections and recall references, but does not erase existing chat transcripts. Rare use does not establish low value; entries do not expire solely because they are old.

## Other features called memory

| Mechanism | Entry point and purpose |
| --- | --- |
| **Personalized Memory** | `/memory`: retain your preferences and conditional experience, select relevant entries for a task, and inspect sources, revise, pause or forget them |
| **Agent memory-file configuration** | `/agents memory`: load `AGENTS.md`, Markdown or text reference files for an agent. File content and configuration determine what is loaded; loading a file does not establish a personal preference |
| **Context-compaction summaries** | Continue work within the current conversation. A summary does not automatically become confirmed long-term Personalized Memory |

In this guide, **Personalized Memory** means the first mechanism. For adding and loading reference files, see [memory-file configuration](../configuration/memory.md). Loading a document or repeating a statement in summaries does not independently strengthen the evidence for a preference.

## Recall controls and cost

**Automatic recall** selects entries for the current question and project. **Recall on request** waits for you to ask. **Memory off** stops chat reads and writes while leaving the library editor available. **Only when asked** disables automatic extraction without disabling automatic recall.

Automatic extraction uses the current conversation model and adds at most one automatic check per new turn, increasing the wait before an answer begins. Extraction failures are reported and the conversation can continue. Each check produces at most three memories of up to 600 characters each. One recall selects at most five entries with a combined rendered-content limit of 6,000 characters.

Memories are stored locally. Selected entries are sent to your configured model service for recall; extraction also sends bounded recent conversation and existing memories for comparison. It does not scan all old chats or run a background batch job. The main chat agent can use Personalized Memory; sub-agents and workflow agents do not automatically receive this private library.
