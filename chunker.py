# FILE: chunker.py
# PURPOSE: Preserve the legacy chunker CLI at the repo root while delegating implementation to v1.
# OWNS: Root compatibility wrapper for the V1 chunker entrypoint.
# EXPORTS: BookChunker, Chunk, RawSection, chunk_book, main.
# DOCS: README.md, v1/chunker.py

from v1.chunker import BookChunker, Chunk, RawSection, chunk_book, main

__all__ = ["BookChunker", "Chunk", "RawSection", "chunk_book", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
