"""Cache key normalisation, HIT skips the provider, failures fall back, fast tint path."""

from __future__ import annotations

import logging

import numpy as np
import pytest
from PIL import Image

from swatch.cache import SwatchCache, cache_key
from swatch.config import CONFIG
from swatch.pipeline import get_swatch, get_swatch_fast
from swatch.prompt_builder import SwatchInputs
from swatch.providers import (
    FailingProvider,
    FixtureProvider,
    OfflineProvider,
    OpenAIImageProvider,
    get_image_provider,
)

BRIEF = {
    "stitch_type": "cable",
    "colour_name": "royal purple",
    "colour_hex": "#5B3E96",
    "weight_category": "worsted",
    "fibre_content": "100% wool",
}
SETTINGS = {"model": "m", "quality": "low"}


@pytest.fixture
def cache(tmp_path):
    return SwatchCache(tmp_path)


def test_key_ignores_case_whitespace_and_order():
    messy = {
        "fibre_content": " 100%  WOOL ",
        "weight_category": "Worsted",
        "colour_hex": "#5b3e96",
        "colour_name": "Royal Purple",
        "stitch_type": "Cable",
    }
    assert cache_key(SwatchInputs(**BRIEF), SETTINGS) == cache_key(SwatchInputs(**messy), SETTINGS)


def test_key_uses_canonical_weight_and_ignores_colour_name():
    renamed = {**BRIEF, "weight_category": "aran", "colour_name": "violet"}
    assert cache_key(SwatchInputs(**BRIEF), SETTINGS) == cache_key(SwatchInputs(**renamed), SETTINGS)


@pytest.mark.parametrize(
    "change", [{"colour_hex": "#5B3E97"}, {"stitch_type": "rib"}, {"weight_category": "chunky"}, {"fibre_content": "cotton"}]
)
def test_key_changes_with_each_input(change):
    assert cache_key(SwatchInputs(**BRIEF), SETTINGS) != cache_key(SwatchInputs(**{**BRIEF, **change}), SETTINGS)


def test_key_changes_with_model():
    assert cache_key(SwatchInputs(**BRIEF), SETTINGS) != cache_key(SwatchInputs(**BRIEF), {**SETTINGS, "model": "x"})


@pytest.mark.demo
def test_second_call_is_cache_hit_and_skips_provider(cache, caplog):
    provider = FixtureProvider()
    with caplog.at_level(logging.INFO, logger="swatch"):
        first = get_swatch(BRIEF, provider=provider, cache=cache)
        second = get_swatch(BRIEF, provider=provider, cache=cache)
    assert (first.source, second.source) == ("generated", "cache")
    assert provider.calls == 1
    assert first.key == second.key
    assert "cache=MISS" in caplog.text and "cache=HIT" in caplog.text


@pytest.mark.demo
def test_failing_provider_returns_placeholder_in_target_colour(cache, caplog):
    with caplog.at_level(logging.WARNING, logger="swatch"):
        result = get_swatch(BRIEF, provider=FailingProvider(), cache=cache)
    assert result.source == "fallback"
    assert result.image.size[0] > 0
    assert result.delta_e < 3
    assert "fallback=placeholder" in caplog.text
    assert not list(cache.root.glob("*.png"))  # failures are not cached


def test_off_colour_generation_is_tinted(cache):
    class GreyProvider(FixtureProvider):
        def generate(self, prompt, inputs):
            self.calls += 1
            return Image.fromarray(np.full((64, 64, 3), 150, dtype=np.uint8), "RGB"), None

    result = get_swatch(BRIEF, provider=GreyProvider(), cache=cache)
    assert result.tinted
    assert result.delta_e_raw > 12 > result.delta_e


def test_fast_path_generates_master_once_then_tints(cache):
    provider = FixtureProvider()
    results = [get_swatch_fast({**BRIEF, "colour_hex": h}, provider=provider, cache=cache) for h in ("#5B3E96", "#2E6B3F", "#D4A017")]
    assert provider.calls == 1
    assert all(r.source == "tint" for r in results)
    assert all(r.delta_e < 5 for r in results)


def test_simulate_failure_env_forces_failing_provider(monkeypatch):
    monkeypatch.setenv("SIMULATE_IMAGE_FAILURE", "1")
    assert isinstance(get_image_provider(), FailingProvider)


