# Changelog

## 0.1.1 - 2026-05-17

### Added

- README demo GIF showing Rick running a judged CLI workflow.

### Fixed

- Interactive TUI transcript scrolling now works with `PgUp`, `PgDn`, mouse wheel, and trackpad scrolling.
- TUI transcript history no longer jumps to the bottom while the user is reading older output.

## 0.1.0 - 2026-05-17

Initial alpha release of Rick, a local CLI for staged LLM workflows.

Highlights:

- Workflow DSL with `RESOLVE`, `CONTEXT`, `GEN`, `JUDGE`, `EDIT`, output glue, materialization, and verification steps.
- Multiple candidate generation with DoD-based judging.
- Markdown and JSON run logs for inspection and regression work.
- OpenRouter integration with local mock fallback when no API key is configured.
- Interactive terminal UI for local workflow runs.
- Security defaults for context paths, custom OpenRouter base URLs, shell verification, and file materialization.
