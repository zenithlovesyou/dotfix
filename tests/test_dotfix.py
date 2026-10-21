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


def run(args, env=None, cwd=None):
    """Invoke dotfix as a subprocess and return (returncode, stdout, stderr)."""
    e = dict(os.environ)
    e["XDG_CONFIG_HOME"] = str(cwd) if cwd else e.get("XDG_CONFIG_HOME", "")
    if env:
        e.update(env)
    proc = subprocess.run(
        [sys.executable, str(DOTFIX), *args],
        capture_output=True, text=True, env=e, cwd=cwd,
    )
    return proc.returncode, proc.stdout, proc.stderr


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
        self.tmp = Path(tempfile.mkdtemp(prefix="dotfix-test-"))
        self.home = self.tmp / "home"
        self.config = self.home / ".config"
        self.home.mkdir(parents=True)
        self.config.mkdir(parents=True)
        self.sb = Sandbox(self.home, self.config)
        self.env = {"HOME": str(self.home)}

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

    def test_sync_creates_symlinks(self):
        repo = self.sb.make_repo("dots", {"nvim/init.lua": "x", "tmux/tmux.conf": "y"})
        self.sb.configure([("dots", repo, ["*"])])

        rc, out, err = self.dotfix("sync")
        self.assertEqual(rc, 0, err)
        self.assertTrue((self.config / "nvim").is_symlink())
        self.assertTrue((self.config / "tmux").is_symlink())
        self.assertEqual(self.symlink_target("nvim"), str(repo / "nvim"))

    def test_doctor_reports_ok(self):
        repo = self.sb.make_repo("dots", {"nvim/init.lua": "x"})
        self.sb.configure([("dots", repo, ["*"])])
        self.dotfix("sync")

        rc, out, err = self.dotfix("doctor")
        self.assertEqual(rc, 0, err)
        self.assertIn("OK: nvim", out)

    def test_broken_symlink_is_detected_and_repaired(self):
        repo = self.sb.make_repo("dots", {"nvim/init.lua": "x"})
        self.sb.configure([("dots", repo, ["*"])])
        # Point the symlink at a path that does not exist
        (self.config / "nvim").symlink_to(self.home / "gone")

        rc, out, err = self.dotfix("doctor")
        self.assertIn("Broken symlink: nvim", out)

        rc, out, err = self.dotfix("sync")
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.symlink_target("nvim"), str(repo / "nvim"))

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

    def test_force_overwrites_regular_file(self):
        repo = self.sb.make_repo("dots", {"nvim/init.lua": "x"})
        self.sb.configure([("dots", repo, ["*"])])
        (self.config / "nvim").mkdir()

        rc, out, err = self.dotfix("sync", "--force")
        self.assertEqual(rc, 0, err)
        self.assertTrue((self.config / "nvim").is_symlink())

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

    def test_precedence_first_repo_owns_name(self):
        r1 = self.sb.make_repo("first", {"nvim/init.lua": "1"})
        r2 = self.sb.make_repo("second", {"nvim/init.lua": "2"})
        self.sb.configure([("first", r1, ["*"]), ("second", r2, ["*"])])

        rc, out, err = self.dotfix("doctor")
        self.assertIn("Shadowed: nvim (owned by first)", out)

        self.dotfix("sync")
        self.assertEqual(self.symlink_target("nvim"), str(r1 / "nvim"))

    def test_precedence_order_is_respected(self):
        r1 = self.sb.make_repo("first", {"nvim/init.lua": "1"})
        r2 = self.sb.make_repo("second", {"nvim/init.lua": "2"})
        # Reversed order — second should own nvim now
        self.sb.configure([("second", r2, ["*"]), ("first", r1, ["*"])])

        rc, out, err = self.dotfix("doctor")
        self.assertIn("Shadowed: nvim (owned by second)", out)

        self.dotfix("sync")
        self.assertEqual(self.symlink_target("nvim"), str(r2 / "nvim"))

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

    def test_clean_removes_orphan_symlinks(self):
        repo = self.sb.make_repo("dots", {"nvim/init.lua": "x"})
        self.sb.configure([("dots", repo, ["*"])])
        self.dotfix("sync")

        # An orphan pointing somewhere outside any repo
        other = self.home / "other"
        other.mkdir()
        (self.config / "orphan").symlink_to(other)

        rc, out, err = self.dotfix("clean", "--dry-run")
        self.assertIn("Would remove orphan: orphan", out)
        self.assertTrue((self.config / "orphan").is_symlink())

        rc, out, err = self.dotfix("clean")
        self.assertEqual(rc, 0, err)
        self.assertFalse((self.config / "orphan").exists())
        # managed symlink must survive
        self.assertTrue((self.config / "nvim").is_symlink())

    def test_clean_removes_broken_symlinks(self):
        repo = self.sb.make_repo("dots", {"nvim/init.lua": "x"})
        self.sb.configure([("dots", repo, ["*"])])
        (self.config / "dangling").symlink_to(self.home / "nowhere")

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

    def test_idempotent_sync(self):
        repo = self.sb.make_repo("dots", {"nvim/init.lua": "x", "tmux/tmux.conf": "y"})
        self.sb.configure([("dots", repo, ["*"])])

        self.dotfix("sync")
        first = self.symlink_target("nvim")
        self.dotfix("sync")
        second = self.symlink_target("nvim")

        self.assertEqual(first, second)
        self.assertTrue((self.config / "nvim").is_symlink())

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
