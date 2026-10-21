# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | ✅        |

## Reporting a vulnerability

Please **do not open a public issue** for security problems.

Instead, report privately via GitHub's
[private vulnerability reporting](https://github.com/zenithlovesyou/dotfix/security/advisories/new),
or by email.

Include:
- What the issue is and how it can be triggered
- The version or commit affected
- Your OS and Python version
- Any proof-of-concept steps

You can expect an acknowledgement within a few days and a fix or explanation
once the report has been confirmed.

## Scope

`dotfix` runs as your own user and only touches:
- the directories named in its state file (`~/.local/state/dotfix/state.json`)
- symlinks and (with `--force`) files in the target directories you configure

Things that are **in scope**:
- A path-traversal or escaping-the-target bug that lets `dotfix` write
  outside the configured target directory
- Command injection via repo paths, patterns, or config values
- `clean` or `sync` deleting something other than a symlink
- `clean` or `sync` following a symlink out of the target directory and
  deleting the real file behind it

Things that are **out of scope**:
- Data loss from a user running `sync --force` without reading the output
- Anything requiring the user to already have write access to your account
- Vulnerabilities in Python itself or in the base operating system
