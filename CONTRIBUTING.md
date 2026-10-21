# Contributing to dotfix

Thanks for considering it. dotfix is a single Python file with no runtime
dependencies — please keep it that way.

## Ground rules

1. **No third-party dependencies.** Standard library only. If a feature genuinely
   needs a library, open an issue first and discuss it.
2. **One file.** `dotfix` stays a single self-contained script so it can be
   `curl`'d and run. If you need to split it, that's a major discussion.
3. **Python 3.9+.** No `match`, no `X | Y` type syntax at runtime.
4. **Never destroy user data.** Real files in the target are only overwritten
   with `--force`. `clean` only removes symlinks, never regular files.

## Development

```bash
git clone https://github.com/zenithlovesyou/dotfix
cd dotfix
python3 -m unittest discover -s tests -v
```

The test suite builds a fake `HOME` in a temp dir, so it never touches your
real `~/.config`.

## Adding a command

1. Add `cmd_<name>(args)` near the other command functions.
2. Register it in the `commands` dict in `main()`.
3. Add an argparse subparser.
4. Add tests to `tests/test_dotfix.py`.

## Style

- 4-space indent, no tabs.
- f-strings for formatting.
- Colors go through the `Color` class — don't inline escape codes.
- Use `pathlib.Path` over `os.path` in new code.
