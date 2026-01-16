# Ralph Loop Workflow

## 0. Orient (30 seconds)
```
Check: .claude/ralph-loop.local.md  → iteration #, max, promise
Check: git log --oneline -3         → what just happened?
Check: git diff HEAD~1 --stat       → what files changed?
```

Read these files on every iteration:
1. **idea.md** - project vision (skim after iteration 1)
2. **learnings.md** - accumulated knowledge
3. **log.md** - recent work + **NEXT UP** (start here)

### First Iteration?
If log.md NEXT UP is empty or files don't exist:
1. Read idea.md thoroughly
2. Create todo.md with initial tasks from the vision
3. Set NEXT UP to first concrete task
4. Commit and end iteration

## 1. Pick Task
- Check NEXT UP in log.md → this is your task
- If empty: pick ONE from todo.md (smallest unblocked item)
- If todo.md missing: create it from idea.md

## 2. Evaluate: Is This Task Ready?

A task is "ready" if:
- You know exactly what to do (no unknowns)
- Small scope (~20-50 lines, 1-3 files)
- Single responsibility

**If you don't fully understand it → RESEARCH FIRST**
1. State the specific question you need answered
2. Investigate: read code, search docs, run experiments
3. Document findings in learnings.md
4. Now rewrite the task as concrete sub-tasks in todo.md
5. Set NEXT UP to first sub-task
6. Done - research IS the work for this iteration

**If too big → SPLIT IT**
1. Break into sub-tasks as checkboxes under the parent item
2. Each sub-task should be atomic and ready
3. Commit the updated todo.md
4. Set NEXT UP to first sub-task
5. Done - let next iteration implement

**If ready → DO IT**
1. Implement the task
2. Test it (even quick manual test counts)
3. Commit with descriptive message
4. Mark complete in todo.md

## 3. When Something Breaks
- Find root cause first (don't guess-and-check)
- Fix, test, commit
- Add gotcha to learnings.md

## 4. Learn
After completing work, ask:
- Reusable pattern? → learnings.md "Patterns"
- Gotcha to avoid? → learnings.md "Gotchas"
- Better workflow? → Update this file

## 5. Wrap Up (CRITICAL - every iteration)
1. Commit all changes (don't leave uncommitted work)
2. Add 1-line summary to log.md History
3. **SET NEXT UP** - specific, actionable task for next iteration
4. If you modified working.md, note the change in log.md

## Anti-Patterns
- ❌ Starting implementation without full understanding
- ❌ Leaving NEXT UP empty or vague ("continue work")
- ❌ Skipping commits ("I'll commit later")
- ❌ Repeating the same failed approach

## Meta-Rules
- Research and splitting ARE work. A session that clarifies is a good session.
- One focused task per iteration. Do it well, then stop.
- Understand first, then implement. Never code through confusion.
- When in doubt: commit what you have, set clear NEXT UP.

---
## Discovered Additions
<!-- Add workflow improvements here as you learn them -->
