#!/usr/bin/env python3
"""Willie CLI entry point."""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

WILLIE_DIR = Path(".willie")

def get_templates_dir():
    """Get the path to bundled template files."""
    return Path(__file__).parent / "templates"

def cmd_init():
    """Initialize a Willie project in the current directory."""
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
    print("Willie initialized! Next steps:")
    print("  1. Run: willie edit    # Define your project in idea.md")
    print("  2. Run: willie         # Start the loop")

def cmd_edit():
    """Open interactive session to define idea.md."""
    if not WILLIE_DIR.exists():
        print("Error: Not a Willie project. Run 'willie init' first.")
        sys.exit(1)

    idea_file = WILLIE_DIR / "idea.md"
    working_file = WILLIE_DIR / "working.md"

    prompt = f"Read {working_file} and help me define {idea_file} with my project idea. Ask me questions until you're 99% sure about what I want to build. Cover: goals, constraints, tech stack, and success criteria."

    subprocess.run(["claude", prompt])

def cmd_run(args):
    """Run the Willie loop."""
    if not WILLIE_DIR.exists():
        print("Error: Not a Willie project. Run 'willie init' first.")
        sys.exit(1)

    from willie.loop import main as loop_main, stop_console_reader
    try:
        loop_main(console=args.console, daemon=args.daemon)
    finally:
        stop_console_reader()

def main():
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
