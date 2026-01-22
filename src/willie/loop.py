"""Willie Loop - main loop logic."""

import json
import subprocess
import sys
import threading
import time
import os
from datetime import date
from pathlib import Path

# --- Config ---
MAX_ITERATIONS = 20
POLL_INTERVAL = 5

# All willie files live in .willie/ directory (in current working directory)
WILLIE_DIR = Path(".willie")
TASKS_FILE = WILLIE_DIR / "tasks.jsonl"
DONE_FILE = WILLIE_DIR / "tasks-done.jsonl"
LOG_FILE = WILLIE_DIR / "willie.log"
INBOX_FILE = Path("inbox.txt")  # inbox stays at project root for easy access

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
    """Log to console and file. Works with TUI (patch_stdout handles redirection)."""
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line)
    with open(LOG_FILE, 'a') as f:
        f.write(line + '\n')

def read_inbox():
    """Read and clear the inbox file. Returns content or None."""
    if not INBOX_FILE.exists():
        return None
    content = INBOX_FILE.read_text().strip()
    if not content:
        return None
    INBOX_FILE.unlink()  # Clear after reading
    return content

# --- Console input (TUI) ---

console_input_queue = []
console_lock = threading.Lock()
console_quit = False
prompt_session = None
stdout_context = None

def get_console_input():
    """Get and clear any pending console input."""
    with console_lock:
        if not console_input_queue:
            return None
        # Join all queued messages
        result = '\n'.join(console_input_queue)
        console_input_queue.clear()
        return result

def console_reader_thread():
    """Background thread to read console input with prompt_toolkit."""
    global prompt_session, console_quit
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.formatted_text import HTML
        prompt_session = PromptSession()

        while True:
            try:
                line = prompt_session.prompt(HTML('<ansigreen>willie></ansigreen> '))
                if line.strip():
                    with console_lock:
                        console_input_queue.append(line.strip())
                    tui_print(f"[queued] {line.strip()}")
            except EOFError:
                tui_print("Console closed. Shutting down...")
                console_quit = True
                break
            except KeyboardInterrupt:
                tui_print("Interrupted. Shutting down...")
                console_quit = True
                break
    except ImportError:
        print("prompt_toolkit not installed. Run: pip install prompt_toolkit")

def strip_ansi(text):
    """Remove ANSI escape codes from text."""
    import re
    return re.sub(r'\033\[[0-9;]*m', '', text)

def tui_print(msg, ansi=False):
    """Print message above the input line."""
    # Always log to file (strip ANSI codes)
    clean_msg = strip_ansi(msg) if ansi else msg
    if clean_msg.strip():
        with open(LOG_FILE, 'a') as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {clean_msg}\n")

    if ansi and stdout_context:
        # Use prompt_toolkit's ANSI-aware printing
        try:
            from prompt_toolkit import print_formatted_text
            from prompt_toolkit.formatted_text import ANSI
            print_formatted_text(ANSI(msg))
            return
        except ImportError:
            pass
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")

def start_console_reader():
    """Start the TUI console reader."""
    try:
        from prompt_toolkit.patch_stdout import patch_stdout
        global stdout_context
        stdout_context = patch_stdout()
        stdout_context.__enter__()

        thread = threading.Thread(target=console_reader_thread, daemon=True)
        thread.start()
        tui_print("Console input enabled. Type messages at the prompt.")
    except ImportError:
        print("prompt_toolkit not installed. Run: pip install prompt_toolkit")
        print("Falling back to inbox.txt only.")

def stop_console_reader():
    """Clean up the TUI console reader."""
    global stdout_context
    if stdout_context:
        try:
            stdout_context.__exit__(None, None, None)
        except Exception:
            pass  # Ignore cleanup errors
        stdout_context = None
        # Remind user about log file (print after patch_stdout closed)
        print(f"\nFull log: {LOG_FILE}")

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

def get_current_branch():
    """Get the current git branch name."""
    _, branch = git('branch', '--show-current')
    return branch

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

def squash_merge(branch, task_id, title, base_branch):
    """Squash merge branch to base_branch, return commit hash."""
    git('checkout', base_branch)
    git('merge', '--squash', branch)

    message = f"[{task_id}] {title}\n\nCompletes: {task_id}"
    git('commit', '-m', message)

    _, commit_hash = git('rev-parse', '--short', 'HEAD')

    # Clean up branch (local and remote)
    git('branch', '-D', branch)
    git('push', 'origin', '--delete', branch)  # ignore if not pushed

    return commit_hash

# --- Claude execution ---

def get_session_dir():
    """Get Claude's session directory for this project."""
    cwd = os.getcwd().replace('/', '-')
    return Path.home() / '.claude' / 'projects' / cwd


