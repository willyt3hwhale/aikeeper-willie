# Ralph Loop v2 Architecture

## Overview

Evolution from prompt-based workflow to externally-driven agent loop with:
- External orchestration (bash/python) instead of in-Claude looping
- Local task database instead of todo.md
- Branch-per-task git workflow with squash merges
- Event-triggered roles for different thinking modes

---

## Core Components

### 1. External Loop (Orchestrator)

```
┌─────────────────────────────────────────────────┐
│  External Loop (bash/python)                    │
│                                                 │
│  while true:                                    │
│    task = poll_for_task()                       │
│    if task:                                     │
│      branch = create_branch(task)              │
│      while not task_complete(task):            │
│        role = evaluate_role_triggers()         │
│        prompt = build_prompt(role)             │
│        claude --prompt "$prompt"               │
│      squash_merge(branch)                      │
│      mark_complete(task)                       │
│    sleep(interval)                             │
└─────────────────────────────────────────────────┘
```

**Responsibilities:**
- Poll for available tasks (no tokens burned)
- Manage git branches
- Evaluate role triggers between iterations
- Detect task completion
- Handle squash merge workflow

**Open questions:**
- Polling interval? (30s? 1m? configurable?)
- Max iterations per task before escalating/pausing?
- How to handle stuck tasks?

---

### 2. Task Storage (JSONL Files)

Simple file-based task storage. JSONL (one JSON object per line) gives structure without complexity.

**Two files:**
- `tasks.jsonl` — active tasks (pending, in_progress)
- `tasks-done.jsonl` — completed tasks (append-only archive)

**Task format with hierarchical IDs:**
```jsonl
{"id":"A","title":"implement auth","status":"pending","leaf":false}
{"id":"A.1","title":"setup session store","status":"pending","leaf":false}
{"id":"A.1.1","title":"choose session library","status":"active","leaf":true}
{"id":"A.1.2","title":"implement middleware","status":"pending","leaf":true}
{"id":"A.2","title":"add login endpoint","status":"pending","leaf":true}
{"id":"B","title":"write tests","status":"pending","leaf":true}
```

**Dotted IDs for hierarchy:**
- `A` is parent, `A.1` is child, `A.1.1` is grandchild
- Hierarchy visible at a glance
- Easy to grep subtrees: `grep '"id":"A\.'`

**Leaf flag for workability:**
- `leaf:true` — actual work, can be claimed
- `leaf:false` — container, only organizes subtasks
- Outer loop only assigns leaf tasks
- When splitting: set parent `leaf:false`, create children with `leaf:true`

**Querying:**
```bash
# Get next workable task
grep '"leaf":true' tasks.jsonl | grep '"status":"pending"' | head -1

# All subtasks of A
grep '"id":"A\.' tasks.jsonl

# Count pending
grep -c '"status":"pending"' tasks.jsonl
```

**Completion flow:**
```bash
# Mark complete: move from active to done
TASK=$(grep '"id":"A.1.1"' tasks.jsonl)
DONE=$(echo "$TASK" | jq -c '. + {completed:"2024-01-21",commit:"abc123"}')
echo "$DONE" >> tasks-done.jsonl
grep -v '"id":"A.1.1"' tasks.jsonl > tmp && mv tmp tasks.jsonl
```

**tasks-done.jsonl example:**
```jsonl
{"id":"A.1.1","title":"choose session library","completed":"2024-01-21","commit":"abc123"}
{"id":"A.1.2","title":"implement middleware","completed":"2024-01-21","commit":"def456"}
```

**Why JSONL over SQLite:**
- Zero dependencies (grep, jq)
- Human readable/editable
- Git-friendly (line-based diffs)
- Simpler mental model
- Scales to thousands with archive pattern

**Why JSONL over markdown:**
- Structured, parseable by bash
- No ambiguous formatting
- Consistent field access

---

### 3. Branch Workflow

Each task gets its own branch with squash merge on completion.

```
main ─────────────────────●────────────────────●─────
                         ╱                    ╱
task/auth ──●──●──●──●──╯                    │
                                             │
task/api-refactor ──●──●──●──●──●──●────────╯
```

**Flow:**
1. Task claimed → create `task/<slug>` branch
2. Inner loop commits freely (small, frequent commits)
3. Task complete → squash merge to main
4. Branch deleted

