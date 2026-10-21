# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- **Windows symlink comparison.** `os.readlink()` on Windows returns a device
  path with the `\\?\` extended-length prefix (`\\?\C:\Users\me`), which never
  matched a plain path. Every correctly-linked symlink was therefore
  misreported as drift, and a hand-made link was not recognised as a
  conflict. `strip_extended_prefix()` normalises both sides before comparing.
- The test harness decoded the tool's output with the platform's default
  encoding (cp1252 on Windows) while the tool writes UTF-8; it now decodes
  explicitly.
- The test harness gave the tool a child environment containing only the
  sandbox HOME variables. On Windows a process without `SystemRoot` cannot
  load the crypto library, which killed Python 3.9 and 3.10 before `main()`.
- **Windows console encoding.** Windows consoles default to a legacy code page
  (cp1252), which cannot represent the box-drawing and status characters the
  tool prints. Every command died with a `UnicodeEncodeError` before doing any
  work. stdout/stderr are now reconfigured to UTF-8 with a replacement
  fallback.
- Windows directory symlinks are reparse points, so `unlink()` on one raises
  `PermissionError`; `rmdir()` is the call that removes the link itself.
  `remove_symlink()` handles both, and never follows the link.
- macOS `Path.resolve()` collapses symlinked parents (`/var` → `/private/var`);
  `dotfix` now compares resolved paths and reports dangling links correctly.
- Windows `Path.home()` ignores `$HOME` (uses `USERPROFILE`), which made the
  tool unable to follow a sandbox's fake home; `user_home()` honors `$HOME`.
- Windows directory symlinks were created without `target_is_directory=True`,
  so pathlib created them as file symlinks; `create_symlink` now sets the flag.
- `dotfix diff` silently failed on Linux/macOS where the `diff` binary is
  absent; switched to pure-Python `difflib` for files and a recursive sha-set
  comparison for directories — no platform binary required.
- A symlink pointing at some other live location was clobbered silently; now
  reported as a conflict unless `--force`.
- Broken-vs-orphan classification in `clean` and `import` used `resolve()`'s
  (non-raising) behaviour, making "broken" detection dead code on modern Python.
- `clean` did not report shadowed repo copies as managed when scanning shared
  targets, and `import` could double-report each symlink. Both fixed.
- The test suite now skips symlink-dependent tests on platforms that cannot
  create symlinks without elevation, and CI reports whether the runner
  supports them, so a skipped test is never mistaken for a passing one.

[Unreleased]: https://github.com/zenithlovesyou/dotfix/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/zenithlovesyou/dotfix/releases/tag/v0.1.0

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
