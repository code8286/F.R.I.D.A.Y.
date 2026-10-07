# Copyright 2026 Alpha (code8286)
# SPDX-License-Identifier: Apache-2.0

"""Album art as 1-bit ordered-dither line art (brief section 5F), served to QML as image://art/<track id>.

The mock has no real artwork, so each track gets a generated picture (rings, a horizon, a sun), then the same
4x4 Bayer dither the real provider will apply to the Windows media-session thumbnail."""

from __future__ import annotations

import hashlib
import math

from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QImage
from PySide6.QtQuick import QQuickImageProvider

BAYER = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]
SIZE = 96


def dither(gray: list[list[float]], fg: int = 0xFFF5F5F2, bg: int = 0xFF000000) -> QImage:
    h, w = len(gray), len(gray[0])
    img = QImage(w, h, QImage.Format.Format_ARGB32)
    for y in range(h):
        for x in range(w):
            img.setPixel(x, y, fg if gray[y][x] > (BAYER[y % 4][x % 4] + 0.5) / 16 else bg)
    return img


def generated(seed: str) -> list[list[float]]:
    hv = hashlib.sha256(seed.encode()).digest()
    sx, sy = 0.3 + hv[0] / 640, 0.25 + hv[1] / 900
    rings = 3 + hv[2] % 5
    tilt = (hv[3] - 128) / 400
    out = []
    for y in range(SIZE):
        row = []
        for x in range(SIZE):
            u, v = x / SIZE, y / SIZE
            horizon = 0.62 + tilt * (u - 0.5)
            sky = 0.55 * (1 - v)
            d = math.hypot(u - sx - 0.25, v - sy)
            sun = max(0.0, 1 - d * 5.5)
            band = 0.5 + 0.5 * math.sin(d * rings * 18)
            ground = 0.18 + 0.25 * (0.5 + 0.5 * math.sin((u * 9 + v * 30)))
            g = (sky * 0.6 + sun + 0.15 * band * (1 - v)) if v < horizon else ground * (1.2 - v)
            row.append(max(0.0, min(1.0, g)))
        out.append(row)
    return out


class ArtProvider(QQuickImageProvider):
    def __init__(self) -> None:
        super().__init__(QQuickImageProvider.ImageType.Image)
        self._cache: dict[str, QImage] = {}

    def requestImage(self, image_id: str, size: QSize, requested: QSize) -> QImage:  # noqa: N802
        key = image_id.split("?")[0] or "none"
        img = self._cache.get(key)
        if img is None:
            img = dither(generated(key))
            self._cache[key] = img
        return img


__all__ = ["ArtProvider", "QColor"]
