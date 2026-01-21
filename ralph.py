#!/usr/bin/env python3
"""ralph.py - external loop with task management"""

import json
import subprocess
import time
import os
from datetime import date
from pathlib import Path

# --- Config ---
MAX_ITERATIONS = 20
POLL_INTERVAL = 5
TASKS_FILE = Path("tasks.jsonl")
DONE_FILE = Path("tasks-done.jsonl")
LOG_FILE = Path("ralph.log")

# --- JSONL helpers ---

def read_tasks():
    """Read all tasks from JSONL file."""
    if not TASKS_FILE.exists():
        return []
    with open(TASKS_FILE) as f:
        return [json.loads(line) for line in f if line.strip()]

def write_tasks(tasks):
    """Write all tasks back to JSONL file."""
    with open(TASKS_FILE, 'w') as f:
        for task in tasks:
            f.write(json.dumps(task) + '\n')

def append_done(task):
    """Append completed task to done file."""
    with open(DONE_FILE, 'a') as f:
        f.write(json.dumps(task) + '\n')

def log(msg):
    """Log to console and file."""
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line)
    with open(LOG_FILE, 'a') as f:
        f.write(line + '\n')

# --- Task operations ---

def get_children(tasks, parent_id):
    """Get direct children of a task (A → A.1, A.2, not A.1.1)."""
    prefix = parent_id + '.'
    parent_depth = parent_id.count('.')
    return [t for t in tasks if t['id'].startswith(prefix)
            and t['id'].count('.') == parent_depth + 1]

def get_next_task(tasks):
    """Find next task to work on.

    Priority:
    1. Active tasks (resume interrupted work)
    2. Pending tasks (new work available)
    3. Split tasks with all children complete (needs verification)
    """
    # First: resume any active task (crash recovery)
    for task in tasks:
        if task.get('status') == 'active':
            return task, 'work'

    # Second: any pending tasks
    for task in tasks:
        if task.get('status') == 'pending':
            return task, 'work'

    # Third: split tasks ready for verification
    for task in tasks:
        if task.get('status') == 'split':
            children = get_children(tasks, task['id'])
            if children and all(c.get('status') == 'complete' for c in children):
                return task, 'verify'

    return None, None

def update_task_status(tasks, task_id, status):
    """Update a task's status in place."""
    for task in tasks:
        if task['id'] == task_id:
            task['status'] = status
            break
    write_tasks(tasks)

def get_task_by_id(tasks, task_id):
    """Find task by ID."""
    for task in tasks:
        if task['id'] == task_id:
            return task
    return None

def get_all_descendants(tasks, parent_id):
    """Get all descendants of a task (children, grandchildren, etc.)."""
    prefix = parent_id + '.'
    return [t for t in tasks if t['id'].startswith(prefix)]

def is_root_task(task_id):
    """Check if task is a root (no dots in ID)."""
    return '.' not in task_id

def archive_task_tree(tasks, task_id, commit_hash):
    """Archive a completed root task and all its descendants.

    Only called for root tasks. Children stay in tasks.jsonl until
    their root parent completes, so Claude can see existing IDs.
    """
    task = get_task_by_id(tasks, task_id)
    if not task:
        return tasks

    # Collect task and all descendants
    to_archive = [task] + get_all_descendants(tasks, task_id)
    to_archive_ids = {t['id'] for t in to_archive}

    # Archive all with completion metadata
    for t in to_archive:
        done_task = {
            **t,
            'completed': date.today().isoformat(),
            'commit': commit_hash
        }
        append_done(done_task)

    # Remove archived tasks from active file
    tasks = [t for t in tasks if t['id'] not in to_archive_ids]
    write_tasks(tasks)

    return tasks

def mark_task_complete(tasks, task_id):
    """Mark a task as complete (but don't archive yet if it has a parent)."""
    for task in tasks:
        if task['id'] == task_id:
            task['status'] = 'complete'
            break
    write_tasks(tasks)
    return tasks

# --- Git operations ---

def git(*args):
    """Run git command, return (exit_code, stdout)."""
    result = subprocess.run(['git'] + list(args), capture_output=True, text=True)
    return result.returncode, result.stdout.strip()

def slugify(text):
    """Convert text to branch-safe slug."""
    slug = text.lower().replace(' ', '-')
    return ''.join(c for c in slug if c.isalnum() or c == '-')[:30]

def create_branch(task_id, title):
    """Create and checkout task branch. If it exists, just check it out."""
    branch = f"task/{task_id}-{slugify(title)}"
    code, _ = git('checkout', '-b', branch)
    if code != 0:
        # Branch exists, just check it out
        git('checkout', branch)
    return branch

