## What this changes

<!-- Describe the change. -->

## Why

<!-- The problem it solves. Link any related issue: Fixes #123 -->

## Testing

- [ ] `python -m unittest discover -s tests -v` passes
- [ ] Tested on: <!-- Linux / macOS / Windows / WSL -->
- [ ] No new dependencies added (dotfix stays stdlib-only)

## Checklist

- [ ] Single file, no new runtime dependencies
- [ ] Python 3.9 compatible (no `match`, no PEP 604 unions at runtime)
- [ ] Destructive operations are opt-in (`--force`, `clean`)
- [ ] README updated if behavior changed
