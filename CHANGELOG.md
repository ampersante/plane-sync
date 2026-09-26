# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-09-27

### Added

- `plane-sync` CLI with subcommands: `snapshot`, `fetch`, `write`, `diff`, `profiles`, `init`.
- Snapshot: read a Plane project (work items, modules, pages, intake) to markdown, with concurrent relation/page fetch.
- Fetch: pull a single work item, page, module, or intake list.
- Write: create/update work items, modules, pages, and intake from markdown; dry-run by default, `--execute` to apply.
- Diff: compare two snapshot markdown files by work item, as text or `--json`.
- Config lives in `~/.config/plane-sync` (`profiles.json`, `.env`), separate from the install itself.
- `curl`-based installer (`install.sh`) and Homebrew tap for one-line install, upgrade, and uninstall.
- Agent contract (`docs/agent-contract.md`) and `plane-sync init` to bootstrap agent memory files in a new project.
- Offline smoke gate (`scripts/smoke_offline.sh`) and GitHub Actions CI across Ubuntu/macOS and Python 3.10/3.13.
