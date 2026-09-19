"""Colour maths for swatches: convert colours, measure how close an image is, recolour it.

Converts hex -> sRGB -> CIELAB (D65 white), measures colour difference with
CIEDE2000, and tints an image. The tint is the fast colour path: generate a
neutral-grey structure master once, then move its LAB colour onto the target in
milliseconds while keeping the texture (the relative lightness detail) intact.

Example: describe("#5B3E96") -> "medium muted purple"; hex_to_rgb("#5B3E96") -> (91, 62, 150).
Pure numpy, no I/O.
"""

from __future__ import annotations

import colorsys

import numpy as np
from PIL import Image

from swatch import config  # module import: config.py has no colour dependency at import time

# --- sRGB <-> CIELAB constants (IEC 61966-2-1 sRGB, CIE 1976 L*a*b*) ---
# Reference white D65, as XYZ.
_D65_WHITE = np.array([0.95047, 1.0, 1.08883])
# Linear sRGB -> XYZ matrix, and its inverse for the way back.
_RGB_TO_XYZ = np.array(
    [[0.4124564, 0.3575761, 0.1804375], [0.2126729, 0.7151522, 0.0721750], [0.0193339, 0.1191920, 0.9503041]]
)
_XYZ_TO_RGB = np.linalg.inv(_RGB_TO_XYZ)
# CIE constants: below EPSILON the LAB curve switches from a cube root to a straight line.
_EPSILON = 216 / 24389
_KAPPA = 24389 / 27

# --- Colour words for the prompt ---
# (upper hue limit in degrees, name): the first limit the hue is at or below wins.
_HUE_NAMES = [
    (15, "red"), (40, "orange"), (65, "yellow"), (80, "yellow-green"), (160, "green"),
    (190, "teal"), (250, "blue"), (285, "purple"), (330, "magenta"), (360, "red"),
]


# --- Hex and RGB ---


def hex_to_rgb(hex_code: str) -> tuple[int, int, int]:
    """'#5B3E96' (or '5b3e96') -> (91, 62, 150). Raises ValueError if it is not six hex digits."""
    digits = hex_code.strip().lstrip("#")
    if len(digits) != 6:
        raise ValueError(f"colour hex must be #RRGGBB, got {hex_code!r}")
    red = int(digits[0:2], 16)
    green = int(digits[2:4], 16)
    blue = int(digits[4:6], 16)
    return red, green, blue


def rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    """(91, 62, 150) -> '#5B3E96' (always upper case, so equal colours compare equal)."""
    return "#{:02X}{:02X}{:02X}".format(*rgb)


# --- sRGB <-> CIELAB ---


def rgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    """sRGB (0-255, shape [..., 3]) -> CIELAB (D65), same leading shape."""
    srgb = np.asarray(rgb, dtype=float) / 255.0
    # Undo the sRGB gamma curve to get linear light.
    linear_rgb = np.where(srgb <= 0.04045, srgb / 12.92, ((srgb + 0.055) / 1.055) ** 2.4)
    xyz = linear_rgb @ _RGB_TO_XYZ.T / _D65_WHITE
    # CIE f(t): cube root above EPSILON, straight line below.
    f_xyz = np.where(xyz > _EPSILON, np.cbrt(xyz), (_KAPPA * xyz + 16) / 116)
    f_of_x = f_xyz[..., 0]
    f_of_y = f_xyz[..., 1]
    f_of_z = f_xyz[..., 2]
    lightness = 116 * f_of_y - 16
    green_red = 500 * (f_of_x - f_of_y)
    blue_yellow = 200 * (f_of_y - f_of_z)
    return np.stack([lightness, green_red, blue_yellow], axis=-1)


