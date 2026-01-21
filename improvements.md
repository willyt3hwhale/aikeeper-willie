# Proposed Improvements

Analysis of the Ralph Loop repo with prioritized improvements.

---

## High Priority

### 1. Implement Role System (architecture.md Phase 4)

The architecture doc defines a role system (`roles/*.md` + `roles.yaml` triggers) but `ralph.py` only has a stub:

```python
def evaluate_triggers(task, iteration, mode):
    """Evaluate role triggers, return role name or None."""
    # TODO: implement trigger logic
    return None
```

**What to build:**
- Create `roles/` directory with initial roles: `reviewer.md`, `debugger.md`
- Create `config/roles.yaml` with trigger conditions
- Implement `evaluate_triggers()` to parse YAML and check conditions
- Update `build_prompt()` to inject role content

**Why it matters:** Roles enable context-appropriate behavior (review after 5 commits, debug after failures). Without this, Claude works in a single mode regardless of context.

---

### 2. Stuck Task Detection & Recovery

`ralph.py` has `MAX_ITERATIONS = 20` but no strategy when a task hits the limit:

```python
if not task_done:
    log(f"Task {task_id} not complete after {iterations} iterations")
```

The task stays `active` forever, blocking progress.

**What to build:**
- After hitting max iterations: mark task as `blocked`, return to main
- Add `blocked` status to the workflow
- Create `blocked-tasks.jsonl` or add `blocked_reason` field
- Consider auto-splitting: if Claude made progress but didn't finish, split into what's done vs what remains

**Why it matters:** Stuck tasks currently halt all progress. The loop should gracefully recover and allow other work to continue.

---

### 3. Add .gitignore

Untracked files are accumulating:
```
?? .DS_Store
?? ralph.log
?? tasks.jsonl
```

`tasks.jsonl` being untracked is concerning—it should probably be tracked (it's the work queue).

**What to build:**
- Add `.gitignore` with: `.DS_Store`, `ralph.log`, `*.pyc`, `__pycache__/`
- Decide: should `tasks.jsonl` be tracked? (I'd say yes—it's the work queue)
- Track `tasks-done.jsonl` for project history

---

## Medium Priority

### 4. Fill in idea.md

`idea.md` is a template with no content:

```markdown
## Goals
<!-- What are you building? -->
```

For a meta-project like Ralph Loop, this should describe its own goals.

**Suggested content:**
- Goal: External orchestration loop for Claude Code
- Constraints: Python 3.x, no external deps beyond stdlib, JSONL for storage
- Success criteria: Unattended task completion with clean git history

---

### 5. Better Error Handling in run_claude()

Current error handling is minimal:

```python
if exit_code != 0:
    log(f"Claude exited with code {exit_code}, retrying...")
    time.sleep(5)
    continue
```

**What to build:**
- Parse JSON output for error types (auth failure vs task failure)
- Different retry strategies: exponential backoff for rate limits, immediate retry for transient errors
- Log full output on failure for debugging
- Consider: after N consecutive failures, stop the loop (vs infinite retry)

---

### 6. Remove Stale log.md

`log.md` exists but architecture.md says it's replaced:

> **What we removed:**
> - `log.md` — replaced by tasks-done.jsonl + git history

Either delete it or repurpose it.

---

### 7. Leaf Flag Not Implemented

Architecture doc describes a `leaf` flag for workability:

```jsonl
{"id":"A","title":"implement auth","status":"pending","leaf":false}
```

But the current `get_next_task()` doesn't check for `leaf`:

```python
for task in tasks:
    if task.get('status') == 'pending':
        return task, 'work'
```

**What to build:**
- Add `leaf` field to task schema
- Update `get_next_task()` to only return leaf tasks
- When splitting: set parent `leaf:false`, children `leaf:true`

---

## Low Priority

### 8. Add Tests

No test files exist. For a loop that runs unattended, tests are valuable.

**What to build:**
- Unit tests for task operations (`get_next_task`, `get_children`, `archive_task_tree`)
- Integration test: create tasks.jsonl, run loop iteration, verify state
- Test stuck task handling once implemented

---

### 9. Push Remote After Squash Merge

Currently squash merges stay local:

```python
def squash_merge(branch, task_id, title):
    git('checkout', 'main')
    git('merge', '--squash', branch)
    git('commit', '-m', message)
    # no push
```

**What to build:**
- Add configurable auto-push after successful completion
- Or: batch push after N completions (reduces GitHub API noise)

---

### 10. Better Branch Naming

`slugify()` truncates at 30 chars:

```python
return ''.join(c for c in slug if c.isalnum() or c == '-')[:30]
```

This can create collisions for similar task titles.

**What to build:**
- Include task ID in slug: `task/A-implement-auth` vs `task/implement-auth`
- (Already done partially, but verify uniqueness)

---

## Summary by Effort

| Improvement | Effort | Impact |
|-------------|--------|--------|
| Add .gitignore | 5 min | Medium |
| Remove log.md | 2 min | Low |
| Fill in idea.md | 15 min | Medium |
| Stuck task detection | 1-2 hrs | High |
| Role system | 2-4 hrs | High |
| Leaf flag | 30 min | Medium |
| Error handling | 1 hr | Medium |
| Tests | 2-4 hrs | Medium |
| Remote push | 30 min | Low |
| Branch naming | 15 min | Low |

---

## Recommended Order

1. **.gitignore** — quick win, stops noise
2. **Remove log.md** — housekeeping
3. **Fill idea.md** — documents the project
4. **Stuck task detection** — critical for unattended operation
5. **Role system** — unlocks context-aware behavior
6. **Leaf flag** — completes the task hierarchy model
7. **Error handling** — improves reliability
8. **Tests** — enables confident changes
