"""Willie Loop - main loop logic."""

import fcntl
import json
import re
import shutil
import subprocess
import sys
import threading
import time
import os
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

# --- Task Status Constants ---
class TaskStatus:
    PENDING = 'pending'
    ACTIVE = 'active'
    COMPLETE = 'complete'
    SPLIT = 'split'
    VALID = {PENDING, ACTIVE, COMPLETE, SPLIT}

# --- Config ---
MAX_ITERATIONS = 20  # Max iterations per task before giving up
POLL_INTERVAL = 5  # Seconds between polling in daemon mode
CLAUDE_TIMEOUT = 3600  # Max seconds to wait for Claude (1 hour)
SESSION_WAIT_TIMEOUT = 10  # Seconds to wait for Claude session file
SESSION_CHECK_INTERVAL = 0.1  # Seconds between session file checks
TOOL_OUTPUT_PREVIEW_LINES = 3  # Lines to show from tool output
COMMAND_PREVIEW_LENGTH = 60  # Characters to show from bash commands
API_RETRY_DELAYS = [5, 15, 30, 60]  # Exponential backoff for API errors
RATE_LIMIT_WAIT = 300  # 5 minutes wait for rate limits

# --- Error Types ---
class ClaudeError:
    NONE = 'none'
    API_ERROR = 'api_error'  # 500, transient errors
    RATE_LIMIT = 'rate_limit'  # Too many requests
    TOKEN_LIMIT = 'token_limit'  # Out of tokens/credits
    TIMEOUT = 'timeout'
    UNKNOWN = 'unknown'

# All willie files live in .willie/ directory (in current working directory)
WILLIE_DIR = Path(".willie")
TASKS_FILE = WILLIE_DIR / "tasks.jsonl"
DONE_FILE = WILLIE_DIR / "tasks-done.jsonl"
LOG_FILE = WILLIE_DIR / "willie.log"
INBOX_FILE = Path("inbox.txt")  # inbox stays at project root for easy access
IDEA_FILE = WILLIE_DIR / "idea.md"
WORKING_FILE = WILLIE_DIR / "working.md"

# --- Project State Detection ---

def is_idea_template() -> bool:
    """Check if idea.md is still the unfilled template.

    Returns True if idea.md only contains template placeholders (HTML comments)
    with no actual content filled in.
    """
    if not IDEA_FILE.exists():
        return True

    content = IDEA_FILE.read_text()
    # Strip HTML comments and whitespace
    stripped = re.sub(r'<!--.*?-->', '', content, flags=re.DOTALL)
    stripped = re.sub(r'#.*\n', '', stripped)  # Remove headers
    stripped = stripped.strip()

    # If nothing left, it's still the template
    return len(stripped) == 0


def is_project_never_started() -> bool:
    """Check if project was defined but never started.

    Returns True if idea.md has content but no tasks exist and no work
    has been completed (tasks-done.jsonl missing or empty).
    """
    if is_idea_template():
        return False  # Not even defined yet

    # Check if any work has been done
    if DONE_FILE.exists() and DONE_FILE.stat().st_size > 0:
        return False  # Has completed tasks

    # Check if tasks exist
    if TASKS_FILE.exists() and TASKS_FILE.stat().st_size > 0:
        return False  # Has pending tasks

    return True  # Idea defined but no tasks created


def create_bootstrap_task() -> None:
    """Create initial bootstrap task to break down idea.md into tasks."""
    bootstrap = {"id": "0", "title": "Read idea.md and create initial task breakdown", "status": "pending"}
    with open(TASKS_FILE, 'w') as f:
        f.write(json.dumps(bootstrap) + '\n')


def build_init_prompt() -> str:
    """Build prompt for initializing idea.md when project wasn't set up."""
    return f"""The project was initialized but idea.md was never filled in.

Read {WORKING_FILE} to understand how we work, then help define {IDEA_FILE}.

Use the AskUserQuestion tool to ask questions one at a time until you're 99% sure about what they want to build.

Cover these topics:
- Goals: What are they building? What problem does it solve?
- Tech stack: Languages, frameworks, key dependencies
- Development workflow: TDD? Testing requirements? Code style?
- Constraints: Any rules, limitations, or standards
- Success criteria: How do we know when it's done?

After gathering all answers, write the complete {IDEA_FILE} file.

Then create an initial task in tasks.jsonl based on the project goals.
Use the Write tool (NOT bash/echo) to write the task:
{{"id": "1", "title": "Set up project structure", "status": "pending"}}"""