def lab_to_rgb(lab: np.ndarray) -> np.ndarray:
    """CIELAB (D65) -> sRGB (0-255 floats, clipped). Inverse of rgb_to_lab."""
    lab = np.asarray(lab, dtype=float)
    lightness = lab[..., 0]
    # Inverse CIE f: rebuild f(X), f(Y), f(Z) from L, a, b.
    f_of_y = (lightness + 16) / 116
    f_of_x = f_of_y + lab[..., 1] / 500
    f_of_z = f_of_y - lab[..., 2] / 200
    f_xyz = np.stack([f_of_x, f_of_y, f_of_z], axis=-1)
    xyz = np.where(f_xyz**3 > _EPSILON, f_xyz**3, (116 * f_xyz - 16) / _KAPPA)
    # Y is recovered from L directly (more exact near black).
    xyz[..., 1] = np.where(lightness > _KAPPA * _EPSILON, f_of_y**3, lightness / _KAPPA)
    linear_rgb = np.clip((xyz * _D65_WHITE) @ _XYZ_TO_RGB.T, 0, 1)
    # Re-apply the sRGB gamma curve.
    srgb = np.where(linear_rgb <= 0.0031308, 12.92 * linear_rgb, 1.055 * linear_rgb ** (1 / 2.4) - 0.055)
    return np.clip(srgb * 255, 0, 255)


def hex_to_lab(hex_code: str) -> np.ndarray:
    """'#5B3E96' -> its CIELAB colour as a length-3 array."""
    return rgb_to_lab(np.array(hex_to_rgb(hex_code)))


# --- Colour difference ---


def delta_e2000(lab1: np.ndarray, lab2: np.ndarray) -> float:
    """CIEDE2000 colour difference between two LAB colours (Sharma, Wu & Dalal 2005).

    Roughly: under 1 is invisible, 2-3 is a close match, over 10 is clearly a different colour.
    Symbols follow the paper; the equation number is in each comment.
    """
    L1 = float(lab1[0])
    a1 = float(lab1[1])
    b1 = float(lab1[2])
    L2 = float(lab2[0])
    a2 = float(lab2[1])
    b2 = float(lab2[2])

    # Step 1: adjusted a', chroma C' and hue h' for each colour.
    c_bar = (np.hypot(a1, b1) + np.hypot(a2, b2)) / 2  # eq. 2-3: mean chroma C*ab
    G = 0.5 * (1 - np.sqrt(c_bar**7 / (c_bar**7 + 25**7)))  # eq. 4
    a1p = a1 * (1 + G)  # eq. 5
    a2p = a2 * (1 + G)
    c1p = np.hypot(a1p, b1)  # eq. 6
    c2p = np.hypot(a2p, b2)
    h1p = np.degrees(np.arctan2(b1, a1p)) % 360  # eq. 7
    h2p = np.degrees(np.arctan2(b2, a2p)) % 360

    # Step 2: differences in lightness, chroma and hue.
    dLp = L2 - L1  # eq. 8
    dCp = c2p - c1p  # eq. 9
    dhp = _hue_angle_difference(h1p, h2p, c1p, c2p)  # eq. 10
    dHp = 2 * np.sqrt(c1p * c2p) * np.sin(np.radians(dhp / 2))  # eq. 11

    # Step 3: means, weighting functions and the rotation term.
    Lp_bar = (L1 + L2) / 2  # eq. 12
    Cp_bar = (c1p + c2p) / 2  # eq. 13
    hp_bar = _mean_hue(h1p, h2p, c1p, c2p)  # eq. 14
    T = (  # eq. 15
        1
        - 0.17 * np.cos(np.radians(hp_bar - 30))
        + 0.24 * np.cos(np.radians(2 * hp_bar))
        + 0.32 * np.cos(np.radians(3 * hp_bar + 6))
        - 0.20 * np.cos(np.radians(4 * hp_bar - 63))
    )
    d_theta = 30 * np.exp(-(((hp_bar - 275) / 25) ** 2))  # eq. 16
    R_C = 2 * np.sqrt(Cp_bar**7 / (Cp_bar**7 + 25**7))  # eq. 17
    S_L = 1 + 0.015 * (Lp_bar - 50) ** 2 / np.sqrt(20 + (Lp_bar - 50) ** 2)  # eq. 18
    S_C = 1 + 0.045 * Cp_bar  # eq. 19
    S_H = 1 + 0.015 * Cp_bar * T  # eq. 20
    R_T = -np.sin(np.radians(2 * d_theta)) * R_C  # eq. 21

    # Step 4: combine (eq. 22, with kL = kC = kH = 1).
    return float(
        np.sqrt((dLp / S_L) ** 2 + (dCp / S_C) ** 2 + (dHp / S_H) ** 2 + R_T * (dCp / S_C) * (dHp / S_H))
    )


# --- Measuring an image ---


