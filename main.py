"""
Rixie — Book Distillation Engine
=================================

CLI entry point. Dispatches to subcommands.

Usage:
    uv run rixie v1 [options] [book_path ...]
    uv run rixie v2 [options] [book_path ...]
    uv run rixie audiobook [options]
    uv run rixie reading-list
    uv run rixie help
"""

import sys


def main():
    """CLI entry point — dispatch to subcommands."""
    args = sys.argv[1:]

    if not args or args[0] in ("--help", "-h", "help"):
        _show_help()
        return

    cmd = args[0]
    rest = args[1:]

    # Patch sys.argv so subcommands see clean args
    old_argv = sys.argv
    sys.argv = [f"rixie-{cmd}"] + rest

    try:
        if cmd == "v1":
            from v1.process import main as v1_main

            raise SystemExit(v1_main())

        elif cmd == "v2":
            from v2.process import main as v2_main

            raise SystemExit(v2_main())

        elif cmd == "audiobook":
            import asyncio

            from audiobook import main as audiobook_main

            asyncio.run(audiobook_main())

        elif cmd == "reading-list":
            from copy_to_reading_list import copy_htmls_to_reading_list

            copy_htmls_to_reading_list()

        else:
            print(f"❌ Unknown command: {cmd}")
            _show_help()
            sys.exit(1)

    except SystemExit:
        raise
    except KeyboardInterrupt:
        print("\n⏸️  Interrupted.")
        sys.exit(130)
    finally:
        sys.argv = old_argv


def _show_help():
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║  📚 Rixie — Book Distillation Engine                       ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print()
    print("Usage:  uv run rixie <command> [options]")
    print()
    print("Commands:")
    print("  v1               Run legacy V1 pipeline")
    print("  v2               Run progressive V2 pipeline")
    print("  audiobook        Generate MP3 audiobook from V1 output")
    print("  reading-list     Copy HTML exports to reading_list/")
    print("  help             Show this help")
    print()
    print("Examples:")
    print("  uv run rixie v1                           # Process all books in input/")
    print("  uv run rixie v1 input/my_book.epub        # Process a specific book")
    print("  uv run rixie v2 input/my_book.epub        # V2 progressive pipeline")
    print("  uv run rixie audiobook                    # Interactive audiobook menu")
    print("  uv run rixie reading-list                 # Copy HTMLs to reading list")
    print()
    print("For per-command help:")
    print("  uv run rixie v1 --help")
    print("  uv run rixie v2 --help")
    print("  uv run rixie audiobook --help")


if __name__ == "__main__":
    main()
