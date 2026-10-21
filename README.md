# dotfix

[![CI](https://github.com/zenithlovesyou/dotfix/actions/workflows/ci.yml/badge.svg)](https://github.com/zenithlovesyou/dotfix/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**A dotfiles manager that actually handles multiple repositories.**

Most dotfiles tools assume you have exactly one repo and one target directory.
If you've ever split your config across two repos, migrated from chezmoi, or kept
a second "extras" repo for themes you only use sometimes, those tools fall over.

`dotfix` treats repositories as **ordered layers**. The first repo that claims a
config name owns it. Later repos are *shadowed* — visible, but never fighting
over the same symlink.

```
dotfix/
├── dotfiles/          ← layer 1, owns: hypr, kitty, nvim, tmux, ...
└── hypr-dotfiles/     ← layer 2, owns: swaync, neofetch
                        (hypr, kitty, rofi, waybar are shadowed)
```

Zero dependencies. Single Python file. Works on Linux, macOS, Windows, WSL, Termux.

---

## Why

| Problem | What `dotfix` does |
|---|---|
| Two dotfiles repos both contain `hypr/` | Layered precedence — first repo wins, no conflict |
| Symlink points to a deleted path | `doctor` flags it, `sync` repairs it |
| Edited a config in `~/.config` and lost the change | `diff` shows drift, `backup` saves the local copy |
| Orphan symlinks from a removed repo | `clean` finds and removes them |
| Copied config to a new machine by hand | `sync` recreates every link |
| Repo has a different layout (`config/*` vs top-level) | Per-repo glob patterns |

---

## Install

### From source (no dependencies)

```bash
curl -fsSL https://raw.githubusercontent.com/zenithlovesyou/dotfix/main/dotfix.py \
  -o ~/.local/bin/dotfix
chmod +x ~/.local/bin/dotfix
```

Or clone and run the installer:

```bash
git clone https://github.com/zenithlovesyou/dotfix
cd dotfix
./install.sh
```

### With pip / uv

```bash
uv tool install dotfix      # or: pipx install dotfix
```

---

## Quick start

```bash
dotfix init          # auto-detect ~/dotfiles and ~/.dotfiles
dotfix doctor       # audit every symlink
dotfix sync         # create / repair them
```

---

## Commands

### `dotfix init`
Scans for known dotfiles repos and writes a state file. Edit `~/.local/state/dotfix/state.json`
or use `dotfix repo` to fine-tune.

### `dotfix doctor`
Health check for every managed symlink:

```
  dotfix → /home/zeph/.config
  ✓ OK: kitty
  ⚠ Drift: alacritty (exists as regular file/dir (not a symlink))
  ✗ Broken symlink: hypr (points to /home/zeph/.config/zeph instead of /home/zeph/dotfiles/hypr)
  ○ Missing symlink: swaync

  hypr-dotfiles → /home/zeph/.config
  ◌ Shadowed: kitty (owned by dotfiles)
  ◌ Shadowed: rofi (owned by dotfiles)
  ✓ OK: swaync
```

| Symbol | Meaning |
|---|---|
| `✓` | symlink is correct |
| `⚠` | target exists but isn't a symlink, or content drifted |
| `✗` | broken symlink — points at something that no longer exists |
| `○` | symlink missing, source present |
| `◌` | shadowed — an earlier repo owns this name |

### `dotfix sync`
Recreates missing symlinks, repairs broken ones. Conflicts (real files in the
target) are **never** overwritten without `--force`.

```bash
dotfix sync             # safe: skips conflicts
dotfix sync -n          # dry run, shows what would change
dotfix sync --force     # overwrite conflicts (back up first!)
dotfix backup           # save conflicting files before forcing
```

### `dotfix diff`
Shows content differences between a repo and the live config. Works on single
files and whole directory trees.

### `dotfix clean`
Removes orphan and broken symlinks from the target directory. Dry-run by default
in spirit — always pass `-n` first.

```bash
dotfix clean -n      # preview
dotfix clean         # do it
```

### `dotfix repo`
Manage source repos.

```bash
dotfix repo list
dotfix repo add ~/my-dots --name mydots
dotfix repo add ~/dots --patterns "config/*" --ignore ".git" "*.bak"
dotfix repo remove mydots
```

**Repo order matters** — the first repo listed has the highest priority.

---

## Config

State lives in `~/.local/state/dotfix/state.json`:

```json
{
  "repos": [
    {
      "name": "dotfiles",
      "path": "/home/zeph/dotfiles",
      "target": "/home/zeph/.config",
      "patterns": ["*"],
      "ignore": [".git", "*.md", "README*", "LICENSE*", "install.sh"]
    }
  ]
}
```

### Patterns

| Pattern | Matches |
|---|---|
| `*` | every top-level entry in the repo |
| `config/*` | every entry inside `repo/config/` |
| `nvim` | the entry `repo/nvim` itself |
| `neof*` | top-level entries starting with `neof` |

---

## Platform support

| Platform | Config dir |
|---|---|
| Linux | `$XDG_CONFIG_HOME` or `~/.config` |
| macOS | `~/Library/Application Support` |
| Windows | `%APPDATA%` |
| WSL | Linux paths, symlinks work natively |
| Termux | `$HOME/.config` |

Symlink creation on Windows requires Developer Mode or admin rights — `dotfix`
reports the failure rather than crashing.

---

## Development

```bash
git clone https://github.com/zenithlovesyou/dotfix
cd dotfix
python3 -m unittest discover -s tests -v
```

The suite builds a fake `HOME` in a temp dir, so it never touches a real
`~/.config`.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). The short version: stdlib only, one
file, Python 3.9+, and never destroy user data without `--force`.

## License

MIT — see [LICENSE](LICENSE).
