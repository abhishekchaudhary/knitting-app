"""Content-addressed swatch cache: key = sha256(canonical JSON of the normalised inputs + generation settings).

Stored as cache/<key>.png + cache/<key>.json on disk. The same key scheme works
unchanged as an S3 object key behind a CDN.

Example: key = cache_key(inputs, {"model": "gpt-image-1-mini", "quality": "low"})  # 64 hex chars
         SwatchCache().get(key) -> (image, metadata) on a HIT, None on a MISS.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image

from swatch.config import CONFIG
from swatch.prompt_builder import SwatchInputs, build_prompt

logger = logging.getLogger("swatch")

# --- Where the cache lives (SWATCH_CACHE_DIR overrides; relative paths are from the repo root) ---
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DIR = REPO_ROOT / "assignment-b" / "cache"

# Metadata fields the pipeline reads on a HIT; an entry missing any of them is treated as a MISS.
_REQUIRED_META_FIELDS = {"delta_e", "delta_e_raw", "tinted", "provider", "generation_ms"}


def cache_key(inputs: SwatchInputs, settings: dict[str, Any]) -> str:
    """ASSUMPTION: colour_name is a label only (hex is the source of truth), so it is not part
    of the key. Model, quality, image size and the prompt text are: each changes the image, and
    hashing the prompt means editing config.yaml wording never serves a stale image."""
    prompt_sha = hashlib.sha256(build_prompt(inputs).encode()).hexdigest()[:16]
    key_inputs = inputs.model_dump(exclude={"colour_name"})
    payload = key_inputs | settings | {"size": CONFIG.image.size, "prompt": prompt_sha}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


class SwatchCache:
    """A folder of <key>.png + <key>.json pairs. Corrupt entries read as a MISS; writes are atomic per file."""

    def __init__(self, root: Path | str | None = None) -> None:
        root = root or os.environ.get("SWATCH_CACHE_DIR") or DEFAULT_DIR
        root = Path(root)
        self.root = root if root.is_absolute() else REPO_ROOT / root
        self.root.mkdir(parents=True, exist_ok=True)

    def get(self, key: str) -> tuple[Image.Image, dict[str, Any]] | None:
        """HIT only if both files exist and the JSON is a dict with every field the pipeline reads.

        Anything else (unreadable PNG, bad JSON, JSON that is not an object, missing fields) is
        logged and treated as a MISS, so a corrupt entry costs one regeneration, never a crash.
        """
        png_path = self.root / f"{key}.png"
        meta_path = self.root / f"{key}.json"
        if not (png_path.exists() and meta_path.exists()):
            return None
        try:
            with Image.open(png_path) as opened:
                image = opened.convert("RGB")
            metadata = json.loads(meta_path.read_text(encoding="utf-8"))
            if not isinstance(metadata, dict):
                raise ValueError(f"metadata is {type(metadata).__name__}, not an object")
            if not _REQUIRED_META_FIELDS <= metadata.keys():
                raise ValueError("missing fields")
        except Exception as exc:  # unreadable image, bad JSON, odd payload: regenerate rather than crash
            logger.warning("SWATCH cache=CORRUPT key=%s… reason=%r (treated as MISS)", key[:16], str(exc)[:80])
            return None
        return image, metadata

    def put(self, key: str, image: Image.Image, meta: dict[str, Any]) -> None:
        """Each file is written to a temp file then renamed, so no reader ever sees half a file.

        The png and the json are two separate renames, not one transaction: a concurrent reader can
        briefly see the png without its json. `get` requires both, so that window reads as a MISS.
        The json is written second for exactly that reason.
        """
        stored = image.copy()
        stored.thumbnail((CONFIG.image.store_px, CONFIG.image.store_px))
        self._atomic_write(f"{key}.png", lambda file: stored.save(file, format="PNG", optimize=True))
        body = json.dumps(meta, indent=2, sort_keys=True).encode()
        self._atomic_write(f"{key}.json", lambda file: file.write(body))

    def delete(self, key: str) -> None:
        """Remove both files for `key` (missing files are fine)."""
        for suffix in (".png", ".json"):
            (self.root / f"{key}{suffix}").unlink(missing_ok=True)

    def _atomic_write(self, name: str, write) -> None:
        """Call `write(file)` on a temp file in the cache folder, then rename it to `name`."""
        file_descriptor, tmp_path = tempfile.mkstemp(dir=self.root, prefix=".tmp-")
        try:
            with os.fdopen(file_descriptor, "wb") as file:
                write(file)
            os.replace(tmp_path, self.root / name)
        except BaseException:
            Path(tmp_path).unlink(missing_ok=True)
            raise
