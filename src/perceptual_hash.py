"""感知哈希：用于 OCR 结果缓存。"""
import numpy as np


def perceptual_hash(crop, size=8):
    if crop is None or getattr(crop, "size", 0) == 0:
        return 0
    h, w = crop.shape[:2]
    if h < 1 or w < 1:
        return 0
    ys = np.linspace(0, h - 1, size, dtype=np.int32)
    xs = np.linspace(0, w - 1, size, dtype=np.int32)
    small = crop[np.ix_(ys, xs)]
    gray = (small[:, :, 0].astype(np.float32) * 0.114 +
            small[:, :, 1].astype(np.float32) * 0.587 +
            small[:, :, 2].astype(np.float32) * 0.299)
    mean = gray.mean()
    value = 0
    for b in (gray > mean).flatten():
        value = (value << 1) | int(bool(b))
    return value


def hamming(a, b):
    return bin(a ^ b).count("1")