# --- JSONL helpers ---

def validate_task(task: Dict[str, Any]) -> Dict[str, Any]:
    """Validate task has required fields. Returns task or raises ValueError."""
    required = {'id', 'title', 'status'}
    missing = required - set(task.keys())
    if missing:
        raise ValueError(f"Invalid task: missing {missing}. Got: {task}")
    if task['status'] not in TaskStatus.VALID:
        raise ValueError(f"Invalid status '{task['status']}'. Valid: {TaskStatus.VALID}")
    return task

def read_tasks() -> List[Dict[str, Any]]:
    """Read all tasks from JSONL file with file locking."""
    if not TASKS_FILE.exists():
        return []
    tasks = []
    with open(TASKS_FILE) as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_SH)  # Shared lock for reading
        try:
            for line_num, line in enumerate(f, 1):
                if not line.strip():
                    continue
                try:
                    task = json.loads(line)
                    validate_task(task)
                    tasks.append(task)
                except json.JSONDecodeError as e:
                    log(f"WARNING: Invalid JSON on line {line_num}: {e}")
                except ValueError as e:
                    log(f"WARNING: {e}")
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    return tasks

def write_tasks(tasks: List[Dict[str, Any]]) -> None:
    """Write all tasks back to JSONL file with file locking (atomic write)."""
    # Write to temp file first, then rename (atomic on POSIX)
    temp_file = TASKS_FILE.with_suffix('.jsonl.tmp')
    with open(temp_file, 'w') as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)  # Exclusive lock for writing
        try:
            for task in tasks:
                f.write(json.dumps(task) + '\n')
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    temp_file.rename(TASKS_FILE)  # Atomic rename

def append_done(task: Dict[str, Any]) -> None:
    """Append completed task to done file with file locking."""
    with open(DONE_FILE, 'a') as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            f.write(json.dumps(task) + '\n')
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)

def log(msg: str) -> None:
    """Log to console and file. Works with TUI (patch_stdout handles redirection)."""
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line)
    with open(LOG_FILE, 'a') as f:
        f.write(line + '\n')

def read_inbox() -> Optional[str]:
    """Read and clear the inbox file. Returns content or None."""
    if not INBOX_FILE.exists():
        return None
    try:
        content = INBOX_FILE.read_text().strip()
        if not content:
            return None
        INBOX_FILE.unlink()  # Clear after reading
        return content
    except OSError as e:
        log(f"WARNING: Error reading inbox: {e}")
        return None

# --- Console input (TUI) ---

console_input_queue: List[str] = []
console_lock = threading.Lock()
console_quit = False
prompt_session: Any = None
stdout_context: Any = None

def get_console_input() -> Optional[str]:
    """Get and clear any pending console input."""
    with console_lock:
        if not console_input_queue:
            return None
        # Join all queued messages
        result = '\n'.join(console_input_queue)
        console_input_queue.clear()
        return result

def console_reader_thread() -> None:
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

def strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text."""
    import re
    return re.sub(r'\033\[[0-9;]*m', '', text)

def tui_print(msg: str, ansi: bool = False) -> None:
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

def start_console_reader() -> None:
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

def stop_console_reader() -> None:
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

def get_children(tasks: List[Dict[str, Any]], parent_id: str) -> List[Dict[str, Any]]:
    """Get direct children of a task (A → A.1, A.2, not A.1.1)."""
    prefix = parent_id + '.'
    parent_depth = parent_id.count('.')
    return [t for t in tasks if t['id'].startswith(prefix)
            and t['id'].count('.') == parent_depth + 1]

def get_next_task(tasks: List[Dict[str, Any]]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Find next task to work on.

    Priority:
    1. Active tasks (resume interrupted work)
    2. Pending tasks (new work available)
    3. Split tasks with all children complete (needs verification)
    """
    # First: resume any active task (crash recovery)
    for task in tasks:
        if task.get('status') == TaskStatus.ACTIVE:
            return task, 'work'

    # Second: any pending tasks
    for task in tasks:
        if task.get('status') == TaskStatus.PENDING:
            return task, 'work'

    # Third: split tasks ready for verification
    for task in tasks:
        if task.get('status') == TaskStatus.SPLIT:
            children = get_children(tasks, task['id'])
            if children and all(c.get('status') == TaskStatus.COMPLETE for c in children):
                return task, 'verify'

    return None, None

