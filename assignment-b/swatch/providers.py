"""ImageProvider protocol: OpenAIImageProvider, FailingProvider, OfflineProvider, FixtureProvider.

No SDK is imported outside this module. A second image vendor is one more
class; pipeline.py only sees `generate(prompt, inputs) -> (PIL.Image, usage)`.

Example: get_image_provider() -> OpenAIImageProvider with a key, OfflineProvider without one;
         FailingProvider().generate(...) raises ImageProviderError (to demo the fallback on purpose).
"""

from __future__ import annotations

import base64
import hashlib
import io
import logging
import os
import threading
from typing import Any, Protocol

import numpy as np
from PIL import Image

from swatch import fallback
from swatch.config import CONFIG
from swatch.prompt_builder import SwatchInputs


logger = logging.getLogger("swatch")

# Token usage reported by a provider, or None when it doesn't report any.
Usage = dict[str, int] | None

# Seconds before an OpenAI image call gives up, when OPENAI_IMAGE_TIMEOUT_S is not set.
_DEFAULT_OPENAI_TIMEOUT_S = 90
# Standard deviation (in 0-255 RGB units) of the grain FixtureProvider adds to the placeholder.
_FIXTURE_NOISE_STD = 6


class _CallCounter:
    """Thread-safe call counter: warm_cache.py generates through a ThreadPoolExecutor and the
    notebook/video read `provider.calls`, so `+= 1` must not lose increments."""

    def _init_calls(self) -> None:
        """Call from __init__: sets `calls` to 0."""
        self.calls = 0
        self._calls_lock = threading.Lock()

    def _count(self) -> None:
        """Call at the start of generate()."""
        with self._calls_lock:
            self.calls += 1


class ImageProviderError(RuntimeError):
    """Generation failed; the pipeline shows the placeholder instead."""


class ImageProvider(Protocol):
    name: str
    model: str
    calls: int

    def generate(self, prompt: str, inputs: SwatchInputs) -> tuple[Image.Image, Usage]:
        """The image plus token usage (None when the provider doesn't report it)."""
        ...


class OpenAIImageProvider(_CallCounter):
    """OpenAI Images API. Env: OPENAI_API_KEY, OPENAI_IMAGE_MODEL, IMAGE_QUALITY, OPENAI_IMAGE_TIMEOUT_S."""

    name = "openai"

    def __init__(
        self, client: Any | None = None, model: str | None = None, quality: str | None = None
    ) -> None:
        self.model = model or os.environ.get("OPENAI_IMAGE_MODEL") or CONFIG.image.default_model
        self.quality = quality or os.environ.get("IMAGE_QUALITY") or CONFIG.image.quality
        if client is None:
            if not os.environ.get("OPENAI_API_KEY"):
                raise ImageProviderError("OPENAI_API_KEY is not set")
            from openai import OpenAI

            timeout_s = float(os.environ.get("OPENAI_IMAGE_TIMEOUT_S") or _DEFAULT_OPENAI_TIMEOUT_S)
            client = OpenAI(timeout=timeout_s, max_retries=0)
        self._client = client
        self._init_calls()

    def generate(self, prompt: str, inputs: SwatchInputs) -> tuple[Image.Image, Usage]:
        self._count()
        try:
            response = self._client.images.generate(
                model=self.model, prompt=prompt, quality=self.quality, size=CONFIG.image.size, n=1
            )
            image_bytes = base64.b64decode(response.data[0].b64_json)
            image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            usage = getattr(response, "usage", None)
        except Exception as exc:  # SDK + decode boundary: auth, timeout, moderation block, network, bad bytes
            raise ImageProviderError(f"{type(exc).__name__}: {exc}") from exc
        return image, _read_usage(usage)


class FailingProvider(_CallCounter):
    """Always fails, to trigger the fallback on purpose (brief §4.4)."""

    name = "failing"

    def __init__(self, reason: str = "simulated outage (401 invalid API key)") -> None:
        self.model = "none"
        self.reason = reason
        self._init_calls()

    def generate(self, prompt: str, inputs: SwatchInputs) -> tuple[Image.Image, Usage]:
        self._count()
        raise ImageProviderError(self.reason)


class OfflineProvider(_CallCounter):
    """No key: serve what is already in the cache (same model/quality as the real provider,
    so the committed example images are hits); anything uncached fails -> placeholder."""

    name = "offline"

    def __init__(self) -> None:
        self.model = os.environ.get("OPENAI_IMAGE_MODEL") or CONFIG.image.default_model
        self.quality = os.environ.get("IMAGE_QUALITY") or CONFIG.image.quality
        self._init_calls()

    def generate(self, prompt: str, inputs: SwatchInputs) -> tuple[Image.Image, Usage]:
        self._count()
        raise ImageProviderError("offline: no OPENAI_API_KEY and this swatch is not in the cache")


class FixtureProvider(_CallCounter):
    """Offline stand-in: a noisy procedural swatch, deterministic per input. No key, no network."""

    name = "fixture"

    def __init__(self) -> None:
        self.model = "fixture"
        self._init_calls()

    def generate(self, prompt: str, inputs: SwatchInputs) -> tuple[Image.Image, Usage]:
        self._count()
        base = np.asarray(fallback.placeholder(inputs.stitch_type, inputs.colour_hex), dtype=float)
        # Seeded from the prompt, so the same inputs always give the same image.
        seed = int.from_bytes(hashlib.sha256(prompt.encode()).digest()[:8], "little")
        grain = np.random.default_rng(seed).normal(0, _FIXTURE_NOISE_STD, base.shape[:2])
        noise = grain[..., None]  # same grain on R, G and B: lightness noise, not colour noise
        return Image.fromarray(np.clip(base + noise, 0, 255).astype(np.uint8), "RGB"), None


def get_image_provider() -> ImageProvider:
    """SIMULATE_IMAGE_FAILURE=1 -> failing; IMAGE_PROVIDER=failing|fixture|offline|openai (default);
    openai without a key -> offline (cached images, placeholder otherwise). The choice is logged."""
    choice = os.environ.get("IMAGE_PROVIDER") or "openai"
    if os.environ.get("SIMULATE_IMAGE_FAILURE") == "1":
        choice = "failing"
    provider: ImageProvider
    if choice == "failing":
        provider = FailingProvider()
    elif choice == "fixture":
        provider = FixtureProvider()
    elif choice == "offline":
        provider = OfflineProvider()
    else:
        try:
            provider = OpenAIImageProvider()
        except ImageProviderError as exc:
            logger.warning("SWATCH provider=offline reason=%r", str(exc))
            return OfflineProvider()
    logger.info("SWATCH provider=%s model=%s", provider.name, provider.model)
    return provider


def _read_usage(usage: Any) -> Usage:
    """Token counts from the SDK's usage object, or None.

    Read defensively: the image is already generated and paid for, so an SDK shape change
    must cost the token numbers, never the image.
    """
    if usage is None:
        return None
    tokens = {
        "input_tokens": getattr(usage, "input_tokens", None),
        "output_tokens": getattr(usage, "output_tokens", None),
    }
    if tokens["input_tokens"] is None and tokens["output_tokens"] is None:
        logger.warning("SWATCH usage=unreadable type=%s", type(usage).__name__)
        return None
    return tokens
