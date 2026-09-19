"""Provider smoke tests. Skipped unless real keys are in the environment:

    set -a; . ./.env; set +a; .venv/bin/python -m pytest -m live
"""

from __future__ import annotations

import os

import pytest

from swatch.cache import SwatchCache
from swatch.pipeline import get_swatch
from swatch.providers import OpenAIImageProvider
from swatch.ravelry import search_reference

pytestmark = pytest.mark.live


@pytest.mark.skipif(not (os.getenv("RAVELRY_USERNAME") and os.getenv("RAVELRY_PASSWORD")), reason="needs Ravelry creds")
def test_live_ravelry_cable_has_photo():
    ref = search_reference("cable")
    assert ref is not None and ref.photo_url.startswith("https://")


@pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="needs OPENAI_API_KEY")
def test_live_image_generation(tmp_path):
    result = get_swatch(
        {"stitch_type": "rib", "colour_hex": "#2E6B3F", "weight_category": "dk"},
        provider=OpenAIImageProvider(quality="low"),
        cache=SwatchCache(tmp_path),
    )
    assert result.source == "generated"
    assert result.delta_e < 12
