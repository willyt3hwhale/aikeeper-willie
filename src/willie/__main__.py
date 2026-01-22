#!/usr/bin/env python3
"""Willie CLI entry point."""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

WILLIE_DIR = Path(".willie")


def check_claude_installed() -> bool:
    """Check if Claude CLI is installed."""
    return shutil.which('claude') is not None


def check_git_repo() -> bool:
    """Check if we're in a git repository."""
    result = subprocess.run(['git', 'rev-parse', '--git-dir'],
                          capture_output=True, text=True)
    return result.returncode == 0

def get_templates_dir():
    """Get the path to bundled template files."""
    return Path(__file__).parent / "templates"

def cmd_init() -> None:
    """Initialize a Willie project in the current directory."""
    # Check prerequisites
    if not check_claude_installed():
        print("Error: 'claude' command not found.")
        print("Install Claude Code CLI: https://docs.anthropic.com/en/docs/claude-code")
        sys.exit(1)

    if not check_git_repo():
        print("Error: Not in a git repository.")
        print("Run 'git init' first, then try again.")
        sys.exit(1)

    if WILLIE_DIR.exists():
        print(f"Error: {WILLIE_DIR} already exists. Already initialized?")
        sys.exit(1)

    # Create .willie directory
    WILLIE_DIR.mkdir()
    print(f"Created {WILLIE_DIR}/")

    # Copy template files
    templates = get_templates_dir()
    for template in templates.iterdir():
        if template.is_file():
            dest = WILLIE_DIR / template.name
            shutil.copy(template, dest)
            print(f"  Created {dest}")

    # Create empty tasks.jsonl
    (WILLIE_DIR / "tasks.jsonl").touch()
    print(f"  Created {WILLIE_DIR}/tasks.jsonl")

    print()
    print("Starting interactive session to define your project...")
    print()

    # Run Claude to help define idea.md
    idea_file = WILLIE_DIR / "idea.md"
    working_file = WILLIE_DIR / "working.md"
    prompt = f"""Read {working_file} and help me define {idea_file} with my project idea.

Use the AskUserQuestion tool to ask me questions one at a time until you're 99% sure about what I want to build.

Cover these topics:
- Goals: What am I building? What problem does it solve?
- Constraints: Development rules and standards
- Tech stack: Languages, frameworks, key dependencies
- Success criteria: How do we know when it's done?

After gathering all answers, write the complete {idea_file} file."""

    result = subprocess.run(["claude", prompt])
    if result.returncode != 0:
        print(f"Warning: Claude exited with code {result.returncode}")

    print()
    print("Willie initialized! Run 'willie' to start the loop.")

def cmd_edit() -> None:
    """Open interactive session to define idea.md."""
    if not check_claude_installed():
        print("Error: 'claude' command not found.")
        print("Install Claude Code CLI: https://docs.anthropic.com/en/docs/claude-code")
        sys.exit(1)

    if not WILLIE_DIR.exists():
        print("Error: Not a Willie project. Run 'willie init' first.")
        sys.exit(1)

    idea_file = WILLIE_DIR / "idea.md"
    working_file = WILLIE_DIR / "working.md"

    prompt = f"""Read {working_file} and help me define {idea_file} with my project idea.

Use the AskUserQuestion tool to ask me questions one at a time until you're 99% sure about what I want to build.

Cover these topics:
- Goals: What am I building? What problem does it solve?
- Constraints: Development rules and standards
- Tech stack: Languages, frameworks, key dependencies
- Success criteria: How do we know when it's done?

After gathering all answers, write the complete {idea_file} file."""

    result = subprocess.run(["claude", prompt])
    if result.returncode != 0:
        print(f"Warning: Claude exited with code {result.returncode}")

def cmd_run(args: Any) -> None:
    """Run the Willie loop."""
    if not WILLIE_DIR.exists():
        print("Error: Not a Willie project. Run 'willie init' first.")
        sys.exit(1)

    from willie.loop import main as loop_main, stop_console_reader
    try:
        loop_main(console=args.console, daemon=args.daemon)
    finally:
        stop_console_reader()

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Willie Loop - External orchestration loop for Claude Code"
    )
    subparsers = parser.add_subparsers(dest="command")

    # init command
    subparsers.add_parser("init", help="Initialize a Willie project")

    # edit command
    subparsers.add_parser("edit", help="Edit idea.md interactively with Claude")

    # run command (also default)
    run_parser = subparsers.add_parser("run", help="Run the Willie loop")
    run_parser.add_argument("-c", "--console", action="store_true",
                           help="Enable interactive console input")
    run_parser.add_argument("-d", "--daemon", action="store_true",
                           help="Run as daemon (poll forever)")

    # Also add flags to main parser for default run
    parser.add_argument("-c", "--console", action="store_true",
                       help="Enable interactive console input")
    parser.add_argument("-d", "--daemon", action="store_true",
                       help="Run as daemon (poll forever)")

    args = parser.parse_args()

    if args.command == "init":
        cmd_init()
    elif args.command == "edit":
        cmd_edit()
    elif args.command == "run":
        cmd_run(args)
    elif args.command is None:
        # Default: run the loop if .willie exists, otherwise show help
        if WILLIE_DIR.exists():
            cmd_run(args)
        else:
            parser.print_help()
            print()
            print("To get started, run: willie init")

if __name__ == "__main__":
    main()