def measured_lab(image: Image.Image) -> np.ndarray:
    """Median LAB of the centre `colour.measure_crop` crop (ignores vignettes and edge shadows)."""
    return np.median(_centre_lab(image).reshape(-1, 3), axis=0)


def measure_delta_e(image: Image.Image, target_hex: str) -> float:
    """How far the image's measured colour is from `target_hex`, in CIEDE2000 units."""
    return delta_e2000(measured_lab(image), hex_to_lab(target_hex))


# --- Recolouring ---


def tint(image: Image.Image, target_hex: str) -> Image.Image:
    """Recolour keeping texture: shift the image's LAB so its median lands on the target.

    L' = L - median(L) + L_target (texture detail kept, overall lightness moved)
    a' = a - median(a) + a_target, b' likewise.
    Limit: very dark or very saturated targets can clip, which flattens some shading.
    """
    lab = rgb_to_lab(np.asarray(image.convert("RGB"), dtype=float))
    median = np.median(lab.reshape(-1, 3), axis=0)
    shifted = lab - median + hex_to_lab(target_hex)
    shifted[..., 0] = np.clip(shifted[..., 0], 0, 100)
    return Image.fromarray(lab_to_rgb(shifted).round().astype(np.uint8), "RGB")


# --- Words for a colour ---


def describe(hex_code: str) -> str:
    """Plain words for a hex, e.g. #5B3E96 -> 'medium muted purple'. Image models follow words better than hex."""
    red, green, blue = hex_to_rgb(hex_code)
    hue_fraction, lightness, saturation = colorsys.rgb_to_hls(red / 255, green / 255, blue / 255)

    if saturation < 0.12 or lightness < 0.06 or lightness > 0.96:
        return _describe_neutral(lightness)

    hue_degrees = hue_fraction * 360
    hue_name = _hue_name(hue_degrees)
    if 20 <= hue_degrees <= 50 and lightness < 0.45:
        hue_name = "brown"  # dark orange reads as brown to people and to image models

    if lightness < 0.35:
        tone = "dark"
    elif lightness > 0.7:
        tone = "light"
    else:
        tone = "medium"

    if saturation < 0.45:
        saturation_word = "muted"
    elif saturation > 0.75:
        saturation_word = "vivid"
    else:
        saturation_word = "rich"
    return f"{tone} {saturation_word} {hue_name}"


# --- Private helpers, in the order they are used above ---


def _hue_angle_difference(h1p: float, h2p: float, c1p: float, c2p: float) -> float:
    """Δh' (Sharma et al. 2005, eq. 10): the signed hue difference, taking the short way round the circle."""
    if c1p * c2p == 0:
        return 0.0
    if abs(h2p - h1p) <= 180:
        return h2p - h1p
    if h2p > h1p:
        return h2p - h1p - 360
    return h2p - h1p + 360


def _mean_hue(h1p: float, h2p: float, c1p: float, c2p: float) -> float:
    """h̄' (Sharma et al. 2005, eq. 14): the mean hue, taking the short way round the circle."""
    if c1p * c2p == 0:
        return h1p + h2p
    if abs(h1p - h2p) <= 180:
        return (h1p + h2p) / 2
    if h1p + h2p < 360:
        return (h1p + h2p + 360) / 2
    return (h1p + h2p - 360) / 2


def _centre_lab(image: Image.Image, crop: float | None = None) -> np.ndarray:
    """LAB pixels of the centre `crop` fraction of the image (default from config)."""
    crop = config.CONFIG.colour.measure_crop if crop is None else crop
    pixels = np.asarray(image.convert("RGB"), dtype=float)
    height, width = pixels.shape[:2]
    margin_y = int(height * (1 - crop) / 2)
    margin_x = int(width * (1 - crop) / 2)
    return rgb_to_lab(pixels[margin_y : height - margin_y, margin_x : width - margin_x])


def _describe_neutral(lightness: float) -> str:
    """Words for a colour with almost no hue: near-black, or a light/medium neutral grey."""
    if lightness < 0.2:
        return "near-black"
    if lightness > 0.75:
        return "light neutral grey"
    return "medium neutral grey"


def _hue_name(hue_degrees: float) -> str:
    """The first entry in _HUE_NAMES whose upper limit the hue is at or below."""
    for upper_limit, name in _HUE_NAMES:
        if hue_degrees <= upper_limit:
            return name
    raise StopIteration  # unreachable: the last limit is 360