def test_no_key_means_offline_provider(monkeypatch, caplog):
    monkeypatch.delenv("SIMULATE_IMAGE_FAILURE", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("IMAGE_PROVIDER", "openai")
    with caplog.at_level(logging.INFO, logger="swatch"):
        provider = get_image_provider()
    assert isinstance(provider, OfflineProvider)
    assert "provider=offline" in caplog.text


def test_offline_provider_serves_cache_and_falls_back_otherwise(cache):
    real = FixtureProvider()
    real.model, real.quality = OfflineProvider().model, OfflineProvider().quality  # same key space
    get_swatch(BRIEF, provider=real, cache=cache)
    offline = OfflineProvider()
    assert get_swatch(BRIEF, provider=offline, cache=cache).source == "cache"
    assert get_swatch({**BRIEF, "stitch_type": "lace"}, provider=offline, cache=cache).source == "fallback"


def test_key_changes_when_prompt_wording_changes(monkeypatch):
    before = cache_key(SwatchInputs(**BRIEF), SETTINGS)
    monkeypatch.setattr(CONFIG.stitch("cable"), "structure", "chunky aran cables")
    assert cache_key(SwatchInputs(**BRIEF), SETTINGS) != before


@pytest.mark.parametrize("corrupt", ["{not json", "{}"])
def test_corrupt_cache_entry_is_a_miss(cache, corrupt, caplog):
    provider = FixtureProvider()
    first = get_swatch(BRIEF, provider=provider, cache=cache)
    (cache.root / f"{first.key}.json").write_text(corrupt)
    with caplog.at_level(logging.WARNING, logger="swatch"):
        again = get_swatch(BRIEF, provider=provider, cache=cache)
    assert again.source == "generated" and provider.calls == 2
    assert "cache=CORRUPT" in caplog.text


def test_undecodable_image_bytes_fall_back(cache):
    import base64
    from types import SimpleNamespace

    class Client:
        images = SimpleNamespace(generate=lambda **kw: SimpleNamespace(
            data=[SimpleNamespace(b64_json=base64.b64encode(b"not a png").decode())], usage=None))

    result = get_swatch(BRIEF, provider=OpenAIImageProvider(client=Client()), cache=cache)
    assert result.source == "fallback"
    assert "UnidentifiedImageError" in result.error


def test_unexpected_provider_exception_falls_back(cache):
    class Broken(FixtureProvider):
        def generate(self, prompt, inputs):
            raise KeyError("surprise")

    assert get_swatch(BRIEF, provider=Broken(), cache=cache).source == "fallback"


def test_fast_path_master_failure_calls_provider_once(cache):
    provider = FailingProvider()
    result = get_swatch_fast(BRIEF, provider=provider, cache=cache)
    assert result.source == "fallback"
    assert provider.calls == 1


def test_non_dict_cache_metadata_is_a_miss(cache, caplog):
    """A .json that parses to a list used to escape as AttributeError instead of a MISS."""
    provider = FixtureProvider()
    first = get_swatch(BRIEF, provider=provider, cache=cache)
    (cache.root / f"{first.key}.json").write_text("[1, 2, 3]")
    with caplog.at_level(logging.WARNING, logger="swatch"):
        again = get_swatch(BRIEF, provider=provider, cache=cache)
    assert again.source == "generated" and provider.calls == 2
    assert "cache=CORRUPT" in caplog.text


def test_placeholder_failure_still_returns_an_image(cache, monkeypatch, caplog):
    """The failure path itself must not fail: a broken placeholder still shows the target colour."""
    import swatch.pipeline as pipeline

    def boom(*a, **kw):
        raise KeyError("typo")

    monkeypatch.setattr(pipeline.fallback, "placeholder", boom)
    with caplog.at_level(logging.WARNING, logger="swatch"):
        result = get_swatch(BRIEF, provider=FailingProvider(), cache=cache)
    assert result.source == "fallback"
    assert result.image.size[0] > 0
    assert result.delta_e < 3
    assert "placeholder=flat" in caplog.text


def test_fast_path_master_is_built_through_validation(cache, monkeypatch):
    """model_copy(update=...) skipped validation; a lowercase master hex must still normalise."""
    monkeypatch.setattr(CONFIG.colour, "master_hex", "#9a9a9a")
    provider = FixtureProvider()
    result = get_swatch_fast(BRIEF, provider=provider, cache=cache)
    hit = cache.get(result.key)
    assert hit is not None
    assert hit[1]["inputs"]["colour_hex"] == "#9A9A9A"


def test_fast_path_flags_a_tint_that_misses_the_colour(cache, monkeypatch, caplog):
    import swatch.pipeline as pipeline

    monkeypatch.setattr(pipeline.colour, "measure_delta_e", lambda image, hex_code: 30.0)
    with caplog.at_level(logging.WARNING, logger="swatch"):
        result = get_swatch_fast(BRIEF, provider=FixtureProvider(), cache=cache)
    assert result.source == "tint"
    assert result.error and "exceeds threshold" in result.error
    assert "tint=OFF_TARGET" in caplog.text


def test_usage_object_without_token_attributes_keeps_the_image(cache, caplog):
    """The image is already paid for: an unreadable usage object must cost the tokens, not the image."""
    import base64
    import io as _io
    from types import SimpleNamespace

    buf = _io.BytesIO()
    Image.fromarray(np.full((32, 32, 3), 120, dtype=np.uint8), "RGB").save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()

    class Client:
        images = SimpleNamespace(generate=lambda **kw: SimpleNamespace(
            data=[SimpleNamespace(b64_json=b64)], usage=object()))

    with caplog.at_level(logging.WARNING, logger="swatch"):
        result = get_swatch(BRIEF, provider=OpenAIImageProvider(client=Client()), cache=cache)
    assert result.source == "generated"
    assert "usage=unreadable" in caplog.text


def test_provider_call_counter_is_thread_safe():
    """warm_cache.py generates through a thread pool; the demo reads provider.calls afterwards."""
    from concurrent.futures import ThreadPoolExecutor

    provider = FailingProvider()
    inputs = SwatchInputs(**BRIEF)

    def call(_):
        with pytest.raises(Exception):
            provider.generate("p", inputs)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(call, range(500)))
    assert provider.calls == 500


