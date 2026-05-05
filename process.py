# FILE: process.py
# PURPOSE: Preserve the legacy end-to-end CLI at the repo root while delegating implementation to v1.
# OWNS: Root compatibility wrapper for the V1 process entrypoint.
# EXPORTS: main, process_book.
# DOCS: README.md, v1/process.py

from v1.process import main, process_book

__all__ = ["main", "process_book"]


if __name__ == "__main__":
    raise SystemExit(main())
