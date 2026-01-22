# Willie Loop

An external loop for Claude Code that breaks work into small, focused iterations.

## How It Works

```
willie.py (outer loop)
    │
    ├─ picks task from tasks.jsonl
    ├─ creates branch
    ├─ calls: claude "Read working.md and execute. TASK: [...] MODE: [...]"
    ├─ Claude works, commits, updates task status
    ├─ squash merges on completion
    └─ repeats
```

## Getting Started

### 1. Initialize Your Project

```bash
./init.sh
```

This starts an interactive session where Claude helps you define:
- **Goals** — What are you building? What problem does it solve?
- **Constraints** — Development rules (TDD? Type hints? Code style?)
- **Tech Stack** — Languages, frameworks, dependencies
- **Success Criteria** — How do you know when it's done?

### 2. Create Your First Task

Add to `tasks.jsonl`:
```json
{"id":"A","title":"your first task","status":"pending"}
```

### 3. Run the Loop

```bash
./willie           # Normal mode
./willie -c        # With console input (TUI)
./willie -d        # Daemon mode (poll forever)
./willie -cd       # Both
```

The wrapper script auto-creates a virtual environment on first run.

Or run manually:
```
claude "Read working.md and execute. TASK: [A] your first task. MODE: WORK"
```

## Core Files

| File | Purpose |
|------|---------|
| `willie.py` | External loop orchestrator |
| `working.md` | Workflow instructions Claude reads each iteration |
| `idea.md` | Project vision, goals, constraints |
| `learnings.md` | Accumulated patterns and gotchas |
| `tasks.jsonl` | Active tasks |
| `tasks-done.jsonl` | Completed tasks archive |

## Task Flow

```
pending → active → complete
                → split (creates subtasks)
                    ↓
              [children complete]
                    ↓
              verify → complete (or more subtasks)
```

## Key Concepts

- **Small tasks** — ~20-50 lines, 1-3 files
- **Research is work** — Clarifying IS progress
- **Split when big** — A → A.1, A.2, A.3
- **Verify when done** — Parent re-evaluated after children complete
