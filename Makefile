# ─── Rixie — Common Commands ────────────────────────────────────────────────

.PHONY: install v1 v2 audiobook podcast reading-list lint format clean help

# ── Setup ───────────────────────────────────────────────────────────────────

install:           ## Install dependencies (uv sync)
	uv sync

# ── V1 Pipeline ─────────────────────────────────────────────────────────────

v1:                ## Run V1 pipeline on all books in input/
	uv run rixie v1

v1-book:           ## Run V1 pipeline on a specific book (usage: make v1-book B=file.epub)
	uv run rixie v1 input/$(B)

# ── V2 Pipeline ─────────────────────────────────────────────────────────────

v2:                ## Run V2 pipeline on all books in input/
	uv run rixie v2

v2-book:           ## Run V2 pipeline on a specific book (usage: make v2-book B=file.epub)
	uv run rixie v2 input/$(B)

v2-smoke:          ## V2 smoke test — first 10 blocks only (usage: make v2-smoke B=file.epub)
	uv run rixie v2 input/$(B) --max-blocks 10

# ── Audio ────────────────────────────────────────────────────────────────────

audiobook:         ## Run V1 audiobook generator (interactive)
	uv run rixie audiobook

podcast:           ## V2 podcast generator (usage: make podcast SLUG=my-book-slug)
	uv run python -m v2.podcast output/v2/$(SLUG)

# ── Utilities ────────────────────────────────────────────────────────────────

reading-list:      ## Copy all HTML exports to reading_list/
	uv run rixie reading-list

# ── Lint & Format ───────────────────────────────────────────────────────────

lint:              ## Run ruff linter
	uv run ruff check .

format:            ## Run ruff formatter
	uv run ruff format .

check: lint        ## Alias for lint

# ── Clean ────────────────────────────────────────────────────────────────────

clean:             ## Remove caches and temporary files
	rm -rf .ruff_cache __pycache__
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true

clean-all: clean   ## Remove everything except source
	rm -rf .venv uv.lock

# ── Help ─────────────────────────────────────────────────────────────────────

help:              ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'
