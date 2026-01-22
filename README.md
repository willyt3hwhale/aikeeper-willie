# Willie Loop

![Groundskeeper Willie](https://upload.wikimedia.org/wikipedia/en/d/dc/GroundskeeperWillie.png)

An external orchestration loop for Claude Code with task tracking, branch-per-task git workflow, and interactive console.

Based on the [Ralph Wiggum](https://github.com/anthropics/claude-code/blob/main/.claude/skills/ralph-wiggum/ralph-loop.md) prompting technique — but run externally with persistent task state and clean git history.

## How It Works

```
./willie (outer loop)
    │
    ├─ picks task from .willie/tasks.jsonl
    ├─ creates branch
    ├─ calls: claude "Read .willie/working.md and execute. TASK: [...] MODE: [...]"
    ├─ Claude works, commits, updates task status
    ├─ squash merges on completion
    └─ repeats
```

## Requirements

- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) installed and authenticated
- Python 3.8+
- Git

## Getting Started

### 1. Initialize Your Project

```bash
./willie init
```

This starts an interactive session where Claude helps you define `.willie/idea.md`:
- **Goals** — What are you building? What problem does it solve?
- **Constraints** — Development rules (TDD? Type hints? Code style?)
- **Tech Stack** — Languages, frameworks, dependencies
- **Success Criteria** — How do you know when it's done?

### 2. Run the Loop

```bash
./willie           # Normal mode
./willie -c        # With console input (TUI)
./willie -d        # Daemon mode (poll forever)
./willie -cd       # Both
```

Willie reads `.willie/idea.md`, creates tasks automatically, and works through them.

The wrapper script auto-creates a virtual environment on first run.

### Manual Task Creation (Optional)

You can also add tasks directly to `.willie/tasks.jsonl`:
```json
{"id":"A","title":"your first task","status":"pending"}
```

## Project Structure

All Willie files live in `.willie/` to keep your project root clean:

```
your-project/
├── willie                  # Entry point (run this)
├── .willie/
│   ├── willie.py           # Main loop orchestrator
│   ├── working.md          # Workflow instructions
│   ├── idea.md             # Project vision & goals
│   ├── learnings.md        # Accumulated knowledge
│   ├── tasks.jsonl         # Active tasks
│   └── tasks-done.jsonl    # Completed tasks archive
└── (your project files)
```

### Cleanup

When your project is complete, remove Willie:
```bash
rm -rf .willie willie
```

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
