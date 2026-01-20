# Ralph Loop Prompting

A workflow system for iterative AI agent sessions. Ralph loops give Claude Code a structured approach to tackling projects across multiple iterations, with built-in mechanisms for research, task decomposition, and knowledge accumulation.

## Core Files

- **working.md** - The main workflow instructions read each iteration
- **idea.md** - Project vision template (the "north star")
- **log.md** - Session history and NEXT UP task
- **learnings.md** - Accumulated patterns and gotchas

## Key Concepts

**Research before implementation** - First iteration is always understanding the problem space, not coding.

**Task readiness** - Tasks must be small, concrete, and fully understood before implementation. If not ready, research or split.

**Recursive splitting** - Large tasks get broken into sub-tasks, which can be split further as needed.

**Knowledge capture** - Patterns and gotchas get documented in learnings.md for future iterations.

## Usage

1. Clone this repo as a starting point for a new project
2. Fill in idea.md with your project vision
3. Run ralph loops via the `/ralph-wiggum:ralph-loop` skill in Claude Code
4. Each iteration reads working.md, picks a task, and makes incremental progress
