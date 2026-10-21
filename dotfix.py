#!/usr/bin/env python3
"""
dotfix - Multi-repo dotfiles manager with drift detection and symlink repair.
Handles multiple source repos, broken symlinks, and cross-platform config sync.
"""

import os
import sys
import json
import shutil
import subprocess
import argparse
import hashlib
import locale
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum

# Keep subprocess output (diff, etc.) in English regardless of the user's locale.
os.environ["LC_ALL"] = "C"
os.environ["LANG"] = "C"


class Color:
    RED = "\033[0;31m"
    GREEN = "\033[0;32m"
    YELLOW = "\033[0;33m"
    BLUE = "\033[0;34m"
    MAGENTA = "\033[0;35m"
    CYAN = "\033[0;36m"
    WHITE = "\033[0;37m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RESET = "\033[0m"


class Platform(Enum):
    LINUX = "linux"
    WINDOWS = "windows"
    MACOS = "macos"
    WSL = "wsl"
    TERMUX = "termux"


@dataclass
class RepoConfig:
    name: str
    path: Path
    target: Path = field(default_factory=lambda: Path.home() / ".config")
    patterns: list[str] = field(default_factory=lambda: ["*"])
    ignore: list[str] = field(default_factory=lambda: [".git", "*.md", "README*", "LICENSE*", "install.sh", "preview*.png", "nvim_preview.png"])


@dataclass
class SymlinkInfo:
    source: Path
    target: Path
    exists: bool
    valid: bool
    broken: bool
    target_exists: bool
    drift: bool = False
    drift_details: str = ""


def detect_platform() -> Platform:
    if os.environ.get("TERMUX_VERSION"):
        return Platform.TERMUX
    if sys.platform == "win32" or os.environ.get("MSYSTEM") or os.environ.get("CYGWIN"):
        return Platform.WINDOWS
    if sys.platform == "darwin":
        return Platform.MACOS
    if Path("/proc/version").exists() and "microsoft" in Path("/proc/version").read_text().lower():
        return Platform.WSL
    return Platform.LINUX


PLATFORM = detect_platform()


def load_repos() -> list[RepoConfig]:
    state = load_state()
    repos = []
    for r in state.get("repos", []):
        repos.append(RepoConfig(
            name=r["name"],
            path=Path(r["path"]),
            target=Path(r["target"]),
            patterns=r.get("patterns", ["*"]),
            ignore=r.get("ignore", [".git", "*.md", "README*", "LICENSE*", "install.sh", "preview*.png", "nvim_preview.png"]),
        ))
    return repos if repos else DEFAULT_REPOS


def find_config_dir() -> Path:
    if PLATFORM == Platform.WINDOWS:
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    if PLATFORM == Platform.MACOS:
        return Path.home() / "Library" / "Application Support"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))


CONFIG_DIR = find_config_dir()
DEFAULT_REPOS = [
    RepoConfig("dotfiles", Path.home() / "dotfiles", CONFIG_DIR),
    RepoConfig("dotfiles-alt", Path.home() / ".dotfiles", CONFIG_DIR),
]
STATE_FILE = Path.home() / ".local" / "state" / "dotfix" / "state.json"


def ensure_state_dir():
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)


def load_state() -> dict:
    ensure_state_dir()
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            return {}
    return {}


def save_state(state: dict):
    ensure_state_dir()
    STATE_FILE.write_text(json.dumps(state, indent=2))


