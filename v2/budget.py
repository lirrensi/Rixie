# FILE: v2/budget.py
# PURPOSE: Context-aware token budgeting for V2 pipeline stages.
#          Figures out how much room you have, and splits payloads when
#          you'd otherwise overflow and make the LLM cry.
# OWNS: Token estimation, budget calculation, payload splitting logic.
# EXPORTS: ContextBudget, estimate_tokens, split_by_budget.

from __future__ import annotations

from typing import Any, Callable, TypeVar

try:
    import tiktoken
except ImportError:
    tiktoken = None

T = TypeVar("T")


# ── Token estimation ──────────────────────────────────────────────────────────

_ENCODER_CACHE: dict[str, Any] = {}


def _get_encoder(model: str) -> any:
    """Get a tiktoken encoder (cached). Falls back to cl100k_base."""
    if tiktoken is None:
        return None
    if model in _ENCODER_CACHE:
        return _ENCODER_CACHE[model]
    try:
        enc = tiktoken.encoding_for_model(model)
    except Exception:
        enc = tiktoken.get_encoding("cl100k_base")
    _ENCODER_CACHE[model] = enc
    return enc


def estimate_tokens(text: str, model: str = "gpt-4o-mini") -> int:
    """Count tokens in text using a model-aware encoder.
    
    Falls back to ~4 chars/token if tiktoken is not available.
    Returns at least 1 for non-empty text, 0 for empty.
    """
    if not text:
        return 0
    enc = _get_encoder(model)
    if enc is None:
        return max(1, len(text) // 4)
    return len(enc.encode(text))


# ── Budget calculation ────────────────────────────────────────────────────────

class ContextBudget:
    """Calculate how many input tokens are available for a single LLM call.
    
    Usage::
    
        budget = ContextBudget(context_window=128000, overhead=2000, reserve=4000)
        usable = budget.usable  # 122000 tokens for input
    
    The formula is:
        usable = context_window - system_prompt_tokens - prompt_overhead - response_reserve
    
    Where:
      - context_window: the model's total context window (configurable)
      - prompt_overhead: fixed overhead for the system prompt and structural formatting
      - response_reserve: tokens reserved for the LLM's response
    """

    def __init__(
        self,
        context_window: int,
        prompt_overhead: int = 4000,
        response_reserve: int = 8000,
        encoding_model: str = "gpt-4o-mini",
    ):
        self._context_window = context_window
        self._prompt_overhead = prompt_overhead
        self._response_reserve = response_reserve
        self._encoding_model = encoding_model

    @property
    def usable(self) -> int:
        """Max tokens available for ALL input (system + user messages)."""
        return self._context_window - self._prompt_overhead - self._response_reserve

    @property
    def context_window(self) -> int:
        return self._context_window

    def estimate(self, text: str) -> int:
        return estimate_tokens(text, self._encoding_model)

    def fits(self, text: str) -> bool:
        """Check if text fits within the usable budget."""
        return self.estimate(text) <= self.usable

    def __repr__(self) -> str:
        return (
            f"ContextBudget(window={self._context_window}, "
            f"overhead={self._prompt_overhead}, "
            f"reserve={self._response_reserve}, "
            f"usable={self.usable})"
        )


# ── Payload splitting ─────────────────────────────────────────────────────────

def split_by_budget(
    items: list[T],
    *,
    budget: ContextBudget,
    per_item_token_fn: Callable[[T], int],
    system_prompt: str = "",
    min_chunks: int = 1,
) -> list[list[T]]:
    """Split a list of items into chunks, each fitting within the budget.
    
    Args:
        items: The items to split (e.g. blocks).
        budget: The context budget for each call.
        per_item_token_fn: Function that returns token count for a single item.
        system_prompt: System prompt text (its tokens reduce the budget).
        min_chunks: Minimum number of chunks to split into (default 1, no min).
    
    Returns:
        List of chunks, where each chunk is a sublist of items.
    
    If items fit within budget, returns [items] (single chunk).
    If any single item exceeds budget, it still gets its own chunk
    (better to try and fail than to silently drop content).
    """
    if not items:
        return []

    system_tokens = budget.estimate(system_prompt)
    # Per-call fixed overhead for formatting
    per_call_overhead = estimate_tokens(
        "\n---\n❌ YOUR PREVIOUS CHAPTER MAP WAS REJECTED:\n...\n",
        budget._encoding_model,
    )
    available = budget.usable - system_tokens - per_call_overhead

    # If everything fits comfortably, return as one chunk
    total = sum(per_item_token_fn(item) for item in items)
    if total <= available and len(items) >= min_chunks:
        return [items]

    # Do the math: how many items per chunk based on average size
    if len(items) <= 1:
        return [items]

    avg_item = total / len(items) if len(items) > 0 else 1
    items_per_chunk = max(1, int(available / avg_item))
    num_chunks = max(min_chunks, (len(items) + items_per_chunk - 1) // items_per_chunk)

    # Redistribute items as evenly as possible across chunks
    chunks: list[list[T]] = []
    base = len(items) // num_chunks
    remainder = len(items) % num_chunks
    start = 0
    for i in range(num_chunks):
        chunk_size = base + (1 if i < remainder else 0)
        chunks.append(items[start:start + chunk_size])
        start += chunk_size

    return chunks


def split_text_by_tokens(
    text: str,
    max_tokens: int,
    model: str = "gpt-4o-mini",
    min_chars: int = 100,
) -> list[str]:
    """Split a string into chunks each <= max_tokens tokens (approximate).
    
    Tries to break at paragraph boundaries first, then sentences.
    If a paragraph is too large, it's hard-split by token count.
    """
    if not text or estimate_tokens(text, model) <= max_tokens:
        return [text] if text else []

    enc = _get_encoder(model)
    tokens = enc.encode(text) if enc else None

    if tokens is None:
        # Fallback: char-based splitting
        avg_chars_per_token = 4
        chunk_chars = max_tokens * avg_chars_per_token
        chunks: list[str] = []
        i = 0
        while i < len(text):
            end = min(i + chunk_chars, len(text))
            chunk = text[i:end]
            if len(chunk) < min_chars and chunks:
                chunks[-1] += chunk
            else:
                chunks.append(chunk)
            i = end
        return chunks

    # Token-aware splitting at paragraph boundaries
    paragraphs = text.split("\n\n")
    chunks = []
    current_tokens: list[int] = []
    current_text: list[str] = []

    for para in paragraphs:
        para_tokens = len(enc.encode(para))
        if not current_text:
            current_text = [para]
            current_tokens = [para_tokens]
        elif sum(current_tokens) + para_tokens <= max_tokens:
            current_text.append(para)
            current_tokens.append(para_tokens)
        else:
            chunks.append("\n\n".join(current_text))
            current_text = [para]
            current_tokens = [para_tokens]

    if current_text:
        chunks.append("\n\n".join(current_text))

    # If any single chunk still exceeds max_tokens, hard split by token count
    final_chunks: list[str] = []
    for chunk in chunks:
        chunk_tok = len(enc.encode(chunk))
        if chunk_tok <= max_tokens:
            final_chunks.append(chunk)
        else:
            # Hard split
            tok_ids = enc.encode(chunk)
            for i in range(0, len(tok_ids), max_tokens):
                piece = enc.decode(tok_ids[i:i + max_tokens])
                if piece.strip():
                    final_chunks.append(piece)

    return final_chunks