def update_task_status(tasks: List[Dict[str, Any]], task_id: str, status: str) -> None:
    """Update a task's status in place."""
    for task in tasks:
        if task['id'] == task_id:
            task['status'] = status
            break
    write_tasks(tasks)

def get_task_by_id(tasks: List[Dict[str, Any]], task_id: str) -> Optional[Dict[str, Any]]:
    """Find task by ID."""
    for task in tasks:
        if task['id'] == task_id:
            return task
    return None

def get_all_descendants(tasks: List[Dict[str, Any]], parent_id: str) -> List[Dict[str, Any]]:
    """Get all descendants of a task (children, grandchildren, etc.)."""
    prefix = parent_id + '.'
    return [t for t in tasks if t['id'].startswith(prefix)]

def is_root_task(task_id: str) -> bool:
    """Check if task is a root (no dots in ID)."""
    return '.' not in task_id

def archive_task_tree(tasks: List[Dict[str, Any]], task_id: str, commit_hash: str) -> List[Dict[str, Any]]:
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

def mark_task_complete(tasks: List[Dict[str, Any]], task_id: str) -> List[Dict[str, Any]]:
    """Mark a task as complete (but don't archive yet if it has a parent)."""
    for task in tasks:
        if task['id'] == task_id:
            task['status'] = TaskStatus.COMPLETE
            break
    write_tasks(tasks)
    return tasks

# --- Git operations ---

def git(*args: str, quiet: bool = False) -> Tuple[int, str, str]:
    """Run git command, return (exit_code, stdout, stderr). Set quiet=True to suppress warnings."""
    result = subprocess.run(['git'] + list(args), capture_output=True, text=True)
    if result.returncode != 0 and result.stderr and not quiet:
        log(f"Git warning: {result.stderr.strip()}")
    return result.returncode, result.stdout.strip(), result.stderr.strip()

def has_remote(name: str = 'origin') -> bool:
    """Check if a remote exists."""
    code, _, _ = git('remote', 'get-url', name, quiet=True)
    return code == 0

def check_git_repo() -> bool:
    """Check if we're in a git repository."""
    code, _, _ = git('rev-parse', '--git-dir')
    return code == 0

def get_current_branch() -> str:
    """Get the current git branch name."""
    code, branch, stderr = git('branch', '--show-current')
    if code != 0 or not branch:
        log(f"ERROR: Could not determine current branch. Are you in a git repo?")
        if stderr:
            log(f"  Git error: {stderr}")
        sys.exit(1)
    return branch

def slugify(text: str) -> str:
    """Convert text to branch-safe slug."""
    slug = text.lower().replace(' ', '-')
    return ''.join(c for c in slug if c.isalnum() or c == '-')[:30]

def create_branch(task_id: str, title: str) -> str:
    """Create and checkout task branch. If it exists, just check it out."""
    branch = f"task/{task_id}-{slugify(title)}"
    code, _, _ = git('checkout', '-b', branch)
    if code != 0:
        # Branch exists, just check it out
        git('checkout', branch)
    return branch

def squash_merge(branch: str, task_id: str, title: str, base_branch: str) -> str:
    """Squash merge branch to base_branch, return commit hash."""
    git('checkout', base_branch)
    git('merge', '--squash', branch)

    message = f"[{task_id}] {title}\n\nCompletes: {task_id}"
    git('commit', '-m', message)

    _, commit_hash, _ = git('rev-parse', '--short', 'HEAD')

    # Clean up branch (local and remote)
    code, _, stderr = git('branch', '-D', branch, quiet=True)
    if code != 0 and 'cannot delete branch' not in stderr:
        log(f"WARNING: Failed to delete local branch {branch}: {stderr}")

    if has_remote():
        code, _, stderr = git('push', 'origin', '--delete', branch, quiet=True)
        if code != 0 and 'remote ref does not exist' not in stderr:
            log(f"WARNING: Failed to delete remote branch {branch}: {stderr}")

    return commit_hash

