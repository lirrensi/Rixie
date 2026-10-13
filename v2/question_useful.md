# Gate question for the useful/non-content pre-gate.
#
# Format: three sections separated by a line containing only `---`.
#   1. instructions — the yes/no question (first line may be a `#` title, ignored)
#   2. criteria for TRUE  (block IS useful content)
#   3. criteria for FALSE (block is non-content)
#
# Keep this in English even for non-English books: decision models score
# questions more accurately in English while the block text stays native.
# After editing, run `uv run python -m v2.calibrate` to re-fit thresholds.
# Gate behavior (see config.yaml -> v2.execution):
#   score <= decision_useful_low   -> skip generation (non-content)
#   score >= decision_useful_high  -> confident content (generate)
#   between, or gate error         -> fail open (generate)

# Question
Does this block contain actual book content?

---

Narrative, argument, exposition, or ideas carrying the book's substance;
ambiguous blocks with real insight count as content.

---

Front matter, copyright, acknowledgments, table of contents, index,
bibliography, blank filler, page numbers, or other boilerplate.