def sha256_file(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    except Exception:
        return ""


def should_ignore(name: str, ignore_patterns: list[str]) -> bool:
    for pat in ignore_patterns:
        if pat.endswith("*"):
            if name.startswith(pat[:-1]):
                return True
        elif pat.startswith("*"):
            if name.endswith(pat[1:]):
                return True
        elif name == pat:
            return True
    return False


def scan_repo(repo: RepoConfig) -> list[Path]:
    """Return list of items in repo that should be symlinked.

    Patterns are matched against the path relative to the repo root:
      "*"            -> every top-level entry
      "config/*"     -> every entry inside repo/config/
      "nvim"         -> the entry repo/nvim itself
    """
    items: list[Path] = []
    if not repo.path.exists():
        return items

    seen: set[Path] = set()

    def add(p: Path):
        if p in seen:
            return
        if should_ignore(p.name, repo.ignore):
            return
        seen.add(p)
        items.append(p)

    for pat in repo.patterns:
        if pat == "*":
            for item in sorted(repo.path.iterdir()):
                add(item)
            continue

        if "/" in pat:
            base, _, glob = pat.rpartition("/")
            base_dir = repo.path / base
            if not base_dir.is_dir():
                continue
            if glob == "*":
                for sub in sorted(base_dir.iterdir()):
                    add(sub)
            else:
                for sub in sorted(base_dir.glob(glob)):
                    add(sub)
            continue

        if pat.endswith("*"):
            prefix = pat[:-1]
            for item in sorted(repo.path.iterdir()):
                if item.name.startswith(prefix):
                    add(item)
            continue

        exact = repo.path / pat
        if exact.exists():
            add(exact)

    return items


def check_symlink(source: Path, target: Path) -> SymlinkInfo:
    target_path = target / source.name
    exists = target_path.exists() or target_path.is_symlink()
    valid = False
    broken = False
    target_exists = source.exists()
    drift = False
    drift_details = ""

    if exists:
        if target_path.is_symlink():
            try:
                resolved = target_path.resolve()
                valid = resolved == source.resolve()
                broken = not valid
                if not valid:
                    drift = True
                    drift_details = f"points to {resolved} instead of {source}"
            except Exception:
                broken = True
                drift = True
                drift_details = "broken symlink (cannot resolve)"
        else:
            valid = False
            broken = False
            drift = True
            drift_details = "exists as regular file/dir (not a symlink)"
            if source.is_file() and target_path.is_file():
                if sha256_file(source) != sha256_file(target_path):
                    drift_details += " + content differs"
    return SymlinkInfo(source, target_path, exists, valid, broken, target_exists, drift, drift_details)


@dataclass
class PlanEntry:
    """One item to be symlinked, with ownership resolved across repos."""
    repo: RepoConfig
    item: Path
    owner: Optional[RepoConfig] = None  # repo that actually owns this name
    shadowed: bool = False

    @property
    def is_owner(self) -> bool:
        return self.owner is not None and self.owner.name == self.repo.name


def build_plan(repos: list[RepoConfig]) -> list[PlanEntry]:
    """Resolve which repo owns each target name.

    Repos are consulted in priority order; the first repo to claim a given
    target name owns it. Later repos claiming the same name are shadowed —
    their copy is left alone rather than fighting over the symlink.
    """
    owner_of: dict[str, RepoConfig] = {}
    plan: list[PlanEntry] = []

    for repo in repos:
        for item in scan_repo(repo):
            name = item.name
            if name in owner_of:
                plan.append(PlanEntry(repo, item, owner=owner_of[name], shadowed=True))
            else:
                owner_of[name] = repo
                plan.append(PlanEntry(repo, item, owner=repo, shadowed=False))

    return plan


def print_header(text: str):
    print(f"\n{Color.BOLD}{Color.CYAN}╭─ {text} {'─' * (60 - len(text))}{Color.RESET}")


def print_item(label: str, value: str, color: str = Color.WHITE):
    print(f"  {Color.DIM}{label}:{Color.RESET} {color}{value}{Color.RESET}")


def print_status(icon: str, text: str, color: str = Color.WHITE):
    print(f"  {color}{icon}{Color.RESET} {text}")


def cmd_doctor(args):
    print_header("dotfix doctor")
    print_item("Platform", PLATFORM.value.upper(), Color.CYAN)
    print_item("Config dir", str(CONFIG_DIR), Color.CYAN)
    print_item("State file", str(STATE_FILE), Color.CYAN)

    repos = load_repos()

    total_broken = 0
    total_drift = 0
    total_missing = 0
    total_ok = 0
    total_shadowed = 0

    plan = build_plan(repos)
    by_repo: dict[str, list[PlanEntry]] = {}
    for entry in plan:
        by_repo.setdefault(entry.repo.name, []).append(entry)

    for repo in repos:
        print(f"\n  {Color.BOLD}{repo.name}{Color.RESET} → {repo.target}")
        if not repo.path.exists():
            print_status("✗", f"Source repo not found: {repo.path}", Color.RED)
            continue

        entries = by_repo.get(repo.name, [])
        if not entries:
            print_status("○", "No items to manage", Color.DIM)
            continue

        for entry in entries:
            if entry.shadowed:
                print_status(
                    "◌",
                    f"Shadowed: {entry.item.name} (owned by {entry.owner.name})",
                    Color.MAGENTA,
                )
                total_shadowed += 1
                continue

            info = check_symlink(entry.item, repo.target)
            if not info.target_exists:
                print_status("✗", f"Source missing: {entry.item.name}", Color.RED)
                total_missing += 1
            elif not info.exists:
                print_status("○", f"Missing symlink: {entry.item.name}", Color.YELLOW)
                total_missing += 1
            elif info.broken:
                print_status("✗", f"Broken symlink: {entry.item.name} ({info.drift_details})", Color.RED)
                total_broken += 1
            elif info.drift:
                print_status("⚠", f"Drift: {entry.item.name} ({info.drift_details})", Color.YELLOW)
                total_drift += 1
            else:
                print_status("✓", f"OK: {entry.item.name}", Color.GREEN)
                total_ok += 1

    print(
        f"\n  {Color.BOLD}Summary:{Color.RESET} {Color.GREEN}{total_ok} ok{Color.RESET}  "
        f"{Color.YELLOW}{total_drift} drift{Color.RESET}  {Color.RED}{total_broken} broken{Color.RESET}  "
        f"{Color.YELLOW}{total_missing} missing{Color.RESET}  {Color.MAGENTA}{total_shadowed} shadowed{Color.RESET}"
    )


def cmd_status(args):
    cmd_doctor(args)


def cmd_add_repo(args):
    state = load_state()
    repos = state.get("repos", [])

    repo_path = Path(args.path).expanduser().resolve()
    if not repo_path.exists():
        print(f"{Color.RED}Path does not exist: {repo_path}{Color.RESET}")
        return 1

    name = args.name or repo_path.name
    target = Path(args.target).expanduser().resolve() if args.target else CONFIG_DIR

    new_repo = {
        "name": name,
        "path": str(repo_path),
        "target": str(target),
        "patterns": args.patterns or ["*"],
        "ignore": args.ignore or [".git", "*.md", "README*", "LICENSE*", "install.sh"],
    }

    for i, r in enumerate(repos):
        if r["name"] == name:
            repos[i] = new_repo
            print(f"{Color.GREEN}Updated repo: {name}{Color.RESET}")
            break
    else:
        repos.append(new_repo)
        print(f"{Color.GREEN}Added repo: {name}{Color.RESET}")

    state["repos"] = repos
    save_state(state)
    return 0


def cmd_list_repos(args):
    state = load_state()
    repos = state.get("repos", [])
    if not repos:
        print(f"{Color.DIM}No repos configured. Using defaults:{Color.RESET}")
        for r in DEFAULT_REPOS:
            print(f"  {r.name}: {r.path} → {r.target}")
        return

    print(f"{Color.BOLD}Configured repos:{Color.RESET}")
    for r in repos:
        path = Path(r["path"])
        exists = "✓" if path.exists() else "✗"
        print(f"  {exists} {r['name']}: {r['path']} → {r['target']}")


def cmd_remove_repo(args):
    state = load_state()
    repos = state.get("repos", [])
    repos = [r for r in repos if r["name"] != args.name]
    state["repos"] = repos
    save_state(state)
    print(f"{Color.GREEN}Removed repo: {args.name}{Color.RESET}")
    return 0


def cmd_sync(args):
    repos = load_repos()

    dry_run = args.dry_run
    force = args.force
    repaired = 0
    created = 0
    skipped = 0
    shadowed = 0
    errors = 0

    # Report repos whose source is missing before touching anything.
    usable = []
    for repo in repos:
        if not repo.path.exists():
            print(f"{Color.RED}Skip {repo.name}: source not found ({repo.path}){Color.RESET}")
            errors += 1
        else:
            usable.append(repo)

    plan = build_plan(usable)
    current_repo = None

    for entry in plan:
        repo = entry.repo
        item = entry.item

        if repo.name != current_repo:
            current_repo = repo.name
            print(f"\n  {Color.BOLD}{repo.name}{Color.RESET}")

        if entry.shadowed:
            if args.verbose:
                print(f"{Color.MAGENTA}  ◌ Shadowed: {item.name} (owned by {entry.owner.name}){Color.RESET}")
            shadowed += 1
            continue

        info = check_symlink(item, repo.target)

        if not info.target_exists:
            print(f"{Color.RED}  ✗ Source missing: {item.name}{Color.RESET}")
            errors += 1
            continue

        if info.valid:
            if args.verbose:
                print(f"{Color.GREEN}  ✓ Already synced: {item.name}{Color.RESET}")
            skipped += 1
            continue

        if info.exists and not force and not info.broken:
            print(f"{Color.YELLOW}  ⊘ Conflict (use --force): {item.name}{Color.RESET}")
            skipped += 1
            continue

        target_path = repo.target / item.name
        if dry_run:
            action = "Would create" if not info.exists else "Would repair"
            print(f"{Color.BLUE}  → {action}: {item.name}{Color.RESET}")
            continue

        try:
            if target_path.exists() or target_path.is_symlink():
                if target_path.is_dir() and not target_path.is_symlink():
                    shutil.rmtree(target_path)
                else:
                    target_path.unlink()

            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.symlink_to(item.resolve())
            if info.exists:
                print(f"{Color.YELLOW}  ⟳ Repaired: {item.name}{Color.RESET}")
                repaired += 1
            else:
                print(f"{Color.GREEN}  ✓ Created: {item.name}{Color.RESET}")
                created += 1
        except Exception as e:
            print(f"{Color.RED}  ✗ Failed: {item.name} ({e}){Color.RESET}")
            errors += 1

    if not dry_run:
        print(
            f"\n{Color.BOLD}Done:{Color.RESET} {Color.GREEN}{created} created{Color.RESET}  "
            f"{Color.YELLOW}{repaired} repaired{Color.RESET}  {Color.DIM}{skipped} skipped{Color.RESET}  "
            f"{Color.MAGENTA}{shadowed} shadowed{Color.RESET}  {Color.RED}{errors} errors{Color.RESET}"
        )
    return 0 if errors == 0 else 1


def cmd_clean(args):
    repos = load_repos()

    # Only the owning repo's items count as managed; shadowed copies are not
    # targets, so a symlink pointing at one is still an orphan.
    all_managed = set()
    for entry in build_plan(repos):
        if entry.shadowed:
            continue
        all_managed.add((entry.repo.target / entry.item.name).resolve())

    dry_run = args.dry_run
    removed = 0

    seen_targets = set()
    for repo in repos:
        if not repo.target.exists():
            continue
        if repo.target in seen_targets:
            continue
        seen_targets.add(repo.target)

        for target_item in sorted(repo.target.iterdir()):
            if not target_item.is_symlink():
                continue
            try:
                resolved = target_item.resolve()
                if resolved in all_managed:
                    continue
                reason = "orphan"
            except Exception:
                resolved = None
                reason = "broken"

            if dry_run:
                arrow = f" → {resolved}" if resolved else ""
                print(f"{Color.BLUE}  → Would remove {reason}: {target_item.name}{arrow}{Color.RESET}")
            else:
                target_item.unlink()
                print(f"{Color.RED}  ✗ Removed {reason}: {target_item.name}{Color.RESET}")
                removed += 1

    if not dry_run:
        print(f"\n{Color.BOLD}Removed {removed} orphan/broken symlinks{Color.RESET}")
    return 0


def cmd_diff(args):
    repos = load_repos()
    changes = 0

    for entry in build_plan(repos):
        repo, item = entry.repo, entry.item
        if entry.shadowed:
            continue
        if not repo.path.exists():
            continue

        target_path = repo.target / item.name
        if not (target_path.exists() and not target_path.is_symlink()):
            continue

        if item.is_file() and target_path.is_file():
            if sha256_file(item) != sha256_file(target_path):
                print(f"{Color.YELLOW}Drift:{Color.RESET} {repo.name}/{item.name}")
                try:
                    subprocess.run(["diff", "-u", str(item), str(target_path)], check=False)
                except Exception:
                    pass
                changes += 1
        elif item.is_dir() and target_path.is_dir():
            # Compare directory trees
            try:
                result = subprocess.run(
                    ["diff", "-r", "-q", str(item), str(target_path)],
                    capture_output=True, text=True, check=False,
                )
                if result.stdout.strip():
                    print(f"{Color.YELLOW}Drift:{Color.RESET} {repo.name}/{item.name}")
                    print(result.stdout)
                    changes += 1
            except Exception:
                pass

    if not changes:
        print(f"{Color.GREEN}No drift detected.{Color.RESET}")
    return 0


def cmd_backup(args):
    """Back up conflicting real files before a forced sync."""
    repos = load_repos()
    backup_root = Path.home() / ".local" / "state" / "dotfix" / "backups"
    stamp = args.stamp or str(int(__import__("time").time()))

    dest = backup_root / stamp
    dest.mkdir(parents=True, exist_ok=True)

    saved = 0
    for entry in build_plan(repos):
        if entry.shadowed:
            continue
        repo, item = entry.repo, entry.item
        target_path = repo.target / item.name
        if not target_path.exists() or target_path.is_symlink():
            continue
        try:
            out = dest / repo.name / item.name
            out.parent.mkdir(parents=True, exist_ok=True)
            if target_path.is_dir():
                shutil.copytree(target_path, out, dirs_exist_ok=True)
            else:
                shutil.copy2(target_path, out)
            print(f"{Color.GREEN}  ✓ Backed up: {repo.name}/{item.name}{Color.RESET}")
            saved += 1
        except Exception as e:
            print(f"{Color.RED}  ✗ Failed to back up {item.name}: {e}{Color.RESET}")

    print(f"\n{Color.BOLD}Backed up {saved} item(s) to {dest}{Color.RESET}")
    return 0


def cmd_init(args):
    print_header("dotfix init")
    print("This will set up dotfix with your existing repos.\n")

    found = []
    for default in DEFAULT_REPOS:
        if default.path.exists():
            found.append(default)
            print(f"  {Color.GREEN}✓ Found:{Color.RESET} {default.name} at {default.path}")

    if not found:
        print(f"  {Color.YELLOW}No default repos found. Add manually with 'dotfix repo add'.{Color.RESET}")

    state = {"repos": [{"name": r.name, "path": str(r.path), "target": str(r.target), "patterns": r.patterns, "ignore": r.ignore} for r in found]}
    save_state(state)
    print(f"\n{Color.GREEN}Initialized state at {STATE_FILE}{Color.RESET}")
    return 0


def cmd_import(args):
    """Report which existing symlinks in the target are already managed."""
    repos = load_repos()

    # Build the set of every path a repo claims, across all repos. A symlink is
    # managed if it points at any of them — not just the ones for one repo.
    managed_paths = {}
    for entry in build_plan(repos):
        try:
            managed_paths.setdefault(entry.item.resolve(), entry.repo.name)
        except Exception:
            continue

    # Scan each distinct target directory exactly once.
    scanned = set()
    imported = 0
    orphans = 0
    broken = 0

    for repo in repos:
        target = repo.target
        if not target.exists() or target in scanned:
            continue
        scanned.add(target)

        for target_item in sorted(target.iterdir()):
            if not target_item.is_symlink():
                continue
            try:
                resolved = target_item.resolve()
            except Exception:
                print(f"{Color.RED}  ✗ Broken: {target_item.name}{Color.RESET}")
                broken += 1
                continue

            owner = managed_paths.get(resolved)
            if owner:
                print(f"{Color.GREEN}  ✓ Managed: {target_item.name} → {owner}{Color.RESET}")
                imported += 1
            else:
                print(f"{Color.YELLOW}  ? Orphan: {target_item.name} → {resolved}{Color.RESET}")
                orphans += 1

    print(
        f"\n{Color.BOLD}Managed: {Color.GREEN}{imported}{Color.RESET}  "
        f"{Color.YELLOW}orphans: {orphans}{Color.RESET}  "
        f"{Color.RED}broken: {broken}{Color.RESET}"
    )
    return 0
    return 0


def main():
    parser = argparse.ArgumentParser(
        prog="dotfix",
        description="Multi-repo dotfiles manager with drift detection and symlink repair",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  dotfix init                    # Auto-detect and configure repos
  dotfix doctor                  # Check symlink health
  dotfix sync                    # Create/repair all symlinks
  dotfix sync --dry-run          # Preview changes
  dotfix clean                   # Remove orphan/broken symlinks
  dotfix repo add ~/my-dots      # Add a custom repo
  dotfix diff                    # Show content differences
        """
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")

    sub = parser.add_subparsers(dest="cmd", required=True)

    # doctor/status
    sub.add_parser("doctor", help="Check symlink health (alias: status)")
    sub.add_parser("status", help="Alias for doctor")

    # sync
    p_sync = sub.add_parser("sync", help="Create/repair symlinks")
    p_sync.add_argument("--dry-run", "-n", action="store_true", help="Preview changes")
    p_sync.add_argument("--force", "-f", action="store_true", help="Overwrite conflicts")

    # clean
    p_clean = sub.add_parser("clean", help="Remove orphan/broken symlinks")
    p_clean.add_argument("--dry-run", "-n", action="store_true", help="Preview changes")

    # diff
    sub.add_parser("diff", help="Show content drift between source and target")

    # backup
    p_backup = sub.add_parser("backup", help="Back up conflicting real files in the target")
    p_backup.add_argument("--stamp", help="Backup folder name (default: timestamp)")

    # init
    sub.add_parser("init", help="Auto-detect and configure repos")

    # import
    sub.add_parser("import", help="Import existing symlinks as managed")

    # repo management
    p_repo = sub.add_parser("repo", help="Manage source repositories")
    repo_sub = p_repo.add_subparsers(dest="repo_cmd", required=True)

    p_add = repo_sub.add_parser("add", help="Add a repository")
    p_add.add_argument("path", help="Path to dotfiles repo")
    p_add.add_argument("--name", help="Repo name (default: directory name)")
    p_add.add_argument("--target", help="Target directory (default: XDG_CONFIG_HOME)")
    p_add.add_argument("--patterns", nargs="+", help="Glob patterns to include")
    p_add.add_argument("--ignore", nargs="+", help="Glob patterns to ignore")

    repo_sub.add_parser("list", help="List configured repositories")

    p_remove = repo_sub.add_parser("remove", help="Remove a repository")
    p_remove.add_argument("name", help="Repository name")

    args = parser.parse_args()

    commands = {
        "doctor": cmd_doctor,
        "status": cmd_status,
        "sync": cmd_sync,
        "clean": cmd_clean,
        "diff": cmd_diff,
        "backup": cmd_backup,
        "init": cmd_init,
        "import": cmd_import,
        "repo": lambda a: None,
    }

    if args.cmd == "repo":
        repo_commands = {
            "add": cmd_add_repo,
            "list": cmd_list_repos,
            "remove": cmd_remove_repo,
        }
        return repo_commands[args.repo_cmd](args)

    return commands[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())