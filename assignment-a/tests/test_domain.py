"""domain.yaml loads and validates: sources present, needles sorted, weight
bounds inside the needle table, aliases unique."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from knitcalc.domain import DOMAIN, DOMAIN_YAML_PATH, load_domain


def test_domain_loads_without_error():
    assert DOMAIN.version == 1


def test_every_weight_has_source_and_note():
    for w in DOMAIN.weights:
        assert w.source
        assert w.note


def test_approximation_blocks_have_calibrate():
    for w in DOMAIN.weights:
        if w.approximation:
            assert w.calibrate, f"{w.key} is approximation but has no calibrate note"
    for item in DOMAIN.stitches.items:
        assert DOMAIN.stitches.calibrate  # stitches block-level calibrate


def test_needle_rows_sorted_ascending():
    mms = [r.mm for r in DOMAIN.needles.rows]
    assert mms == sorted(mms)


def test_every_weight_needle_range_inside_table():
    table_min = DOMAIN.needles.rows[0].mm
    table_max = DOMAIN.needles.rows[-1].mm
    for w in DOMAIN.weights:
        lo, hi = w.needle_mm
        assert table_min <= lo <= table_max
        assert table_min <= hi <= table_max


def test_duplicate_weight_alias_rejected(tmp_path):
    import yaml

    with open(DOMAIN_YAML_PATH) as f:
        raw = yaml.safe_load(f)
    # duplicate an alias across two weight entries
    raw["weights"][1]["aliases"].append(raw["weights"][0]["aliases"][0])
    bad_path = tmp_path / "bad_domain.yaml"
    with open(bad_path, "w") as f:
        yaml.safe_dump(raw, f)

    with pytest.raises(ValidationError):
        load_domain(bad_path)


def test_duplicate_stitch_alias_rejected(tmp_path):
    import yaml

    with open(DOMAIN_YAML_PATH) as f:
        raw = yaml.safe_load(f)
    raw["stitches"]["items"][1]["aliases"].append(raw["stitches"]["items"][0]["aliases"][0])
    bad_path = tmp_path / "bad_domain.yaml"
    with open(bad_path, "w") as f:
        yaml.safe_dump(raw, f)

    with pytest.raises(ValidationError):
        load_domain(bad_path)


def test_weight_lookup_by_alias_and_key():
    assert DOMAIN.weight_by_alias("dk").key == "light"
    assert DOMAIN.weight_by_alias("Worsted").key == "medium"
    assert DOMAIN.weight_by_alias("jumbo").key == "jumbo"


def test_weight_lookup_unknown_raises():
    with pytest.raises(ValueError):
        DOMAIN.weight_by_alias("nonexistent-weight")


def test_stitch_lookup_by_alias():
    assert DOMAIN.stitch_by_alias("1x1 rib").key == "rib_1x1"
    assert DOMAIN.stitch_by_alias("moss").key == "seed"


# --- config typos must fail at load -------------------------------------------


def _raw() -> dict:
    import yaml

    with open(DOMAIN_YAML_PATH) as f:
        return yaml.safe_load(f)


def _write(tmp_path, raw) -> "object":
    import yaml

    path = tmp_path / "bad_domain.yaml"
    with open(path, "w") as f:
        yaml.safe_dump(raw, f)
    return path


def test_severity_key_typo_rejected_at_load(tmp_path):
    raw = _raw()
    raw["tension"]["severity"]["minor_bellow"] = raw["tension"]["severity"].pop("minor_below")
    with pytest.raises(ValidationError):
        load_domain(_write(tmp_path, raw))


def test_unknown_key_in_a_sub_model_rejected_at_load(tmp_path):
    raw = _raw()
    raw["tension"]["mm_per_stich"] = 0.25  # typo next to the real mm_per_stitch
    with pytest.raises(ValidationError):
        load_domain(_write(tmp_path, raw))


def test_unknown_default_fabric_rejected_at_load(tmp_path):
    raw = _raw()
    raw["needle_recommender"]["default_fabric"] = "balancd"
    with pytest.raises(ValidationError):
        load_domain(_write(tmp_path, raw))


def test_unknown_default_project_rejected_at_load(tmp_path):
    raw = _raw()
    raw["needle_recommender"]["default_project"] = "scraf"
    with pytest.raises(ValidationError):
        load_domain(_write(tmp_path, raw))


def test_tension_severity_is_typed_not_a_free_dict():
    assert DOMAIN.tension.severity.minor_below < DOMAIN.tension.severity.moderate_below


def test_stitches_per_needle_size_is_a_config_constant():
    """No domain constant is hard-coded in calculators.py."""
    constant = DOMAIN.tension.sts_per_needle_size
    assert constant.value > 0
    assert constant.source and constant.note
