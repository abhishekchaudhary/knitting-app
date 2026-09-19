"""warm_cache.py CLI: bad arguments must not escape as tracebacks, and cost must never read as free."""

from __future__ import annotations

import logging

import pytest

import warm_cache


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    monkeypatch.setattr(warm_cache, "load_dotenv", lambda *a, **k: None)  # never read the real .env in tests
    monkeypatch.setenv("IMAGE_PROVIDER", "fixture")
    monkeypatch.setenv("SWATCH_CACHE_DIR", str(tmp_path))
    monkeypatch.delenv("SIMULATE_IMAGE_FAILURE", raising=False)


def run(monkeypatch, *argv: str) -> int:
    monkeypatch.setattr("sys.argv", ["warm_cache.py", *argv])
    return warm_cache.main()


def test_unpriced_model_reports_unknown_not_free(monkeypatch, caplog):
    """IMAGE_PROVIDER=fixture has no published price: the grid must not be advertised as $0.00."""
    with caplog.at_level(logging.INFO, logger="swatch"):
        assert run(monkeypatch, "--dry-run", "--stitches", "cable", "--presets", "2") == 0
    assert "est. cost=unknown (no price for model fixture)" in caplog.text
    assert "$0.00" not in caplog.text
    assert "grid=2" in caplog.text


@pytest.mark.parametrize("argv", [
    ["--stitches", "moss-diamond-brioche"],
    ["--weight", "extra-heavy"],
    ["--fibre", "100% wool"],  # valid: kept as the control in the ids below
])
def test_bad_domain_arguments_exit_as_usage_errors(monkeypatch, argv):
    if argv[0] == "--fibre":
        assert run(monkeypatch, "--dry-run", *argv) == 0
        return
    with pytest.raises(SystemExit) as exc:
        run(monkeypatch, "--dry-run", *argv)
    assert exc.value.code == 2  # argparse usage error, not a pydantic traceback


@pytest.mark.parametrize("argv", [["--presets", "0"], ["--presets", "-3"], ["--workers", "0"]])
def test_non_positive_counts_are_rejected(monkeypatch, argv):
    with pytest.raises(SystemExit) as exc:
        run(monkeypatch, "--dry-run", *argv)
    assert exc.value.code == 2


def test_keyless_non_dry_run_points_at_dry_run(monkeypatch, caplog):
    with caplog.at_level(logging.WARNING, logger="swatch"):
        code = run(monkeypatch, "--stitches", "cable", "--presets", "1")
    assert code == 1
    assert "--dry-run" in caplog.text
