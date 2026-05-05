# FILE: synthesizer.py
# PURPOSE: Preserve the legacy synthesizer CLI at the repo root while delegating implementation to v1.
# OWNS: Root compatibility wrapper for the V1 synthesizer entrypoint.
# EXPORTS: count_tokens, load_config, load_prompt, main, synthesize_book.
# DOCS: README.md, v1/synthesizer.py

from v1.synthesizer import count_tokens, load_config, load_prompt, main, synthesize_book

__all__ = ["count_tokens", "load_config", "load_prompt", "main", "synthesize_book"]


if __name__ == "__main__":
    raise SystemExit(main())