# --- Claude execution ---

def check_claude_installed() -> bool:
    """Check if Claude CLI is installed."""
    return shutil.which('claude') is not None

def get_session_dir() -> Path:
    """Get Claude's session directory for this project."""
    cwd = os.getcwd().replace('/', '-')
    return Path.home() / '.claude' / 'projects' / cwd


def detect_error_type(stderr: str) -> Tuple[str, str]:
    """Parse stderr to detect error type. Returns (error_type, message)."""
    stderr_lower = stderr.lower()
    if not stderr.strip():
        return ClaudeError.NONE, ''
    if 'rate limit' in stderr_lower or '429' in stderr:
        return ClaudeError.RATE_LIMIT, stderr
    if 'insufficient' in stderr_lower or 'credit' in stderr_lower or 'quota' in stderr_lower:
        return ClaudeError.TOKEN_LIMIT, stderr
    if '500' in stderr or 'internal server error' in stderr_lower or 'api_error' in stderr_lower:
        return ClaudeError.API_ERROR, stderr
    if 'timeout' in stderr_lower:
        return ClaudeError.TIMEOUT, stderr
    return ClaudeError.UNKNOWN, stderr


def run_claude(prompt: str) -> Tuple[int, str, str]:
    """Run claude, streaming output by watching session files.
    Returns (exit_code, error_type, error_message)."""
    import json as json_module
    import glob

    session_dir = get_session_dir()

    # Ensure session directory exists (Claude creates it, but we need to watch it)
    session_dir.mkdir(parents=True, exist_ok=True)

    # Note existing session files before starting
    existing = set(glob.glob(str(session_dir / '*.jsonl')))

    # Capture stderr for error detection
    stderr_lines: List[str] = []

    def read_stderr(pipe):
        for line in iter(pipe.readline, ''):
            stderr_lines.append(line)
        pipe.close()

    # Start Claude (no streaming flags needed - we read session files)
    process = subprocess.Popen(
        ['claude', '-p', prompt, '--dangerously-skip-permissions'],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )

    # Read stderr in background thread
    stderr_thread = threading.Thread(target=read_stderr, args=(process.stderr,))
    stderr_thread.daemon = True
    stderr_thread.start()

    # Find the new session file
    new_session = None
    wait_iterations = int(SESSION_WAIT_TIMEOUT / SESSION_CHECK_INTERVAL)
    for _ in range(wait_iterations):
        current = set(glob.glob(str(session_dir / '*.jsonl')))
        new_files = current - existing
        if new_files:
            new_session = max(new_files, key=lambda f: os.path.getmtime(f))
            break
        time.sleep(SESSION_CHECK_INTERVAL)

    if not new_session:
        # Session file not found - Claude might use a different session dir
        # Just wait for the process without streaming (with timeout)
        log("(streaming unavailable, waiting for Claude...)")
        try:
            process.wait(timeout=CLAUDE_TIMEOUT)
        except subprocess.TimeoutExpired:
            log(f"ERROR: Claude timed out after {CLAUDE_TIMEOUT}s, terminating...")
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
            return 1, ClaudeError.TIMEOUT, "Claude timed out"
        stderr_thread.join(timeout=1)
        stderr_text = ''.join(stderr_lines)
        error_type, error_msg = detect_error_type(stderr_text)
        return process.returncode, error_type, error_msg

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

                            def format_tool_result(content: Any, max_lines: int = TOOL_OUTPUT_PREVIEW_LINES) -> Optional[str]:
                                """Format tool result, showing first N lines."""
                                if not content:
                                    return None
                                # Handle Task tool results (list of content blocks)
                                if isinstance(content, list):
                                    texts = []
                                    for item in content:
                                        if isinstance(item, dict) and item.get('type') == 'text':
                                            texts.append(item.get('text', ''))
                                    content = '\n'.join(texts) if texts else str(content)
                                lines = str(content).split('\n')
                                # Truncate very long lines
                                lines = [line[:200] + '...' if len(line) > 200 else line for line in lines]
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
                                            arg = inp.get('command', '')[:COMMAND_PREVIEW_LENGTH]
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
    stderr_thread.join(timeout=1)
    stderr_text = ''.join(stderr_lines)
    error_type, error_msg = detect_error_type(stderr_text)
    return process.returncode, error_type, error_msg


