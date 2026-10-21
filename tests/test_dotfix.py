#!/usr/bin/env python3
"""Test suite for dotfix.

Runs against a temporary sandbox so it never touches the real ~/.config.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

DOTFIX = Path(__file__).resolve().parent.parent / "dotfix.py"
# Make "import dotfix" work so the tests can exercise internals directly.
sys.path.insert(0, str(DOTFIX.parent))


def run(args, env=None, cwd=None):
    """Invoke dotfix as a subprocess and return (returncode, stdout, stderr)."""
    e = dict(os.environ)
    if env:
        e.update(env)
    e.setdefault("XDG_CONFIG_HOME", str(cwd) if cwd else "")
    proc = subprocess.run(
        [sys.executable, str(DOTFIX), *args],
        capture_output=True, text=True, env=e, cwd=cwd,
    )
    return proc.returncode, proc.stdout, proc.stderr


def make_symlink(link: Path, target: Path):
    """Create a symlink the way the platform expects it.

    Windows needs the directory flag set for directory targets, and pathlib
    only supports it from Python 3.10.
    """
    try:
        link.symlink_to(target, target_is_directory=target.is_dir())
    except TypeError:
        os.symlink(str(target), str(link), target_is_directory=target.is_dir())


def symlinks_supported() -> bool:
    """True if this platform lets us create symlinks without elevation.

    On Windows that needs Developer Mode or admin rights; CI runners have
    neither by default, so the symlink tests skip instead of failing.
    """
    probe_dir = Path(tempfile.mkdtemp(prefix="dotfix-probe-"))
    try:
        os.symlink(str(probe_dir), str(probe_dir / "link"), target_is_directory=True)
        return True
    except (OSError, NotImplementedError, AttributeError):
        return False
    finally:
        shutil.rmtree(probe_dir, ignore_errors=True)


class Sandbox:
    """Builds a fake HOME with repos and a config dir."""

    def __init__(self, home: Path, config: Path):
        self.home = home
        self.config = config
        self.repos = {}

    def make_repo(self, name, files: dict):
        """files: {'relpath': 'content'}"""
        repo = self.home / name
        repo.mkdir(parents=True, exist_ok=True)
        for rel, content in files.items():
            p = repo / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
        self.repos[name] = repo
        return repo

    def configure(self, repos: list):
        """repos: list of (name, path, patterns)"""
        state = {
            "repos": [
                {
                    "name": name,
                    "path": str(path),
                    "target": str(self.config),
                    "patterns": patterns,
                    "ignore": [".git", "*.md", "README*", "LICENSE*"],
                }
                for name, path, patterns in repos
            ]
        }
        state_dir = self.home / ".local" / "state" / "dotfix"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "state.json").write_text(json.dumps(state))
        return state


class DotfixTest(unittest.TestCase):
    def setUp(self):
        # Resolve the temp dir: on macOS /var is a symlink to /private/var, so
        # an unresolved path would never match the resolved symlink target.
        self.tmp = Path(tempfile.mkdtemp(prefix="dotfix-test-")).resolve()
        self.home = self.tmp / "home"
        self.config = self.home / ".config"
        self.home.mkdir(parents=True)
        self.config.mkdir(parents=True)
        self.sb = Sandbox(self.home, self.config)
        self.env = {
            "HOME": str(self.home),
            "USERPROFILE": str(self.home),
            "APPDATA": str(self.home / "AppData" / "Roaming"),
        }

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---------- helpers ----------

    def dotfix(self, *args):
        return run(list(args), env=self.env)

    def symlink_target(self, name):
        """Resolve a symlink in the config dir, or None if not a symlink."""
        p = self.config / name
        if p.is_symlink():
            return str(p.resolve())
        return None

    # ---------- tests ----------

    @unittest.skipUnless(symlinks_supported(),
                     "this platform cannot create symlinks")
    def test_sync_creates_symlinks(self):
        repo = self.sb.make_repo("dots", {"nvim/init.lua": "x", "tmux/tmux.conf": "y"})
        self.sb.configure([("dots", repo, ["*"])])

        rc, out, err = self.dotfix("sync")
        self.assertEqual(rc, 0, err)
        self.assertTrue((self.config / "nvim").is_symlink())
        self.assertTrue((self.config / "tmux").is_symlink())
        self.assertEqual(self.symlink_target("nvim"), str(repo / "nvim"))

    @unittest.skipUnless(symlinks_supported(),
                     "this platform cannot create symlinks")
    def test_doctor_reports_ok(self):
        repo = self.sb.make_repo("dots", {"nvim/init.lua": "x"})
        self.sb.configure([("dots", repo, ["*"])])
        self.dotfix("sync")

        rc, out, err = self.dotfix("doctor")
        self.assertEqual(rc, 0, err)
        self.assertIn("OK: nvim", out)

    @unittest.skipUnless(symlinks_supported(),
                     "this platform cannot create symlinks")
    def test_broken_symlink_is_detected_and_repaired(self):
        repo = self.sb.make_repo("dots", {"nvim/init.lua": "x"})
        self.sb.configure([("dots", repo, ["*"])])
        # Point the symlink at a path that does not exist
        make_symlink(self.config / "nvim", self.home / "gone")

        rc, out, err = self.dotfix("doctor")
        self.assertIn("Broken symlink: nvim", out)

        rc, out, err = self.dotfix("sync")
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.symlink_target("nvim"), str(repo / "nvim"))

    @unittest.skipUnless(symlinks_supported(),
                     "this platform cannot create symlinks")
    def test_missing_symlink_is_created(self):
        repo = self.sb.make_repo("dots", {"nvim/init.lua": "x"})
        self.sb.configure([("dots", repo, ["*"])])

        rc, out, err = self.dotfix("doctor")
        self.assertIn("Missing symlink: nvim", out)

        self.dotfix("sync")
        self.assertTrue((self.config / "nvim").is_symlink())

    def test_regular_file_is_drift_not_overwritten_without_force(self):
        repo = self.sb.make_repo("dots", {"nvim/init.lua": "x"})
        self.sb.configure([("dots", repo, ["*"])])
        (self.config / "nvim").mkdir()
        (self.config / "nvim" / "mine.lua").write_text("mine")

        rc, out, err = self.dotfix("doctor")
        self.assertIn("Drift: nvim", out)

        # sync without --force must not touch it
        rc, out, err = self.dotfix("sync")
        self.assertIn("Conflict", out)
        self.assertFalse((self.config / "nvim").is_symlink())
        self.assertTrue((self.config / "nvim" / "mine.lua").exists())

    @unittest.skipUnless(symlinks_supported(),
                     "this platform cannot create symlinks")
    def test_force_overwrites_regular_file(self):
        repo = self.sb.make_repo("dots", {"nvim/init.lua": "x"})
        self.sb.configure([("dots", repo, ["*"])])
        (self.config / "nvim").mkdir()

        rc, out, err = self.dotfix("sync", "--force")
        self.assertEqual(rc, 0, err)
        self.assertTrue((self.config / "nvim").is_symlink())

    @unittest.skipUnless(symlinks_supported(),
                     "this platform cannot create symlinks")
    def test_conflict_on_symlink_to_other_location(self):
        """A symlink pointing somewhere we don't own is skipped, not clobbered."""
        repo = self.sb.make_repo("dots", {"nvim/init.lua": "x"})
        self.sb.configure([("dots", repo, ["*"])])

        # The user linked nvim to their own location by hand.
        mine = self.home / "my-nvim"
        mine.mkdir()
        (mine / "init.lua").write_text("mine")
        make_symlink(self.config / "nvim", mine)

        rc, out, err = self.dotfix("sync")
        self.assertIn("Conflict", out)
        # The hand-made link must survive untouched. readlink() on Windows
        # returns a \\?\ device path, so compare the resolved paths instead of
        # the raw strings.
        import importlib
        mod = importlib.import_module("dotfix")
        self.assertTrue(mod.same_path(os.readlink(str(self.config / "nvim")), str(mine)))
        self.assertTrue((self.config / "nvim" / "init.lua").exists())

    def test_backup_saves_conflicting_files(self):
        repo = self.sb.make_repo("dots", {"nvim/init.lua": "x"})
        self.sb.configure([("dots", repo, ["*"])])
        (self.config / "nvim").mkdir()
        (self.config / "nvim" / "mine.lua").write_text("mine")

        rc, out, err = self.dotfix("backup", "--stamp", "t1")
        self.assertEqual(rc, 0, err)
        saved = self.home / ".local" / "state" / "dotfix" / "backups" / "t1" / "dots" / "nvim" / "mine.lua"
        self.assertTrue(saved.exists())
        self.assertEqual(saved.read_text(), "mine")

    @unittest.skipUnless(symlinks_supported(),
                     "this platform cannot create symlinks")
    def test_precedence_first_repo_owns_name(self):
        r1 = self.sb.make_repo("first", {"nvim/init.lua": "1"})
        r2 = self.sb.make_repo("second", {"nvim/init.lua": "2"})
        self.sb.configure([("first", r1, ["*"]), ("second", r2, ["*"])])

        rc, out, err = self.dotfix("doctor")
        self.assertIn("Shadowed: nvim (owned by first)", out)

        self.dotfix("sync")
        self.assertEqual(self.symlink_target("nvim"), str(r1 / "nvim"))

    @unittest.skipUnless(symlinks_supported(),
                     "this platform cannot create symlinks")
    def test_precedence_order_is_respected(self):
        r1 = self.sb.make_repo("first", {"nvim/init.lua": "1"})
        r2 = self.sb.make_repo("second", {"nvim/init.lua": "2"})
        # Reversed order — second should own nvim now
        self.sb.configure([("second", r2, ["*"]), ("first", r1, ["*"])])

        rc, out, err = self.dotfix("doctor")
        self.assertIn("Shadowed: nvim (owned by second)", out)

        self.dotfix("sync")
        self.assertEqual(self.symlink_target("nvim"), str(r2 / "nvim"))

    @unittest.skipUnless(symlinks_supported(),
                     "this platform cannot create symlinks")
    def test_subdirectory_pattern(self):
        repo = self.sb.make_repo("dots", {"config/nvim/init.lua": "x", "config/kitty/kitty.conf": "y"})
        self.sb.configure([("dots", repo, ["config/*"])])

        rc, out, err = self.dotfix("sync")
        self.assertEqual(rc, 0, err)
        self.assertTrue((self.config / "nvim").is_symlink())
        self.assertTrue((self.config / "kitty").is_symlink())

    def test_ignore_patterns_are_skipped(self):
        repo = self.sb.make_repo("dots", {
            "nvim/init.lua": "x",
            "README.md": "readme",
            ".git/config": "git",
        })
        self.sb.configure([("dots", repo, ["*"])])

        self.dotfix("sync")
        self.assertTrue((self.config / "nvim").is_symlink())
        self.assertFalse((self.config / "README.md").exists())
        self.assertFalse((self.config / ".git").exists())

    @unittest.skipUnless(symlinks_supported(),
                     "this platform cannot create symlinks")
    def test_clean_removes_orphan_symlinks(self):
        repo = self.sb.make_repo("dots", {"nvim/init.lua": "x"})
        self.sb.configure([("dots", repo, ["*"])])
        self.dotfix("sync")

        # An orphan pointing somewhere outside any repo
        other = self.home / "other"
        other.mkdir()
        make_symlink(self.config / "orphan", other)

        rc, out, err = self.dotfix("clean", "--dry-run")
        self.assertIn("Would remove orphan: orphan", out)
        self.assertTrue((self.config / "orphan").is_symlink())

        rc, out, err = self.dotfix("clean")
        self.assertEqual(rc, 0, err)
        self.assertFalse((self.config / "orphan").exists())
        # managed symlink must survive
        self.assertTrue((self.config / "nvim").is_symlink())

    @unittest.skipUnless(symlinks_supported(),
                     "this platform cannot create symlinks")
    def test_clean_removes_broken_symlinks(self):
        repo = self.sb.make_repo("dots", {"nvim/init.lua": "x"})
        self.sb.configure([("dots", repo, ["*"])])
        make_symlink(self.config / "dangling", self.home / "nowhere")

        rc, out, err = self.dotfix("clean")
        self.assertEqual(rc, 0, err)
        self.assertFalse((self.config / "dangling").exists())

    def test_diff_reports_content_drift(self):
        repo = self.sb.make_repo("dots", {"file.txt": "repo version"})
        self.sb.configure([("dots", repo, ["*"])])
        (self.config / "file.txt").write_text("local version")

        rc, out, err = self.dotfix("diff")
        self.assertIn("Drift:", out)
        self.assertIn("file.txt", out)

    def test_diff_reports_no_drift_when_identical(self):
        repo = self.sb.make_repo("dots", {"file.txt": "same"})
        self.sb.configure([("dots", repo, ["*"])])
        (self.config / "file.txt").write_text("same")

        rc, out, err = self.dotfix("diff")
        self.assertIn("No drift detected", out)

    def test_dry_run_makes_no_changes(self):
        repo = self.sb.make_repo("dots", {"nvim/init.lua": "x"})
        self.sb.configure([("dots", repo, ["*"])])

        rc, out, err = self.dotfix("sync", "--dry-run")
        self.assertEqual(rc, 0, err)
        self.assertIn("Would create", out)
        self.assertFalse((self.config / "nvim").exists())

    def test_repo_add_and_list(self):
        repo = self.sb.make_repo("dots", {"nvim/init.lua": "x"})
        rc, out, err = self.dotfix("repo", "add", str(repo), "--name", "mydots")
        self.assertEqual(rc, 0, err)
        self.assertIn("Added repo: mydots", out)

        rc, out, err = self.dotfix("repo", "list")
        self.assertIn("mydots", out)

    def test_repo_remove(self):
        repo = self.sb.make_repo("dots", {"nvim/init.lua": "x"})
        self.sb.configure([("dots", repo, ["*"])])
        rc, out, err = self.dotfix("repo", "remove", "dots")
        self.assertIn("Removed repo: dots", out)

        rc, out, err = self.dotfix("repo", "list")
        self.assertNotIn("dots", out)

    @unittest.skipUnless(symlinks_supported(),
                     "this platform cannot create symlinks")
    def test_clean_does_not_follow_symlink_out_of_target(self):
        """clean must unlink the symlink, never delete the real file behind it."""
        repo = self.sb.make_repo("dots", {"nvim/init.lua": "x"})
        self.sb.configure([("dots", repo, ["*"])])

        precious = self.home / "precious"
        precious.mkdir()
        (precious / "file.txt").write_text("IMPORTANT DATA")
        make_symlink(self.config / "danger", precious)
        make_symlink(self.config / "dangerfile", precious / "file.txt")

        rc, out, err = self.dotfix("clean")
        self.assertEqual(rc, 0, err)

        # The symlinks are gone...
        self.assertFalse((self.config / "danger").exists())
        self.assertFalse((self.config / "dangerfile").exists())
        # ...but the real data survives untouched.
        self.assertTrue(precious.is_dir())
        self.assertTrue((precious / "file.txt").exists())
        self.assertEqual((precious / "file.txt").read_text(), "IMPORTANT DATA")

    def test_clean_never_removes_regular_files(self):
        repo = self.sb.make_repo("dots", {"nvim/init.lua": "x"})
        self.sb.configure([("dots", repo, ["*"])])

        plain = self.config / "plainfile"
        plain.write_text("not managed, must stay")
        plain_dir = self.config / "plaindir"
        plain_dir.mkdir()
        (plain_dir / "inside.txt").write_text("also must stay")

        rc, out, err = self.dotfix("clean")
        self.assertEqual(rc, 0, err)

        self.assertTrue(plain.exists())
        self.assertEqual(plain.read_text(), "not managed, must stay")
        self.assertTrue((plain_dir / "inside.txt").exists())

    @unittest.skipUnless(symlinks_supported(),
                     "this platform cannot create symlinks")
    def test_import_reports_managed_and_orphan(self):
        r1 = self.sb.make_repo("first", {"nvim/init.lua": "1"})
        r2 = self.sb.make_repo("second", {"swaync/config": "2"})
        self.sb.configure([("first", r1, ["*"]), ("second", r2, ["*"])])
        self.dotfix("sync")

        # An orphan pointing outside every repo
        other = self.home / "other"
        other.mkdir()
        make_symlink(self.config / "orphan", other)

        rc, out, err = self.dotfix("import")
        self.assertEqual(rc, 0, err)
        self.assertIn("Managed: nvim", out)
        self.assertIn("Managed: swaync", out)
        self.assertIn("Orphan: orphan", out)

    @unittest.skipUnless(symlinks_supported(),
                     "this platform cannot create symlinks")
    def test_import_scans_shared_target_once(self):
        """Two repos pointing at one target must not double-report symlinks."""
        r1 = self.sb.make_repo("first", {"nvim/init.lua": "1"})
        r2 = self.sb.make_repo("second", {"swaync/config": "2"})
        self.sb.configure([("first", r1, ["*"]), ("second", r2, ["*"])])
        self.dotfix("sync")

        rc, out, err = self.dotfix("import")
        self.assertEqual(rc, 0, err)
        # Each symlink should be reported exactly once.
        self.assertEqual(out.count("Managed: nvim"), 1)
        self.assertEqual(out.count("Managed: swaync"), 1)
        self.assertEqual(out.count("Orphan"), 0)

    @unittest.skipUnless(symlinks_supported(),
                     "this platform cannot create symlinks")
    def test_idempotent_sync(self):
        repo = self.sb.make_repo("dots", {"nvim/init.lua": "x", "tmux/tmux.conf": "y"})
        self.sb.configure([("dots", repo, ["*"])])

        self.dotfix("sync")
        first = self.symlink_target("nvim")
        self.dotfix("sync")
        second = self.symlink_target("nvim")

        self.assertEqual(first, second)
        self.assertTrue((self.config / "nvim").is_symlink())

    @unittest.skipUnless(symlinks_supported(),
                     "this platform cannot create symlinks")
    def test_nested_config_dir_is_created(self):
        repo = self.sb.make_repo("dots", {"nvim/init.lua": "x"})
        self.sb.configure([("dots", repo, ["*"])])
        nested = self.config / "deep" / "nested"
        # point target at a nonexistent nested dir
        state_file = self.home / ".local" / "state" / "dotfix" / "state.json"
        state = json.loads(state_file.read_text())
        state["repos"][0]["target"] = str(nested)
        state_file.write_text(json.dumps(state))

        rc, out, err = self.dotfix("sync")
        self.assertEqual(rc, 0, err)
        self.assertTrue((nested / "nvim").is_symlink())

    def test_source_missing_is_an_error(self):
        repo = self.sb.make_repo("dots", {})
        self.sb.configure([("dots", repo, ["*"])])
        # repo has an entry that vanishes between scan and link is hard to
        # simulate; instead verify a repo pointing nowhere errors cleanly
        state_file = self.home / ".local" / "state" / "dotfix" / "state.json"
        state = json.loads(state_file.read_text())
        state["repos"][0]["path"] = str(self.home / "nonexistent")
        state_file.write_text(json.dumps(state))

        rc, out, err = self.dotfix("sync")
        self.assertIn("source not found", out)

    def test_home_env_is_honored(self):
        """Path.home() ignores $HOME on Windows — the tool must not."""
        import importlib
        mod = importlib.import_module("dotfix")
        old = {k: os.environ.get(k) for k in ("HOME", "USERPROFILE")}
        try:
            os.environ["HOME"] = str(self.home)
            os.environ["USERPROFILE"] = str(self.home)
            self.assertEqual(str(mod.user_home()), str(self.home))
            self.assertEqual(str(mod.expand_user("~/dots")), str(self.home / "dots"))
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    @unittest.skipUnless(symlinks_supported(), "no symlink support on this platform")
    def test_create_symlink_marks_directories(self):
        """Directory symlinks must be created with target_is_directory=True."""
        import importlib
        mod = importlib.import_module("dotfix")
        src = self.home / "srcdir"
        src.mkdir()
        (src / "f.txt").write_text("x")
        link = self.home / "linkdir"
        mod.create_symlink(link, src)
        self.assertTrue(link.is_symlink())
        self.assertTrue(link.is_dir())
        # On Windows, os.readlink() returns device paths with a \\?\ prefix
        # (e.g. "\\?\C:\\Users\\..."), which never matches a bare path string
        # against src. Use same_path(), which normalises both sides the way
        # the platform does.
        import importlib
        mod = importlib.import_module("dotfix")
        self.assertTrue(mod.same_path(os.readlink(str(link)), str(src)))

    def test_output_survives_legacy_console_encoding(self):
        """Windows consoles default to cp1252, where box-drawing chars crash."""
        repo = self.sb.make_repo("dots", {"nvim/init.lua": "x"})
        self.sb.configure([("dots", repo, ["*"])])

        # Start from the inherited environment: a child process that lacks
        # SystemRoot cannot load the Windows crypto library, and Python 3.9
        # and 3.10 then die before main() with a fatal random-seed error.
        env = dict(os.environ)
        env.update(self.env)
        env["PYTHONIOENCODING"] = "cp1252"
        proc = subprocess.run(
            [sys.executable, str(DOTFIX), "doctor"],
            capture_output=True, text=True, env=env,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("doctor", proc.stdout)
        self.assertNotIn("UnicodeEncodeError", proc.stderr)

    @unittest.skipUnless(symlinks_supported(), "this platform cannot create symlinks")
    def test_same_path_handles_case_and_symlinked_parents(self):
        """same_path must collapse symlinked parents and ignore case on Windows."""
        import importlib
        mod = importlib.import_module("dotfix")
        real = self.home / "real"
        real.mkdir()
        alias = self.home / "alias"
        alias.symlink_to(real)
        self.assertTrue(mod.same_path(alias / "x", real / "x"))

    def test_extended_length_prefix_is_stripped(self):
        """Windows readlink() returns a \\\\?\\ device path; it must normalise."""
        import importlib
        mod = importlib.import_module("dotfix")
        self.assertEqual(
            mod.strip_extended_prefix(r"\\?\C:\Users\me"), r"C:\Users\me"
        )
        self.assertEqual(
            mod.strip_extended_prefix(r"\\?\UNC\srv\share"), r"\\srv\share"
        )
        # A path without the prefix is left alone.
        self.assertEqual(
            mod.strip_extended_prefix(r"C:\Users\me"), r"C:\Users\me"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
