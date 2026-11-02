# Personal memory demo

Use the fictional Orange Bridge check and Cedar project to observe a saved lesson changing a later answer, then correct it and stop using it. Wording can vary; inspect the saved content, conditions, source, and subsequent behavior.

Start iCode with a configured model that supports tools. Open `/memory`, select **Automatic recall** and **Only when asked**. These examples write to the current library; remove them at the end. Use `/new` for independent conversations while retaining previous chats.

## 1. Establish a comparison

In a new conversation, ask:

> I am considering changing our review process to automatic publishing. What decision would you recommend?

Save the answer. If your library already contains relevant advice, pause it or use **Memory off** for this comparison. Generic advice about staged deployment does not by itself prove that memory worked.

## 2. Save a conditional decision method

Restore **Automatic recall** and say:

> Can you please remember: across projects, use my Orange Bridge check for review decisions. First identify evidence that would overturn the recommendation, then propose a reversible small experiment, and only then recommend expanding investment. Do not apply this when I only want wording polished.

Open `/memory`. Expect one short saved entry with **Across projects** scope, the decision order, the exception, and your source quote. An explicit save should not require a second review. A claim of success without a saved entry is a failed save; **+ New** remains available as a manual fallback.

## 3. Observe cross-session use

Use `/new` and ask the exact question from step 1 without mentioning memory or Orange Bridge. Expect the saved decision order to affect the answer. Click the footer's **sent** count to open **This turn**, then inspect **Why it was selected**.

The reference view proves the memory was provided. The answer following the saved order shows it influenced the response. An incidental mention of a small experiment is not sufficient proof. The answer should explain the remembered basis when it changes the recommendation.

## 4. Keep the current request in control

In another new conversation, ask:

> I am changing the review process to automatic publishing. This time, only write one sentence announcing the change. Do not provide decision advice.

Expect the announcement without the three-step method. The stored memory must remain unchanged. It may still appear in **This turn**: term matching selects references, while applicability still requires judgment.

## 5. Correct the original entry

Say:

> Please update this memory: the Orange Bridge order is now a reversible small experiment first, evidence that would overturn the recommendation second, and expanded investment last. Keep the cross-project review-decision scope and the exception for wording-only tasks.

Expect the same entry, a new revision, and the old order under earlier revisions. Scope and exception should remain. Ask step 1 again in a new conversation and check the new order. If the target is ambiguous, locate or edit the original instead of adding a competing entry.

## 6. Check project isolation

In a demo directory, say:

> Remember: this Cedar project's release checklist is called Cedarleaf47. Use it only for this project's release checks and stop using it when the project ends.

Verify **This project only**. A new conversation in the same directory should recall the checklist name. Switch to a different directory with `/chdir`, then `/new`, and ask the same question: this project memory must not be provided. Relevant personal memories can still cross projects. **All** can display other-project entries for management without making them eligible for recall.

## 7. Review and stop use

| Action | Expected behavior |
| --- | --- |
| Enable suggestions and request a reviewable suggestion from a short lesson | A quoted candidate appears in **Review** and is excluded until **Remember** |
| Say “Do not remember: this report only uses blue this once” | Neither a saved entry nor a candidate is added |
| Select **Recall on request**, ask step 1 in a new chat, then explicitly ask to search personal memory | No automatic reference in the first turn; an explicit lookup can supply one |
| **Pause** Orange Bridge, then ask step 1 in a new chat | It is excluded; it remains available to restore under **Paused** |
| Select **Memory off**, then ask step 1 in a new chat | No personal memories are supplied; entries remain manageable |

Recall modes govern reading and suggestions. An explicit user save or a manual editor save remains a direct action. Turning memory off cannot erase text already present in a conversation; use a new turn or new chat to inspect the changed behavior.

## 8. Finish

Find and **Forget** the fictional entries, confirming each deletion. Check Saved, Review, and Paused, then restore your preferred mode. Prior chats remain; forgotten entries must no longer be retrieved from the library in fresh conversations.

See [Configure memory](memory.md) for limits, revision history, and reference-file behavior.