@pytest.mark.demo
def test_committed_cache_entries_still_resolve_to_their_keys():
    """The keyless demo depends on every committed entry being a HIT: filename == derived key.

    Guards the cache key and the input normalisation against an accidental change.
    """
    import json

    from swatch.cache import DEFAULT_DIR

    entries = sorted(DEFAULT_DIR.glob("*.json"))
    assert len(entries) >= 7
    for meta_path in entries:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        key = cache_key(SwatchInputs(**meta["inputs"]), {"model": meta["model"], "quality": meta["quality"]})
        assert key == meta_path.stem, f"{meta_path.name} no longer matches its inputs"
        assert (DEFAULT_DIR / f"{key}.png").exists()


@pytest.mark.demo
def test_offline_provider_serves_every_committed_entry(monkeypatch):
    """What the notebook does keyless: OfflineProvider + the committed cache = HIT, never a placeholder."""
    import json

    from swatch.cache import DEFAULT_DIR

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    for meta_path in sorted(DEFAULT_DIR.glob("*.json")):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        monkeypatch.setenv("OPENAI_IMAGE_MODEL", meta["model"])
        monkeypatch.setenv("IMAGE_QUALITY", meta["quality"])
        result = get_swatch(meta["inputs"], provider=OfflineProvider(), cache=SwatchCache(DEFAULT_DIR))
        assert result.source == "cache", f"{meta_path.name} is no longer a hit"
        assert result.key == meta_path.stem


@pytest.mark.demo
def test_fast_path_master_is_the_committed_master(monkeypatch):
    """get_swatch_fast must land on the committed grey master key (structure-once demo, keyless)."""
    from swatch.cache import DEFAULT_DIR

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_IMAGE_MODEL", "gpt-image-1-mini")
    monkeypatch.setenv("IMAGE_QUALITY", "low")
    result = get_swatch_fast(BRIEF, provider=OfflineProvider(), cache=SwatchCache(DEFAULT_DIR))
    assert result.source == "tint"
    assert result.key == "735bd8066d1c03c64e9fcfbaf32d8459c0ed18c450e4d120cc995b03353e1b52"
