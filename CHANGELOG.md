# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-10-21

Initial release.

### Added

- **Multi-repo layering.** Repos are consulted in priority order; the first
  repo to claim a config name owns it. Later repos claiming the same name are
  reported as *shadowed* and never fight over the symlink.
- `dotfix doctor` — audits every managed symlink and reports one of:
  ok, drift, broken, missing, or shadowed.
- `dotfix sync` — creates missing and repairs broken symlinks. Conflicts
  (real files in the target) are never overwritten without `--force`.
  Supports `--dry-run`.
- `dotfix diff` — shows content drift between a repo and the live config,
  for both single files and directory trees.
- `dotfix clean` — removes orphan and broken symlinks. Only ever removes
  symlinks, never regular files. Supports `--dry-run`.
- `dotfix backup` — saves conflicting files to a timestamped folder before a
  forced sync.
- `dotfix repo add|list|remove` — manage source repos, with per-repo glob
  patterns (`*`, `config/*`, `neof*`) and ignore lists.
- `dotfix init` — auto-detects common dotfiles repo locations and writes
  the state file.
- `dotfix import` — reports which existing symlinks are already managed and
  which are orphans.
- Per-repo glob patterns, so repos with different layouts (`config/*` vs
  top-level) work side by side.
- Cross-platform config directory detection: Linux (`$XDG_CONFIG_HOME`),
  macOS (`~/Library/Application Support`), Windows (`%APPDATA%`), WSL, Termux.
- 21 unit tests that build a sandboxed `HOME` and never touch a real config.

### Safety

- Real files in the target directory are only replaced with `--force`.
- `clean` only deletes symlinks — regular files are left alone.
- `backup` preserves conflicting content before any forced overwrite.

[Unreleased]: https://github.com/zenithlovesyou/dotfix/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/zenithlovesyou/dotfix/releases/tag/v0.1.0
