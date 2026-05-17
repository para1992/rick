# Changelog

## 0.1.0 - Unreleased

Initial alpha release of Rick, a local CLI for staged LLM workflows.

Highlights:

- Workflow DSL with `RESOLVE`, `CONTEXT`, `GEN`, `JUDGE`, `EDIT`, output glue, materialization, and verification steps.
- Multiple candidate generation with DoD-based judging.
- Markdown and JSON run logs for inspection and regression work.
- OpenRouter integration with local mock fallback when no API key is configured.
- Interactive terminal UI for local workflow runs.
- Security defaults for context paths, custom OpenRouter base URLs, shell verification, and file materialization.