def run_claude(prompt):
    """Run claude, streaming output by watching session files."""
    import json as json_module
    import glob

    session_dir = get_session_dir()

    # Ensure session directory exists (Claude creates it, but we need to watch it)
    session_dir.mkdir(parents=True, exist_ok=True)

    # Note existing session files before starting
    existing = set(glob.glob(str(session_dir / '*.jsonl')))

    # Start Claude (no streaming flags needed - we read session files)
    process = subprocess.Popen(
        ['claude', '-p', prompt, '--dangerously-skip-permissions'],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Find the new session file (wait up to 10 seconds)
    new_session = None
    for _ in range(100):
        current = set(glob.glob(str(session_dir / '*.jsonl')))
        new_files = current - existing
        if new_files:
            new_session = max(new_files, key=lambda f: os.path.getmtime(f))
            break
        time.sleep(0.1)

    if not new_session:
        # Session file not found - Claude might use a different session dir
        # Just wait for the process without streaming
        log("(streaming unavailable, waiting for Claude...)")
        process.wait()
        return process.returncode

    # Track what we've already printed
    printed_messages = set()
    last_size = 0

    while process.poll() is None:
        try:
            current_size = os.path.getsize(new_session)
            if current_size > last_size:
                with open(new_session, 'r') as f:
                    f.seek(last_size)
                    new_content = f.read()
                    last_size = current_size

                    for line in new_content.strip().split('\n'):
                        if not line:
                            continue
                        try:
                            msg = json_module.loads(line)
                            msg_type = msg.get('type')

                            # Colors
                            CYAN = '\033[36m'
                            YELLOW = '\033[33m'
                            DIM = '\033[2m'
                            RESET = '\033[0m'

                            def cprint(s):
                                tui_print(s, ansi=True)

                            def format_tool_result(content, max_lines=3):
                                """Format tool result, showing first N lines."""
                                if not content:
                                    return None
                                lines = str(content).split('\n')
                                if len(lines) <= max_lines:
                                    return '\n'.join(f"    {line}" for line in lines if line.strip())
                                shown = '\n'.join(f"    {line}" for line in lines[:max_lines] if line.strip())
                                return f"{shown}\n    {DIM}... ({len(lines) - max_lines} more lines){RESET}"

                            # Tool results (from user messages)
                            if msg_type == 'user':
                                content = msg.get('message', {}).get('content', [])
                                for block in content:
                                    if not isinstance(block, dict):
                                        continue
                                    if block.get('type') == 'tool_result':
                                        result = block.get('content', '')
                                        if result:
                                            formatted = format_tool_result(result)
                                            if formatted:
                                                cprint(f"{DIM}{formatted}{RESET}")

                            # Assistant messages
                            if msg_type == 'assistant':
                                content = msg.get('message', {}).get('content', [])
                                for block in content:
                                    if not isinstance(block, dict):
                                        continue
                                    if block.get('type') == 'text':
                                        text = block.get('text', '')
                                        if text:
                                            cprint(f"{CYAN}{text}{RESET}")
                                    elif block.get('type') == 'tool_use':
                                        tool = block.get('name', 'unknown')
                                        inp = block.get('input', {})
                                        # Format tool args briefly
                                        if tool == 'Read':
                                            arg = inp.get('file_path', '')
                                            cprint(f"{YELLOW}  → {tool}{RESET} {DIM}{arg}{RESET}")
                                        elif tool == 'Write':
                                            arg = inp.get('file_path', '')
                                            cprint(f"{YELLOW}  → {tool}{RESET} {DIM}{arg}{RESET}")
                                        elif tool == 'Edit':
                                            arg = inp.get('file_path', '')
                                            cprint(f"{YELLOW}  → {tool}{RESET} {DIM}{arg}{RESET}")
                                        elif tool == 'Bash':
                                            arg = inp.get('command', '')[:60]
                                            cprint(f"{YELLOW}  → {tool}{RESET} {DIM}{arg}{RESET}")
                                        elif tool == 'Glob':
                                            arg = inp.get('pattern', '')
                                            cprint(f"{YELLOW}  → {tool}{RESET} {DIM}{arg}{RESET}")
                                        elif tool == 'Grep':
                                            arg = inp.get('pattern', '')
                                            cprint(f"{YELLOW}  → {tool}{RESET} {DIM}{arg}{RESET}")
                                        else:
                                            cprint(f"{YELLOW}  → {tool}{RESET}")

                        except json_module.JSONDecodeError:
                            pass
        except (OSError, IOError):
            pass
        time.sleep(0.3)

    # Final read to catch anything written at the end
    CYAN = '\033[36m'
    RESET = '\033[0m'
    try:
        with open(new_session, 'r') as f:
            f.seek(last_size)
            final_content = f.read()
            for line in final_content.strip().split('\n'):
                if not line:
                    continue
                try:
                    msg = json_module.loads(line)
                    if msg.get('type') == 'assistant':
                        content = msg.get('message', {}).get('content', [])
                        for block in content:
                            if block.get('type') == 'text':
                                text = block.get('text', '')
                                if text:
                                    tui_print(f"{CYAN}{text}{RESET}", ansi=True)
                except json_module.JSONDecodeError:
                    pass
    except (OSError, IOError):
        pass

    tui_print("", ansi=True)  # blank line
    process.wait()
    return process.returncode

# --- Role triggers (stub) ---

def evaluate_triggers(task, iteration, mode):
    """Evaluate role triggers, return role name or None."""
    # TODO: implement trigger logic
    # - check branch commit count
    # - check iteration count
    # - check task properties
    # - mode == 'verify' might trigger reviewer role
    return None

def build_prompt(task, mode, role=None, user_input=None):
    """Build prompt based on task and mode.

    mode: 'work' (normal task) or 'verify' (split task, children complete)
    """
    task_id = task['id']
    title = task['title']

    parts = ["Read .willie/working.md and execute.", ""]

    # User input (highest priority context)
    if user_input:
        parts.append("USER INPUT (address this first):")
        parts.append(user_input)
        parts.append("")

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


def build_completion_check_prompt():
    """Build prompt for verifying project completion when task list is empty."""
    parts = [
        "The task list is empty. Verify the project is complete.",
        "",
        "## Instructions",
        "1. Read .willie/idea.md to understand the project vision and success criteria",
        "2. Review the codebase to assess what has been built",
        "3. Compare against the goals and success criteria in .willie/idea.md",
        "",
        "## Decision",
        "- If the project meets all success criteria → respond with: PROJECT_COMPLETE",
        "- If gaps remain → add new tasks to .willie/tasks.jsonl for missing work",
        "",
        "## Task Format",
        'Tasks MUST include status field: {"id": "1", "title": "...", "status": "pending"}',
        "",
        "Be thorough. Check that all goals are met, not just some.",
    ]
    return "\n".join(parts)

# --- Main loop ---

def main(console=False, daemon=False):
    """Run the Willie loop.

    Args:
        console: Enable interactive console input (TUI)
        daemon: Run as daemon (poll forever instead of exiting when idle)
    """
    base_branch = get_current_branch()
    log(f"Willie loop starting (base branch: {base_branch})")

    if console:
        start_console_reader()

    waiting_logged = False

    while True:
        # Check stop signals
        if Path('.stop').exists():
            log("Stop signal received")
            Path('.stop').unlink()
            break

        if console and console_quit:
            log("Console quit signal received")
            break

        tasks = read_tasks()

        # 1. POLL for task
        task, mode = get_next_task(tasks)
        if not task:
            # Check for user input that might create tasks
            user_input = get_console_input() if console else None
            inbox_input = read_inbox()
            if inbox_input:
                user_input = f"{inbox_input}\n\n{user_input}" if user_input else inbox_input

            if user_input:
                # User input with no tasks - let Claude interpret and create tasks
                log(f"Processing user input: {user_input[:50]}...")
                waiting_logged = False
                prompt = f"""No active tasks. User says:

{user_input}

If this is a task request, add it to tasks.jsonl.
If it's a question, answer it briefly.
If it's feedback about the project, incorporate it appropriately."""
                run_claude(prompt)
                continue

            if daemon:
                # Daemon mode: wait for new tasks (log once)
                if not waiting_logged:
                    log("No tasks. Waiting... (type a message or add tasks)")
                    waiting_logged = True
                time.sleep(POLL_INTERVAL)
                continue
            else:
                # Normal mode: verify project completion against idea.md
                log("Task list empty. Verifying project completion...")

                prompt = build_completion_check_prompt()
                exit_code = run_claude(prompt)

                if exit_code != 0:
                    log(f"Claude exited with code {exit_code}, retrying...")
                    time.sleep(5)
                    continue

                # Check if new tasks were added
                tasks = read_tasks()
                if tasks:
                    log("New tasks identified. Continuing...")
                    continue
                else:
                    log("Project complete. Exiting.")
                    break

        task_id = task['id']
        title = task['title']
        log(f"=== [{mode.upper()}] [{task_id}] {title} ===")
        waiting_logged = False

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

            # Check for user input (inbox file or console)
            user_input = read_inbox()
            if console:
                console = get_console_input()
                if console:
                    if user_input:
                        user_input = f"{user_input}\n\n{console}"
                    else:
                        user_input = console
            if user_input:
                log(f"User input received: {user_input[:50]}...")

            # Evaluate role triggers
            role = evaluate_triggers(task, iterations, mode)
            prompt = build_prompt(task, mode, role, user_input)

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
            commit_hash = squash_merge(branch, task_id, title, base_branch)

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
            git('checkout', base_branch)
            code, _ = git('diff', '--cached', '--quiet')
            if code != 0:  # There are staged changes
                git('merge', '--squash', branch)
                git('commit', '-m', f"[{task_id}] Split into subtasks")
            # Clean up branch (local and remote)
            git('branch', '-D', branch)
            git('push', 'origin', '--delete', branch)
            log(f"=== Split: [{task_id}] - children pending ===")

        else:
            # Not complete, preserve branch for review
            git('checkout', base_branch)
            log(f"Branch {branch} preserved for review")

