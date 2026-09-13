"""屏幕截图：一次抓整客户区 + 内存裁剪，失败时自动重建"""
try:
    import mss
    import numpy as np
    _MSS_AVAILABLE = True
    try:
        _mss_factory = mss.MSS
    except AttributeError:
        _mss_factory = mss.mss
except ImportError:
    _MSS_AVAILABLE = False
    _mss_factory = None
    np = None

from .win_utils import get_client_rect_screen

_sct_singleton = None
_consecutive_failures = 0
_MAX_FAILURES = 3


def _get_sct():
    global _sct_singleton
    if _sct_singleton is None and _MSS_AVAILABLE:
        try:
            _sct_singleton = _mss_factory()
        except Exception:
            _sct_singleton = None
    return _sct_singleton


def _rebuild_sct():
    global _sct_singleton, _consecutive_failures
    try:
        _sct_singleton = _mss_factory()
        print("🔧 mss 实例已重建", flush=True)
    except Exception as e:
        print(f"❌ mss 重建失败: {e}", flush=True)
        _sct_singleton = None
    _consecutive_failures = 0


def is_capture_available():
    return _MSS_AVAILABLE


def capture_client_bgra(hwnd):
    global _consecutive_failures
    if not _MSS_AVAILABLE:
        return None, None
    l, t, r, b = get_client_rect_screen(hwnd)
    cw, ch = r - l, b - t
    if cw <= 0 or ch <= 0:
        return None, None
    region = {"left": l, "top": t, "width": cw, "height": ch}
    sct = _get_sct()
    if sct is None:
        _rebuild_sct()
        return None, None
    try:
        img = np.array(sct.grab(region), dtype=np.uint8)
    except Exception as e:
        _consecutive_failures += 1
        if _consecutive_failures >= _MAX_FAILURES:
            print(f"截图失败（连续 {_consecutive_failures} 次）：{e}", flush=True)
            _rebuild_sct()
        return None, None
    _consecutive_failures = 0
    return img, (l, t, cw, ch)


def crop_roi_from_client(full_img, roi_ratio, cw, ch):
    if full_img is None or full_img.size == 0:
        return None
    x1, y1, x2, y2 = roi_ratio
    rl = max(0, int(cw * x1))
    rt = max(0, int(ch * y1))
    rw = max(1, int(cw * (x2 - x1)))
    rh = max(1, int(ch * (y2 - y1)))
    h_img, w_img = full_img.shape[:2]
    rl = min(rl, w_img - 1)
    rt = min(rt, h_img - 1)
    rw = min(rw, w_img - rl)
    rh = min(rh, h_img - rt)
    if rw <= 0 or rh <= 0:
        return None
    return full_img[rt:rt + rh, rl:rl + rw]


def capture_roi_bgra(hwnd, roi_ratio):
    full_img, rect = capture_client_bgra(hwnd)
    if full_img is None or rect is None:
        return None, None
    l, t, cw, ch = rect
    crop = crop_roi_from_client(full_img, roi_ratio, cw, ch)
    if crop is None:
        return None, None
    x1, y1, x2, y2 = roi_ratio
    rl = l + int(cw * x1)
    rt = t + int(ch * y1)
    return crop, (rl, rt, crop.shape[1], crop.shape[0])