def run_claude_with_retry(prompt: str) -> Tuple[int, str, str]:
    """Run Claude with automatic retry for transient errors.
    Returns (exit_code, error_type, error_message)."""
    for attempt, delay in enumerate(API_RETRY_DELAYS + [0]):  # +[0] for final attempt
        exit_code, error_type, error_msg = run_claude(prompt)

        if exit_code == 0:
            return exit_code, error_type, error_msg

        # Handle different error types
        if error_type == ClaudeError.RATE_LIMIT:
            log(f"Rate limited. Waiting {RATE_LIMIT_WAIT}s before retry...")
            time.sleep(RATE_LIMIT_WAIT)
            continue
        elif error_type == ClaudeError.TOKEN_LIMIT:
            log(f"ERROR: Token/credit limit reached: {error_msg}")
            return exit_code, error_type, error_msg  # Don't retry
        elif error_type == ClaudeError.API_ERROR:
            if delay > 0:
                log(f"API error (attempt {attempt + 1}/{len(API_RETRY_DELAYS)}). Retrying in {delay}s...")
                time.sleep(delay)
                continue
            else:
                log(f"API error persists after {len(API_RETRY_DELAYS)} retries")
                return exit_code, error_type, error_msg
        elif error_type == ClaudeError.TIMEOUT:
            log(f"Claude timed out")
            return exit_code, error_type, error_msg
        else:
            # Unknown error - retry with backoff
            if delay > 0:
                log(f"Claude error (attempt {attempt + 1}): {error_msg[:100]}. Retrying in {delay}s...")
                time.sleep(delay)
                continue
            else:
                return exit_code, error_type, error_msg

    return exit_code, error_type, error_msg


# --- Role triggers ---

def evaluate_triggers(task: Dict[str, Any], iteration: int, mode: str) -> Optional[str]:
    """Evaluate role triggers, return role name or None.

    Provides specialized roles based on context:
    - Reviewer: After many iterations, get a fresh perspective
    - Architect: During verification, validate design integrity
    """
    # After 5+ iterations on same task, bring in reviewer perspective
    if iteration >= 5 and mode == 'work':
        return 'Code Reviewer - provide fresh perspective on approach'

    # Verification mode benefits from architect thinking
    if mode == 'verify':
        return 'Architect - verify design meets original goals'

    return None

def build_prompt(task: Dict[str, Any], mode: str, role: Optional[str] = None, user_input: Optional[str] = None) -> str:
    """Build prompt based on task and mode.

    mode: 'work' (normal task) or 'verify' (split task, children complete)
    """
    task_id = task.get('id', 'UNKNOWN')
    title = task.get('title', 'UNKNOWN')

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


def build_completion_check_prompt() -> str:
    """Build prompt for verifying project completion when task list is empty."""
    parts = [
        "The task list is empty. Verify the project is complete.",
        "",
        "## Context Files (read in order)",
        "1. .willie/working.md - understand how we work",
        "2. .willie/learnings.md - what we learned during development",
        "3. .willie/idea.md - project vision and success criteria",
        "",
        "## Instructions",
        "1. Review the codebase to assess what has been built",
        "2. Compare against ALL goals and success criteria in .willie/idea.md",
        "3. Test or verify that success criteria are actually met, not just implemented",
        "",
        "## Decision",
        "- If ALL success criteria are met → respond with: PROJECT_COMPLETE",
        "- If ANY gaps remain → add new tasks using the Write tool (NOT bash/echo)",
        "",
        "## Adding Tasks (IMPORTANT)",
        "1. First READ .willie/tasks.jsonl (required before writing)",
        "2. Then use the Write tool to write tasks - do NOT use bash or echo",
        "Each line must be valid JSON with id, title, and status:",
        '{"id": "1", "title": "Short task description", "status": "pending"}',
        "Do NOT escape special characters - write plain JSON.",
        "",
        "Be thorough and critical. A project is only complete when ALL criteria are verified.",
    ]
    return "\n".join(parts)

