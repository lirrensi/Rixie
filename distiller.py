# FILE: distiller.py
# PURPOSE: Preserve the legacy distiller CLI at the repo root while delegating implementation to v1.
# OWNS: Root compatibility wrapper for the V1 distiller entrypoint.
# EXPORTS: distill_book, distill_chunk, load_config, load_prompt, main, validate_distillation.
# DOCS: README.md, v1/distiller.py

from v1.distiller import (
    distill_book,
    distill_chunk,
    load_config,
    load_prompt,
    main,
    validate_distillation,
)

__all__ = [
    "distill_book",
    "distill_chunk",
    "load_config",
    "load_prompt",
    "main",
    "validate_distillation",
]


if __name__ == "__main__":
    raise SystemExit(main())
