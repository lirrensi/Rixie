# FILE: export_epub.py
# PURPOSE: Preserve the legacy EPUB export CLI at the repo root while delegating implementation to v1.
# OWNS: Root compatibility wrapper for the V1 EPUB exporter entrypoint.
# EXPORTS: export_epub, main.
# DOCS: README.md, v1/export_epub.py

from v1.export_epub import export_epub, main

__all__ = ["export_epub", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
