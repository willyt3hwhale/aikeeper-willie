# Willie Loop Workflow

## Orient
```
git status              → uncommitted changes?
git log --oneline -3    → what just happened?
```
Read: idea.md (vision), learnings.md (knowledge), tasks.jsonl (context)

## Evaluate Your Task

A task is ready if: small (~20-50 lines, 1-3 files), single responsibility, no unknowns.

**Don't understand it → RESEARCH**
State the question. Investigate. Document in learnings.md. Split into subtasks.

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

## tasks.jsonl
```json
{"id":"A.1","title":"do thing","status":"pending"}
```
Statuses: `pending`, `active`, `complete`, `split`

## When Something Breaks
Root cause first — don't repeat failed approaches. Fix, test, commit. Add gotcha to learnings.md.

## After Work
- Reusable pattern? → learnings.md "Patterns"
- Gotcha? → learnings.md "Gotchas"

## Rules
- Commit often. Never leave uncommitted work.
- Understand first. Never code through confusion.
- When stuck: commit what you have, split the task.
