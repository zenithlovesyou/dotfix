#!/usr/bin/env python3
"""Run the test suite and publish the results in ways CI can expose.

Two channels are used, because the raw log of a job is only readable by
admins of the repository:

* a job summary, which shows up on the run page;
* one GitHub annotation per failure, which the public REST API returns even
  for a public repository with no access token.

The full output is also written to `ci-tests.log` and uploaded as an
artifact, so nothing is lost.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "ci-tests.log"

FAILURE_RE = re.compile(
    r"^(?:FAIL|ERROR): (?P<name>.+?)(?:\s+\((?P<loc>[^)]*)\))?$", re.M
)


def publish_annotations(output: str):
    """Emit one `::error::` annotation per failing test."""
    # unittest prints the failing test as a header, then a separator, then the
    # traceback. Take everything from a header up to the next header as that
    # test's block, so the traceback travels with its test.
    matches = list(FAILURE_RE.finditer(output))
    for index, m in enumerate(matches):
        start = m.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(output)
        name = m.group("name")
        loc = m.group("loc") or name
        body = output[start:end].strip()
        # The traceback comes after a separator line; take what follows it.
        parts = re.split(r"^-{70}$", body, maxsplit=1, flags=re.M)
        body = parts[1].strip() if len(parts) > 1 else body
        # Drop the trailing "Ran N tests" / "FAILED" boilerplate.
        body = re.split(r"^-{70}$", body, maxsplit=1, flags=re.M)[0].strip()
        if len(body) > 6000:
            body = body[:6000] + "\n... (truncated)"
        message = f"{name}\n{body}".strip()
        # Annotation lines are single-line: escape newlines.
        message = message.replace("\r", "").replace("\n", "%0A")
        print(f"::error title={name}::{message}")
        if loc and loc != name:
            print(f"::error title={name} (location)::{loc}")


def publish_summary(output: str):
    """Append the whole log to the job summary."""
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    try:
        with open(summary_path, "a", encoding="utf-8") as fh:
            fh.write("### Test output\n\n```\n")
            fh.write(output)
            fh.write("\n```\n")
    except OSError:
        pass


def main() -> int:
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        errors="replace",
    )
    output = (proc.stdout or "") + (proc.stderr or "")
    try:
        LOG.write_text(output, encoding="utf-8")
    except OSError:
        pass

    publish_summary(output)
    publish_annotations(output)

    # Echo the tail so the step log shows the summary even without the
    # summary panel.
    tail = output.strip().splitlines()[-12:]
    for line in tail:
        print(line)

    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
