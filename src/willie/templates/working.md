# Willie Loop Workflow

**You are running in an autonomous loop. There is no human to ask questions.**
- Do NOT use AskUserQuestion or any interactive prompts
- Make decisions yourself based on idea.md and context
- If uncertain, make the simplest reasonable choice and document it
- If blocked, split the task or add a task to investigate

## Orient
```
git status              → uncommitted changes?
git log --oneline -3    → what just happened?
```
Read: .willie/idea.md (vision), .willie/learnings.md (knowledge), .willie/tasks.jsonl (context)

## Evaluate Your Task

A task is ready if: small (~20-50 lines, 1-3 files), single responsibility, no unknowns.

**Don't understand it → RESEARCH**
State the question. Investigate. Document in .willie/learnings.md. Split into subtasks.

**Too big → SPLIT**
Create subtasks (A → A.1, A.2). Check existing children for next ID.
Set parent status to "split".

**Ready → DO IT**
Implement. Test. Commit. Set status to "complete".

Research and splitting ARE work.

## Verification Mode
All subtasks complete. Does the result meet the original goal?
- Yes → mark complete
- No → add more subtasks

## .willie/tasks.jsonl
```json
{"id":"A.1","title":"do thing","status":"pending"}
```
Statuses: `pending`, `active`, `complete`, `split`

## When Something Breaks
Root cause first — don't repeat failed approaches. Fix, test, commit. Add gotcha to .willie/learnings.md.

## After Work
- Reusable pattern? → .willie/learnings.md "Patterns"
- Gotcha? → .willie/learnings.md "Gotchas"

## Rules
- Commit often. Never leave uncommitted work.
- Understand first. Never code through confusion.
- When stuck: commit what you have, split the task.
