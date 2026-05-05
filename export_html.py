# FILE: export_html.py
# PURPOSE: Preserve the legacy HTML export CLI at the repo root while delegating implementation to v1.
# OWNS: Root compatibility wrapper for the V1 HTML exporter entrypoint.
# EXPORTS: export_html, main.
# DOCS: README.md, v1/export_html.py

from v1.export_html import export_html, main

__all__ = ["export_html", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
