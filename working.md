# Ralph Loop Workflow

Read these files on every iteration:
1. idea.md - project vision
2. learnings.md - accumulated knowledge
3. log.md - recent work + NEXT UP

## 1. Pick Task
- Check NEXT UP in log.md
- If empty: pick ONE from todo.md (create todo.md if missing)

## 2. Evaluate: Can This Be Done in One Focused Session?

A task is "atomic" if it's:
- Clear what to do (no research needed)
- Small scope (~20-50 lines, 1-3 files)
- Single responsibility

**If NOT atomic → SPLIT IT (this is your whole session)**
1. Break into sub-tasks as checkboxes under the parent item
2. Each sub-task should be atomic
3. Commit the updated todo.md
4. Set NEXT UP to first sub-task
5. Done - let next iteration implement

**If atomic → DO IT**
1. Implement the task
2. Test it
3. Commit
4. Mark complete in todo.md

## 3. When Stuck

**Don't know HOW?** → Research first
- Investigate the problem
- Document findings in learnings.md
- Convert to concrete sub-tasks in todo.md
- Set NEXT UP to first sub-task

**Something broke?** → Fix it
- Find root cause, fix, test
- Add gotcha to learnings.md

## 4. Learn
After each session, ask:
- Reusable pattern? → learnings.md "Patterns"
- Gotcha to avoid? → learnings.md "Gotchas"
- Better workflow? → Update this file, note in log.md

## 5. Wrap Up (CRITICAL)
1. Commit all changes
2. Add brief summary to log.md
3. SET NEXT UP - specific task for next iteration
4. If you modified working.md, note what changed

## Meta-Rules
- Splitting IS work. A session that only splits a big task is a good session.
- Task failing repeatedly? Research task first.
- Stuck with no path? Document blockers, set NEXT UP to research.

---
## Discovered Additions
<!-- Add workflow improvements here as you learn them -->
