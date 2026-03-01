# AGENTS.md

Repository-level collaboration notes for contributors and coding agents.

## Scope

- Applies to the entire repository.
- Follow existing code style and keep changes minimal and task-focused.

## Configuration and Secrets

- Never commit real API keys or tokens.
- Keep `.env` local only; use `.env.example` for placeholders.
- For GitHub Actions, store credentials in repository secrets (not in workflow YAML).

## GitHub Actions Dependency Pinning

- For external repositories checked out in workflows (for example `zotero-mcp`), pin a known-good commit SHA by default.
- Do not default critical workflow dependencies to moving refs like `main`.
- Only update pinned SHAs after validating the new revision in CI/local smoke tests.

## CLI Workflow Conventions

- Recommended order: `fetch -> filter -> enrich -> export`.
- Do not export directly from fetched input (`fetched_papers.json` / legacy `raw.json`) unless intentionally bypassing filtering.
- For Zotero exports, prefer `TARGET_COLLECTION` or `--collection`.
- Default collection is `00_INBOXS_AA`.
- For this repository, prioritize direct updates over backward-compatibility shims unless explicitly requested.

## Gmail Pipeline Notes

- `GMAIL_SENDER_FILTER` is optional; if set too narrowly, fetch may return `0`.
- When mailbox has no matching alerts, zero fetched papers is expected behavior.

## Zotero Dedup Notes

- Existing-item dedup preload must use full-library pagination.
- Identity keys for preload must be derived from parent-level items only.
- Child items (attachments/notes/annotations) must be excluded from dedup-key generation.

## Validation

- Run targeted tests for touched areas before finalizing:
  - `uv run pytest tests/unit/test_cli.py tests/unit/test_config.py`
  - Add `tests/unit/test_gmail_source.py` when changing Gmail behavior.
  - Run `uv run pytest tests/unit/test_adapters.py` when changing Zotero adapter behavior.
