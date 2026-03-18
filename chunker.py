"""
BookConvert - Smart Book Chunker
Groups book sections into digestible chunks respecting natural boundaries.

Strategy:
1. Parse all headings (h1, h2, h3)
2. Identify "Part" markers as structural anchors
3. Group sections between Part markers into logical units
4. If a group exceeds max_tokens, split at h2 boundaries
5. If still too big, split at paragraph boundaries
6. If still too big, recursively halve
"""

import re
import tiktoken
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class RawSection:
    """A parsed section from the book."""

    level: int  # 1=h1, 2=h2, 3=h3
    title: str
    content: str
    line_start: int


@dataclass
class Chunk:
    """A single chunk of book content."""

    text: str
    title: str
    token_count: int
    section_titles: list[str]
    index: int


class BookChunker:
    """Smart book chunker that respects natural boundaries."""

    def __init__(self, max_tokens: int = 8000, encoding_model: str = "gpt-4o-mini"):
        self.max_tokens = max_tokens
        self.encoder = tiktoken.encoding_for_model(encoding_model)

    def count_tokens(self, text: str) -> int:
        return len(self.encoder.encode(text))

    def clean_text(self, text: str) -> str:
        """Clean OCR artifacts and normalize text."""
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
        text = re.sub(r"\n\s*(Figure|Table)\s+\d+\s*\n", "\n", text)
        return text.strip()

    def find_content_start(self, lines: list[str]) -> int:
        """Find where actual content begins (after TOC and metadata)."""
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("**Title:") or stripped.startswith("**Author"):
                continue
            if stripped.startswith("!["):
                continue
            if re.match(r"^\d+\.\s*\[", stripped):
                continue
            if re.match(r"^<\d+>", stripped):
                continue
            if stripped.startswith("# "):
                if i + 2 < len(lines):
                    next_lines = "\n".join(lines[i + 1 : i + 5]).strip()
                    if len(next_lines) > 100:
                        return i
        return 0

    def parse_sections(self, text: str) -> list[RawSection]:
        """Parse markdown into flat list of sections."""
        text = self.clean_text(text)
        lines = text.split("\n")
        content_start = self.find_content_start(lines)
        lines = lines[content_start:]

        sections = []
        current_level = 0
        current_title = ""
        current_content = []
        current_line = 0

        for i, line in enumerate(lines):
            stripped = line.strip()
            heading_match = re.match(r"^(#{1,3})\s+(.+)$", stripped)

            if heading_match:
                if current_title or current_content:
                    content = "\n".join(current_content).strip()
                    if content or current_title:
                        sections.append(
                            RawSection(
                                level=current_level,
                                title=current_title or "[Untitled]",
                                content=content,
                                line_start=current_line,
                            )
                        )
                current_level = len(heading_match.group(1))
                current_title = heading_match.group(2).strip()
                current_content = []
                current_line = content_start + i
            else:
                current_content.append(line)

        if current_title or current_content:
            sections.append(
                RawSection(
                    level=current_level,
                    title=current_title or "[Untitled]",
                    content="\n".join(current_content).strip(),
                    line_start=current_line,
                )
            )
        return sections

    def is_part_marker(self, section: RawSection) -> bool:
        """Check if this section is a structural 'Part' marker."""
        if section.level != 1:
            return False
        return bool(re.match(r"Part\s+[IVXLC\d]+", section.title, re.IGNORECASE))

    def is_trash_section(self, section: RawSection) -> bool:
        """Check if this section should be skipped."""
        title = section.title.strip()
        if not title or len(title) < 2:
            return True
        if re.match(r"^(Figure|Table)\s+\d+$", title):
            return True
        if re.match(r"^\d{1,4}$", title):
            return True
        if title.lower() in ["contents", "index", "acknowledgments"]:
            return True
        if not section.content.strip():
            return True
        weird_chars = len(re.findall(r"[^a-zA-Z0-9\s,.\'-:;!?()&]", title))
        if weird_chars > len(title) * 0.3:
            return True
        return False

    def group_sections(self, sections: list[RawSection]) -> list[list[RawSection]]:
        """Group sections into logical units based on Part markers and token counts."""
        groups = []
        current_group = []
        current_tokens = 0

        for section in sections:
            if self.is_trash_section(section):
                continue
            section_tokens = self.count_tokens(section.title + "\n" + section.content)

            if self.is_part_marker(section):
                if current_group:
                    groups.append(current_group)
                current_group = [section]
                current_tokens = section_tokens
                continue

            if current_group and (current_tokens + section_tokens > self.max_tokens):
                groups.append(current_group)
                current_group = [section]
                current_tokens = section_tokens
            else:
                current_group.append(section)
                current_tokens += section_tokens

        if current_group:
            groups.append(current_group)
        return groups

    def find_split_point(self, text: str, target_index: int) -> int:
        """Find best split point near target (paragraph > sentence > hard split)."""
        window = max(200, len(text) // 4)
        search_start = max(0, target_index - window)
        search_end = min(len(text), target_index + window)
        search_region = text[search_start:search_end]

        best_pos = None
        best_distance = float("inf")

        for match in re.finditer(r"\n\n+", search_region):
            abs_pos = search_start + match.start()
            distance = abs(abs_pos - target_index)
            if distance < best_distance:
                best_distance = distance
                best_pos = abs_pos

        if best_pos is not None:
            return best_pos

        for match in re.finditer(r"[.!?]\s+", search_region):
            abs_pos = search_start + match.end()
            distance = abs(abs_pos - target_index)
            if distance < best_distance:
                best_distance = distance
                best_pos = abs_pos

        return best_pos or target_index

    def recursive_split(self, text: str, title: str, index_start: int) -> list[Chunk]:
        """Recursively split text until all chunks fit."""
        tokens = self.count_tokens(text)

        if tokens <= self.max_tokens:
            return [
                Chunk(
                    text=text.strip(),
                    title=title,
                    token_count=tokens,
                    section_titles=[title],
                    index=index_start,
                )
            ]

        midpoint = len(text) // 2
        split_point = self.find_split_point(text, midpoint)

        first_half = text[:split_point].strip()
        second_half = text[split_point:].strip()

        if not first_half or not second_half:
            first_half = text[:midpoint]
            second_half = text[midpoint:]

        chunks = []
        chunks.extend(self.recursive_split(first_half, f"{title} (1/2)", index_start))
        next_idx = index_start + len(chunks)
        chunks.extend(self.recursive_split(second_half, f"{title} (2/2)", next_idx))
        return chunks

    def chunk_book(self, text: str) -> list[Chunk]:
        """Main entry point: chunk a book into digestible pieces."""
        sections = self.parse_sections(text)
        print(f"   📖 Parsed {len(sections)} raw sections")

        parts_found = sum(1 for s in sections if self.is_part_marker(s))
        print(
            f"      Parts: {parts_found} | Chapters: {sum(1 for s in sections if s.level == 1 and not self.is_part_marker(s))} | Sub-sections: {sum(1 for s in sections if s.level == 2)}"
        )

        groups = self.group_sections(sections)
        print(f"   📦 Grouped into {len(groups)} logical units")

        chunks = []
        chunk_index = 0

        for group in groups:
            combined_parts = []
            section_titles = []

            for section in group:
                if self.is_part_marker(section):
                    combined_parts.append(f"# {section.title}")
                    section_titles.append(section.title)
                else:
                    if section.content:
                        combined_parts.append(section.content)
                        section_titles.append(section.title)

            combined_text = "\n\n".join(combined_parts).strip()
            if not combined_text:
                continue

            title = group[0].title
            tokens = self.count_tokens(combined_text)

            if tokens <= self.max_tokens:
                chunks.append(
                    Chunk(
                        text=combined_text,
                        title=title,
                        token_count=tokens,
                        section_titles=section_titles,
                        index=chunk_index,
                    )
                )
                chunk_index += 1
            else:
                new_chunks = self.recursive_split(combined_text, title, chunk_index)
                chunks.extend(new_chunks)
                chunk_index += len(new_chunks)

        total_tokens = sum(c.token_count for c in chunks)
        print(
            f"   📊 {len(chunks)} chunks | {total_tokens:,} total tokens | avg {total_tokens // max(len(chunks), 1):,}"
        )
        return chunks

    def save_chunks(self, chunks: list[Chunk], output_dir: Path):
        """Save chunks to files."""
        output_dir.mkdir(parents=True, exist_ok=True)
        manifest = ["# Chunks Manifest\n"]

        for chunk in chunks:
            safe_title = re.sub(r"[^\w\s-]", "", chunk.title).strip()
            safe_title = re.sub(r"\s+", "_", safe_title)[:50]
            filename = f"{chunk.index:03d}_{safe_title}.md"

            header = f"# {chunk.title}\n\n"
            header += f"> **Tokens:** {chunk.token_count:,}\n"
            header += f"> **Contains:** {', '.join(chunk.section_titles[:5])}"
            if len(chunk.section_titles) > 5:
                header += f" (+{len(chunk.section_titles) - 5} more)"
            header += "\n\n---\n\n"

            (output_dir / filename).write_text(header + chunk.text, encoding="utf-8")
            manifest.append(
                f"{chunk.index:03d}. **{chunk.title}** ({chunk.token_count:,} tokens)"
            )

        (output_dir / "MANIFEST.md").write_text("\n".join(manifest), encoding="utf-8")


def chunk_book(
    book_path: Path,
    output_dir: Path,
    max_tokens: int = 8000,
    encoding_model: str = "gpt-4o-mini",
) -> list[Chunk]:
    """Standalone function to chunk a book. Returns list of Chunks."""
    print(f"📚 Loading {book_path.name}...")
    text = book_path.read_text(encoding="utf-8")
    print(f"   {len(text):,} chars, ~{len(text.split()):,} words\n")

    chunker = BookChunker(max_tokens=max_tokens, encoding_model=encoding_model)
    chunks = chunker.chunk_book(text)
    chunker.save_chunks(chunks, output_dir)
    return chunks


if __name__ == "__main__":
    import sys
    import yaml

    # Load config
    config_path = Path("config.yaml")
    if config_path.exists():
        with open(config_path) as f:
            config = yaml.safe_load(f)
        max_tokens = config.get("chunking", {}).get("max_tokens", 8000)
        encoding_model = config.get("chunking", {}).get("encoding_model", "gpt-4o-mini")
    else:
        max_tokens = 8000
        encoding_model = "gpt-4o-mini"

    if len(sys.argv) < 2:
        print("Usage: python chunker.py <book_file> [output_dir]")
        sys.exit(1)

    book_path = Path(sys.argv[1])
    output_dir = (
        Path(sys.argv[2])
        if len(sys.argv) > 2
        else Path("output") / book_path.stem / "chunks"
    )
    chunk_book(book_path, output_dir, max_tokens, encoding_model)