**Benefits:**
- Clean main history (one commit per feature)
- Full detail preserved in branch (before squash)
- Easy to abandon failed attempts (delete branch)
- Natural isolation between tasks

**Implementation notes:**
```bash
# Start task
git checkout -b "task/$(slugify "$task_title")"

# During work (Claude commits normally)
git commit -m "research: explored auth options"
git commit -m "implement: basic session handling"
git commit -m "fix: session expiry edge case"

# Complete task
git checkout main
git merge --squash "task/$branch"
git commit -m "feat: implement user authentication"
git branch -d "task/$branch"
```

---

### 4. Role System

Roles modify Claude's behavior for specific situations. Triggered by events, not arbitrary timing.

**Role definition (roles/*.md):**
```
roles/
├── reviewer.md      # code review perspective
├── architect.md     # system design perspective
├── debugger.md      # failure investigation mode
├── documenter.md    # documentation focus
└── refactorer.md    # cleanup/simplification mode
```

**Example role file (roles/reviewer.md):**
```markdown
# Role: Reviewer

You are reviewing recent work with a critical eye.

## Focus Areas
- Code correctness and edge cases
- Consistency with existing patterns
- Missing error handling
- Test coverage gaps
- Documentation accuracy

## This Iteration
- Do NOT implement new features
- Review commits since branch creation
- Add findings to learnings.md under "Review Notes"
- Create follow-up tasks in tasks.jsonl for issues found
- Mark current task complete if review passes

## Output
End with a brief summary: what you reviewed, what you found, what needs attention.
```

**Trigger configuration (roles.yaml):**
```yaml
triggers:
  # After significant work, review it
  - condition: "branch_commits >= 5"
    role: "reviewer"

  # Refactoring tasks get architect perspective
  - condition: "task_title contains 'refactor'"
    role: "architect"

  # After a failure, switch to debugger mode
  - condition: "last_iteration_failed"
    role: "debugger"

  # Periodically document what we've learned
  - condition: "iterations_since_role('documenter') >= 10"
    role: "documenter"

  # Before completing a task, final review
  - condition: "task_marked_ready_to_complete"
    role: "reviewer"
```

**Trigger evaluation (pseudocode):**
```python
def evaluate_triggers(task, iteration_state):
    for trigger in load_triggers():
        if evaluate_condition(trigger.condition, task, iteration_state):
            return load_role(trigger.role)
    return None  # no role, use base working.md

def build_prompt(role):
    base = read_file("working.md")
    if role:
        role_content = read_file(f"roles/{role}.md")
        return f"{base}\n\n---\n\n{role_content}"
    return base
```

---

### 5. Completion Detection & History

**How does the outer loop know a task is done?**

Claude updates the task status in tasks.jsonl (sets `"status":"complete"`).
Outer loop checks after each iteration:
```bash
grep '"status":"complete"' tasks.jsonl
```

**Completion triggers two things:**
1. Task moves from `tasks.jsonl` → `tasks-done.jsonl`
2. Git commit with task context in message

**Commit message format:**
```
[A.1.1] choose session library

- Evaluated express-session, cookie-session
- Picked express-session for simplicity

Completes: A.1.1
```

**History lives in two places:**
- `tasks-done.jsonl` — structured data (what, when, which commit)
- Git log — narrative context (why, how)

**Why both?**
- Quick queries: `grep "auth" tasks-done.jsonl`
- Full context: `git show abc123`
- No duplication of purpose: structured vs narrative

**What we removed:**
- `log.md` — replaced by tasks-done.jsonl + git history
- NEXT UP — outer loop claims tasks, no need for manual tracking
- History section — git log IS the history

---

## Minimal Loop (Starting Point)

```bash
#!/bin/bash
# ralph.sh - minimal external loop

MAX=50
i=0

while true; do
  # Stop signal: touch .stop to halt gracefully
  [[ -f .stop ]] && echo "Stopped." && rm .stop && exit 0

  ((i++))
  [[ $i -gt $MAX ]] && echo "Max iterations reached." && exit 0

  echo "=== Iteration $i ($(date '+%H:%M:%S')) ===" | tee -a ralph.log

  claude "read working.md and execute"
  code=$?

  if [[ $code -ne 0 ]]; then
    echo "Exit code $code, waiting 10s..." | tee -a ralph.log
    sleep 10
    continue  # retry
  fi

  sleep 2  # breathing room between iterations
done
```

**Usage:**
```bash
./ralph.sh          # start loop
touch .stop         # graceful stop (between iterations)
tail -f ralph.log   # watch progress
```

**What this gives you:**
- Iteration counting with safety limit (MAX=50)
- Stop file mechanism for graceful shutdown
- Basic timestamped logging
- Automatic retry on failure with 10s backoff
- 2s delay between iterations

**What to add next (in order of value):**
1. JSONL task storage (tasks.jsonl + tasks-done.jsonl)
2. Branch workflow (clean commits, easy rollback)
3. Task claiming from JSONL (token-free polling)
4. Role triggers (evaluate between iterations)
5. Smarter error detection (parse output, not just exit codes)

---

## Implementation Phases

### Phase 1: External Loop Skeleton
- [ ] Basic bash script (ralph.sh)
- [ ] Iteration counting + max limit
- [ ] Stop file mechanism
- [ ] Basic logging to ralph.log
- [ ] Calls claude with working.md prompt
- [ ] Prove the loop works

### Phase 2: JSONL Task Storage
- [ ] Create tasks.jsonl format
- [ ] Create tasks-done.jsonl for archive
- [ ] Helper functions/scripts for task operations
- [ ] Modify working.md to read/write JSONL
- [ ] Outer loop claims tasks from JSONL

### Phase 3: Branch Workflow
- [ ] Branch creation on task claim (`task/<id>-<slug>`)
- [ ] Claude commits freely on branch
- [ ] Squash merge on completion
- [ ] Task ID + summary in squash commit message
- [ ] Branch cleanup

### Phase 4: Role System
- [ ] Role file format (roles/*.md)
- [ ] Trigger configuration (roles.yaml)
- [ ] Trigger evaluation in outer loop
- [ ] Prompt composition (base + role)

### Phase 5: Polish
- [ ] Max iterations per task
- [ ] Stuck task detection + escalation
- [ ] Better error detection (parse output)
- [ ] Iteration output capture (debugging)

---

## Open Questions

1. **Language for outer loop?**
   - Bash: simpler, no dependencies, sufficient for MVP
   - Python: easier for complex logic (role triggers, YAML parsing)
   - Start with bash, migrate to Python if triggers get complex

2. **How does Claude update task status?**
   - Direct JSONL manipulation (sed/jq in bash)
   - Helper script (`./task complete A.1.1`)
   - Both work; helper script is cleaner

3. **Parent task completion?**
   - Implicit: parent is "done" when all children done
   - Explicit: Claude marks parent complete
   - Leaning implicit — less bookkeeping

4. **Failure handling?**
   - Max iterations per task before blocking?
   - Auto-escalate (notification) after N failures?
   - What counts as a "failure" vs "in progress"?

5. **Task creation during iteration?**
   - Claude discovers subtasks → adds to tasks.jsonl
   - Should it auto-set parent's leaf:false?
   - Validation needed? (unique IDs, valid parent exists)

## Resolved Questions

- ~~SQLite vs files?~~ → JSONL files
- ~~log.md for history?~~ → tasks-done.jsonl + git history
- ~~NEXT UP tracking?~~ → outer loop claims tasks, no manual tracking
- ~~Archive completed tasks?~~ → Yes, to tasks-done.jsonl

---

## File Structure (Proposed)

```
ralph-loop/
├── working.md           # base workflow (simplified)
├── learnings.md         # accumulated knowledge (patterns, gotchas)
├── idea.md              # project vision (north star)
│
├── tasks.jsonl          # active tasks (pending, in_progress)
├── tasks-done.jsonl     # completed tasks (append-only archive)
│
├── roles/
│   ├── reviewer.md
│   ├── architect.md
│   ├── debugger.md
│   └── documenter.md
│
├── config/
│   └── roles.yaml       # trigger definitions
│
├── ralph/               # tooling (if using Python)
│   ├── __init__.py
│   ├── loop.py          # outer loop orchestrator
│   ├── tasks.py         # task operations (JSONL helpers)
│   ├── roles.py         # trigger evaluation
│   └── git.py           # branch workflow helpers
│
├── ralph.sh             # entry point (or minimal bash-only version)
└── ralph.log            # iteration log (timestamps, exit codes)
```

**What's gone:**
- `log.md` — replaced by tasks-done.jsonl + git history
- `todo.md` — replaced by tasks.jsonl
- `ralph.db` — not using SQLite, JSONL instead