# --- Main loop ---

def main(console: bool = False, daemon: bool = False) -> None:
    """Run the Willie loop.

    Args:
        console: Enable interactive console input (TUI)
        daemon: Run as daemon (poll forever instead of exiting when idle)
    """
    # Startup checks
    if not check_claude_installed():
        print("ERROR: 'claude' command not found.")
        print("Install Claude Code CLI: https://docs.anthropic.com/en/docs/claude-code")
        sys.exit(1)

    if not check_git_repo():
        print("ERROR: Not in a git repository.")
        print("Run 'git init' first, then try again.")
        sys.exit(1)

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
                run_claude_with_retry(prompt)
                continue

            # Check if project needs bootstrapping (idea defined but never started)
            if is_project_never_started():
                log("Project defined but no tasks. Creating bootstrap task...")
                create_bootstrap_task()
                continue

            if daemon:
                # Daemon mode: wait for new tasks (log once)
                if not waiting_logged:
                    log("No tasks. Waiting... (type a message or add tasks)")
                    waiting_logged = True
                time.sleep(POLL_INTERVAL)
                continue
            else:
                # Check if project was never properly initialized
                if is_idea_template():
                    log("Project not initialized. Running setup...")
                    prompt = build_init_prompt()
                    exit_code, error_type, _ = run_claude_with_retry(prompt)

                    if exit_code != 0:
                        if error_type == ClaudeError.TOKEN_LIMIT:
                            log("Cannot continue - out of tokens/credits")
                            break
                    continue

                # Normal mode: verify project completion against idea.md
                log("Task list empty. Verifying project completion...")

                prompt = build_completion_check_prompt()
                exit_code, error_type, _ = run_claude_with_retry(prompt)

                if exit_code != 0:
                    if error_type == ClaudeError.TOKEN_LIMIT:
                        log("Cannot continue - out of tokens/credits")
                        break
                    # Other errors already retried by run_claude_with_retry
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
                console_msg = get_console_input()
                if console_msg:
                    if user_input:
                        user_input = f"{user_input}\n\n{console_msg}"
                    else:
                        user_input = console_msg
            if user_input:
                log(f"User input received: {user_input[:50]}...")

            # Evaluate role triggers
            role = evaluate_triggers(task, iterations, mode)
            prompt = build_prompt(task, mode, role, user_input)

            # Run Claude
            exit_code, error_type, _ = run_claude_with_retry(prompt)

            if exit_code != 0:
                if error_type == ClaudeError.TOKEN_LIMIT:
                    log("Cannot continue - out of tokens/credits")
                    break
                # Other errors already retried by run_claude_with_retry
                continue

            # Reload tasks and check status
            tasks = read_tasks()
            current = get_task_by_id(tasks, task_id)

            if not current:
                # Task was removed? Shouldn't happen, but handle it
                log(f"Task {task_id} disappeared from file")
                break

            status = current.get('status')

            if status == TaskStatus.COMPLETE:
                log(f"Task {task_id} marked complete")
                task_done = True
                break
            elif status == TaskStatus.SPLIT:
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

        if current and current.get('status') == TaskStatus.COMPLETE:
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

        elif current and current.get('status') == TaskStatus.SPLIT:
            # Task was split - merge what we have, but don't archive
            # Children will be worked on in subsequent iterations
            git('checkout', base_branch)
            code, _, _ = git('diff', '--cached', '--quiet')
            if code != 0:  # There are staged changes
                git('merge', '--squash', branch)
                git('commit', '-m', f"[{task_id}] Split into subtasks")
            # Clean up branch (local and remote)
            code, _, stderr = git('branch', '-D', branch, quiet=True)
            if code != 0 and 'cannot delete branch' not in stderr:
                log(f"WARNING: Failed to delete local branch {branch}")
            if has_remote():
                code, _, stderr = git('push', 'origin', '--delete', branch, quiet=True)
                if code != 0 and 'remote ref does not exist' not in stderr:
                    log(f"WARNING: Failed to delete remote branch {branch}")
            log(f"=== Split: [{task_id}] - children pending ===")

        else:
            # Not complete, preserve branch for review
            git('checkout', base_branch)
            log(f"Branch {branch} preserved for review")