def squash_merge(branch, task_id, title):
    """Squash merge branch to main, return commit hash."""
    git('checkout', 'main')
    git('merge', '--squash', branch)

    message = f"[{task_id}] {title}\n\nCompletes: {task_id}"
    git('commit', '-m', message)

    _, commit_hash = git('rev-parse', '--short', 'HEAD')
    git('branch', '-d', branch)

    return commit_hash

# --- Claude execution ---

def run_claude(prompt):
    """Run claude with prompt in print mode (non-interactive)."""
    result = subprocess.run(['claude', '-p', prompt])
    return result.returncode

# --- Role triggers (stub) ---

def evaluate_triggers(task, iteration, mode):
    """Evaluate role triggers, return role name or None."""
    # TODO: implement trigger logic
    # - check branch commit count
    # - check iteration count
    # - check task properties
    # - mode == 'verify' might trigger reviewer role
    return None

def build_prompt(task, mode, role=None):
    """Build prompt based on task and mode.

    mode: 'work' (normal task) or 'verify' (split task, children complete)
    """
    task_id = task['id']
    title = task['title']

    parts = ["Read working.md and execute.", ""]

    # Task context
    parts.append(f"TASK: [{task_id}] {title}")

    # Mode-specific instructions
    if mode == 'verify':
        parts.append("MODE: VERIFY")
        parts.append("All subtasks are complete. Verify the original goal is met.")
        parts.append(f"- If done → mark [{task_id}] as complete")
        parts.append(f"- If gaps remain → add more subtasks")
    else:
        parts.append("MODE: WORK")
        parts.append(f"- If doable → complete the task")
        parts.append(f"- If too big → split into subtasks")

    # Optional role
    if role:
        parts.append("")
        parts.append(f"ROLE: {role}")

    return "\n".join(parts)

# --- Main loop ---

def main():
    log("Ralph loop starting")

    while True:
        # Check stop signal
        if Path('.stop').exists():
            log("Stop signal received")
            Path('.stop').unlink()
            break

        tasks = read_tasks()

        # 1. POLL for task
        task, mode = get_next_task(tasks)
        if not task:
            log("No pending tasks, sleeping...")
            time.sleep(POLL_INTERVAL)
            continue

        task_id = task['id']
        title = task['title']
        log(f"=== [{mode.upper()}] [{task_id}] {title} ===")

        # 2. CLAIM (mark as active)
        update_task_status(tasks, task_id, 'active')

        # 3. BRANCH
        branch = create_branch(task_id, title)
        log(f"Created branch: {branch}")

        # 4. WORK LOOP
        iterations = 0
        task_done = False

        while iterations < MAX_ITERATIONS:
            iterations += 1
            log(f"--- Iteration {iterations} ---")

            # Evaluate role triggers
            role = evaluate_triggers(task, iterations, mode)
            prompt = build_prompt(task, mode, role)

            # Run Claude
            exit_code = run_claude(prompt)

            if exit_code != 0:
                log(f"Claude exited with code {exit_code}, retrying...")
                time.sleep(5)
                continue

            # Reload tasks and check status
            tasks = read_tasks()
            current = get_task_by_id(tasks, task_id)

            if not current:
                # Task was removed? Shouldn't happen, but handle it
                log(f"Task {task_id} disappeared from file")
                break

            status = current.get('status')

            if status == 'complete':
                log(f"Task {task_id} marked complete")
                task_done = True
                break
            elif status == 'split':
                log(f"Task {task_id} was split into subtasks")
                task_done = True  # This task is "done" (decomposed)
                break

            # Still active, continue working
            time.sleep(2)

        if not task_done:
            log(f"Task {task_id} not complete after {iterations} iterations")

        # 5. COMPLETE - squash merge and maybe archive
        tasks = read_tasks()
        current = get_task_by_id(tasks, task_id)

        if current and current.get('status') == 'complete':
            commit_hash = squash_merge(branch, task_id, title)

            if is_root_task(task_id):
                # Root task complete - archive entire tree
                archive_task_tree(tasks, task_id, commit_hash)
                log(f"=== Completed & archived: [{task_id}] {title} ({commit_hash}) ===")
            else:
                # Child task complete - just record commit, don't archive yet
                current['commit'] = commit_hash
                write_tasks(tasks)
                log(f"=== Completed: [{task_id}] {title} ({commit_hash}) ===")

        elif current and current.get('status') == 'split':
            # Task was split - merge what we have, but don't archive
            # Children will be worked on in subsequent iterations
            git('checkout', 'main')
            code, _ = git('diff', '--cached', '--quiet')
            if code != 0:  # There are staged changes
                git('merge', '--squash', branch)
                git('commit', '-m', f"[{task_id}] Split into subtasks")
            git('branch', '-D', branch)  # Force delete even if not fully merged
            log(f"=== Split: [{task_id}] - children pending ===")

        else:
            # Not complete, preserve branch for review
            git('checkout', 'main')
            log(f"Branch {branch} preserved for review")

if __name__ == '__main__':
    main()
