# FILE: v2/blocker.py
# PURPOSE: Build deterministic mechanical blocks from normalized source text for V2 cartography.
# OWNS: Fixed-size block splitting, char offsets, and lightweight token estimation.
# EXPORTS: build_blocks, estimate_tokens.
# DOCS: v2/cartographer.py, v2/schema.py

from __future__ import annotations

try:
    import tiktoken
except ImportError:  # pragma: no cover
    tiktoken = None

from v2.schema import BlockArtifact


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4) if text else 0


def _get_encoder(model: str):
    if tiktoken is None:
        return None
    try:
        return tiktoken.encoding_for_model(model)
    except Exception:
        return tiktoken.get_encoding("cl100k_base")


def _encode_len(text: str, encoder) -> int:
    if not text:
        return 0
    if encoder is None:
        return estimate_tokens(text)
    return len(encoder.encode(text))


def build_blocks(
    text: str,
    *,
    target_tokens: int = 1024,
    min_tokens: int = 768,
    max_tokens: int = 1280,
    encoding_model: str = "gpt-4o-mini",
) -> list[BlockArtifact]:
    blocks: list[BlockArtifact] = []
    encoder = _get_encoder(encoding_model)
    paragraphs = re_split_paragraphs(text)
    if not paragraphs:
        return blocks

    order = 1
    current_parts: list[tuple[int, int, str, int]] = []
    current_tokens = 0

    for char_start, char_end, para_text in paragraphs:
        para_tokens = _encode_len(para_text, encoder)

        if current_parts and current_tokens >= min_tokens and current_tokens + para_tokens > max_tokens:
            blocks.append(_make_block(current_parts, order, current_tokens))
            order += 1
            current_parts = []
            current_tokens = 0

        if para_tokens > max_tokens:
            if current_parts:
                blocks.append(_make_block(current_parts, order, current_tokens))
                order += 1
                current_parts = []
                current_tokens = 0

            for piece_start, piece_end, piece_text in split_large_paragraph(
                para_text,
                char_start,
                max_tokens=max_tokens,
                target_tokens=target_tokens,
                encoder=encoder,
            ):
                piece_tokens = _encode_len(piece_text, encoder)
                blocks.append(
                    BlockArtifact(
                        block_id=f"block_{order:04d}",
                        order=order,
                        char_start=piece_start,
                        char_end=piece_end,
                        text=piece_text,
                        token_estimate=piece_tokens,
                    )
                )
                order += 1
            continue

        current_parts.append((char_start, char_end, para_text, para_tokens))
        current_tokens += para_tokens

        if current_tokens >= target_tokens and current_tokens <= max_tokens:
            blocks.append(_make_block(current_parts, order, current_tokens))
            order += 1
            current_parts = []
            current_tokens = 0

    if current_parts:
        blocks.append(_make_block(current_parts, order, current_tokens))

    return blocks


def re_split_paragraphs(text: str) -> list[tuple[int, int, str]]:
    parts: list[tuple[int, int, str]] = []
    cursor = 0
    for raw_part in text.split("\n\n"):
        start = text.find(raw_part, cursor)
        if start == -1:
            continue
        end = start + len(raw_part)
        cursor = end + 2
        stripped = raw_part.strip()
        if not stripped:
            continue
        leading_trim = len(raw_part) - len(raw_part.lstrip())
        trailing_trim = len(raw_part) - len(raw_part.rstrip())
        parts.append((start + leading_trim, end - trailing_trim, stripped))
    return parts


def split_large_paragraph(
    text: str,
    base_char_start: int,
    *,
    max_tokens: int,
    target_tokens: int,
    encoder,
) -> list[tuple[int, int, str]]:
    pieces: list[tuple[int, int, str]] = []
    sentences = split_sentences(text)
    if len(sentences) == 1:
        return split_large_sentence(text, base_char_start, max_tokens=max_tokens, target_tokens=target_tokens, encoder=encoder)

    current = ""
    current_start = 0
    cursor = 0
    for sentence in sentences:
        sentence_start = text.find(sentence, cursor)
        if sentence_start == -1:
            sentence_start = cursor
        sentence_end = sentence_start + len(sentence)
        candidate = f"{current} {sentence}".strip() if current else sentence
        if current and _encode_len(candidate, encoder) > max_tokens:
            chunk = current.strip()
            pieces.append((base_char_start + current_start, base_char_start + current_start + len(chunk), chunk))
            current = sentence
            current_start = sentence_start
        else:
            if not current:
                current_start = sentence_start
            current = candidate
        cursor = sentence_end

    if current.strip():
        chunk = current.strip()
        pieces.append((base_char_start + current_start, base_char_start + current_start + len(chunk), chunk))
    return pieces


def split_large_sentence(text: str, base_char_start: int, *, max_tokens: int, target_tokens: int, encoder) -> list[tuple[int, int, str]]:
    words = text.split()
    pieces: list[tuple[int, int, str]] = []
    current_words: list[str] = []
    for word in words:
        candidate = " ".join([*current_words, word])
        if current_words and _encode_len(candidate, encoder) > max_tokens:
            chunk = " ".join(current_words)
            offset = text.find(chunk)
            pieces.append((base_char_start + offset, base_char_start + offset + len(chunk), chunk))
            current_words = [word]
        else:
            current_words.append(word)
    if current_words:
        chunk = " ".join(current_words)
        offset = text.rfind(chunk)
        pieces.append((base_char_start + offset, base_char_start + offset + len(chunk), chunk))
    return pieces


def split_sentences(text: str) -> list[str]:
    import re

    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if p.strip()]


def _make_block(parts: list[tuple[int, int, str, int]], order: int, token_estimate: int) -> BlockArtifact:
    char_start = parts[0][0]
    char_end = parts[-1][1]
    chunk_text = "\n\n".join(part[2] for part in parts)
    return BlockArtifact(
        block_id=f"block_{order:04d}",
        order=order,
        char_start=char_start,
        char_end=char_end,
        text=chunk_text,
        token_estimate=token_estimate,
    )
