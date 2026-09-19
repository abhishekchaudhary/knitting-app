"""cli.py as a shell caller sees it: JSON shape and exit codes, via subprocess.

Runs with --offline so no key, no network and no .env reload can affect the result.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

CLI = Path(__file__).resolve().parents[1] / "cli.py"
REPO_ROOT = CLI.parents[1]

ANSWERED, ASKED, DECLINED = 0, 2, 3


def run(question: str, *flags: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("OPENAI_", "RAVELRY_"))}
    env["PYTHONPATH"] = str(CLI.parent)
    return subprocess.run(
        [sys.executable, str(CLI), question, "--offline", *flags],
        capture_output=True, text=True, cwd=REPO_ROOT, env=env, timeout=60,
    )


def test_json_keys_and_answered_exit_code():
    proc = run("How much DK yarn do I need for a 50 x 60cm blanket in stockinette?", "--json")
    assert proc.returncode == ANSWERED, proc.stderr
    payload = json.loads(proc.stdout)
    assert {"reply", "intent", "calc", "params", "route", "phrase", "guard_rejected"} <= set(payload)
    assert payload["intent"] == "yarn_quantity"
    assert payload["calc"]["result"]["metres"] == 429.0
    assert "draft" not in payload  # the unverified draft is labelled as such
    assert "draft_unverified" in payload


@pytest.mark.parametrize(
    "question,code",
    [
        ("How much DK yarn do I need for a 50 x 60cm blanket in stockinette?", ANSWERED),
        ("Why is my tension off?", ASKED),
        ("Is merino warmer than acrylic?", DECLINED),
    ],
)
def test_exit_codes_distinguish_answered_asked_declined(question, code):
    assert run(question, "--json").returncode == code


def test_question_starting_with_a_dash_needs_the_double_dash_documented_in_help():
    env = {k: v for k, v in os.environ.items() if not k.startswith(("OPENAI_", "RAVELRY_"))}
    env["PYTHONPATH"] = str(CLI.parent)
    proc = subprocess.run(
        [sys.executable, str(CLI), "--offline", "--json", "--",
         "-50 x 60cm blanket in DK: how much yarn?"],
        capture_output=True, text=True, cwd=REPO_ROOT, env=env, timeout=60,
    )
    assert proc.returncode == DECLINED, proc.stderr  # negative width -> declined, not answered
    help_text = subprocess.run(
        [sys.executable, str(CLI), "--help"], capture_output=True, text=True,
        cwd=REPO_ROOT, env=env, timeout=60,
    ).stdout
    assert "--" in help_text and "exit" in help_text.lower()
