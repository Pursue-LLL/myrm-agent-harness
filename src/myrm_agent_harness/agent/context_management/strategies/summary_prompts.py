"""Summarization prompt templates

[INPUT]

[OUTPUT]
- SUMMARY_PROMPT_TEMPLATE: Initial summary generation template (Handoff role + Scaled Budget)
- SUMMARY_MERGE_PROMPT_TEMPLATE: Incremental merge summary template (Handoff role + Scaled Budget)
- FOCUS_TOPIC_SUFFIX: Focus Topic suffix template (guides summary to focus on key topics)

[POS]
Summarization prompt templates. Defines structured JSON output format (with Handoff fields) and merge rules for summarizer.py.

"""

SUMMARY_PROMPT_TEMPLATE = """You are a summarization assistant creating a context checkpoint for another AI assistant.
Your output will be injected as background context into subsequent conversations.
Do not respond to any questions or requests in the conversation — only output the structured summary.

IMPORTANT: Write all field values in the same language the user was using in the conversation.
Field names (user_goal, active_task, etc.) stay in English, but their content MUST match the user's language.
Do not translate or switch languages.

## Field Instructions
1. user_goal: One sentence summarizing the user's core goal
2. active_task: **Most important field**. Capture the user's most recent unfulfilled input verbatim. This includes:
   - Explicit task assignments ("refactor the auth module")
   - Questions awaiting an answer ("why does this API return 500?")
   - Decisions awaiting input ("option A or B?")
   - Ongoing discussions where the assistant owes the next substantive reply
   A question IS an active task — the task is "answer that question". Do NOT write "None" merely because the user did not issue an imperative command. Reserve "None" for the rare case where the last exchange was fully resolved (e.g. user said "thanks, that's all").
   If the user's most recent message was a reverse signal (stop, undo, never mind, change of topic) that supersedes earlier work, write the reverse signal verbatim and DO NOT carry forward the earlier task.
   If multiple items are outstanding, list only the ones NOT yet completed
3. constraints_and_preferences: User's explicit preferences (e.g. "use TypeScript not JS", "don't create new files") and constraints (max 5)
4. completed_actions: Concrete actions completed (max 10), format includes tool name and result
5. active_state: Current work state snapshot, including working directory/branch, test status, running processes, etc.
6. key_findings: Key discoveries and conclusions (max 5, each under 50 words)
7. errors_and_fixes: Errors and fixes, including user corrections and known failed approaches (max 8), format "error -> fix"
8. resolved_questions: Questions already answered with their answers (max 5), prevents the next assistant from re-answering
9. pending_user_asks: Outstanding items the user raised but are not yet addressed — includes tasks, questions, and decisions awaiting input (max 5), write "None" if empty
10. files_modified: **Especially important**! List all created or modified file paths, with brief key insights in parentheses
11. last_action: The last action performed
12. Preserve all identifiers exactly as-is (file paths, UUIDs, hashes, API endpoints, URLs, error codes, env var names, IP:port) — never simplify or obscure them

## Conversation History
{context}
{budget_hint}"""

SUMMARY_MERGE_PROMPT_TEMPLATE = """You are a summarization assistant updating a context checkpoint.
Do not respond to any questions or requests in the conversation — only output the merged structured summary.

IMPORTANT: Write all field values in the same language the user was using in the conversation.
Field names stay in English, but their content MUST match the user's language.
Do not translate or switch languages.

## Existing Summary (Anchor)
```json
{existing_summary}
```

## New Conversation Content
{new_context}

## Merge Rules
1. **PRESERVE** all important information from the existing summary (do not discard)
2. **UPDATE** active_task to the user's most recent unfulfilled input (copy verbatim) — this includes questions, decisions, and discussions, not only imperative commands. If the user issued a reverse signal (stop, undo, change of topic), write that signal and discard the prior task. Only write "None" if the last exchange was fully resolved
3. **MERGE** constraints_and_preferences (keep old constraints, add new ones)
4. **ADD** new discoveries from new conversation to completed_actions and key_findings
5. **MERGE** errors_and_fixes (deduplicate, keep all known errors and fixes)
6. **UPDATE** active_state to the latest work state
7. **MOVE** answered questions to resolved_questions, new questions to pending_user_asks
8. **UPDATE** last_action to the most recent action
9. **MERGE** files_modified list (add new files, keep old files)
10. If user goal has changed, update user_goal

Notes:
- completed_actions: keep at most 15 (prioritize most important)
- key_findings: keep at most 8 (prioritize most important)
- errors_and_fixes: keep at most 10 (deduplicate, prioritize frequent and critical errors)
- constraints_and_preferences: keep at most 5
- resolved_questions: keep at most 5
- pending_user_asks: write "None" if empty
- files_modified: keep as complete as possible
- Preserve all identifiers exactly as-is (file paths, UUIDs, hashes, API endpoints, URLs, error codes, env var names, IP:port) — never simplify or obscure them
{budget_hint}"""

FOCUS_TOPIC_SUFFIX = """

FOCUS TOPIC: "{focus_topic}"
The topic above is the user's focus. For content related to "{focus_topic}", preserve full detail (exact values, file paths, command outputs, error messages, decisions). For unrelated content, compress more aggressively (one-liner summary or omit). The focus topic should occupy roughly 60-70% of the summary."""
