"""Windows API 封装"""
import ctypes
from ctypes import windll, wintypes
import os
import subprocess
import time

_user32 = ctypes.windll.user32
_dwmapi = ctypes.windll.dwmapi

DWMWA_CLOAKED = 14
GA_ROOT = 2
GWL_STYLE = -16
GWL_EXSTYLE = -20
WS_CHILD = 0x40000000
WS_EX_TRANSPARENT = 0x20
GW_OWNER = 4

def set_click_through(hwnd):
    try:
        ex = _user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        _user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex | WS_EX_TRANSPARENT)
    except:
        pass

def get_hwnd_by_pid(pid):
    if not pid: return None
    result = []
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if not _user32.IsWindowVisible(hwnd): return True
        wpid = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
        if wpid.value != pid: return True
        style = _user32.GetWindowLongW(hwnd, GWL_STYLE)
        if style & WS_CHILD: return True
        if _user32.GetWindow(hwnd, GW_OWNER): return True
        r = wintypes.RECT()
        _user32.GetWindowRect(hwnd, ctypes.byref(r))
        if r.right - r.left <= 0 or r.bottom - r.top <= 0: return True
        result.append(hwnd)
        return True
    _user32.EnumWindows(WNDENUMPROC(cb), 0)
    return result[0] if result else None

_pid_cache = {}
_PID_CACHE_TTL = 5.0


def get_pid_by_exe_name(exe_name):
    if not exe_name:
        return None
    now = time.time()
    cached = _pid_cache.get(exe_name)
    if cached is not None:
        pid_c, ts = cached
        if now - ts < _PID_CACHE_TTL:
            return pid_c
    pid = None
    try:
        out = subprocess.check_output(
            f'tasklist /fi "imagename eq {exe_name}" /fo csv /nh',
            shell=True, encoding="gbk", errors="ignore")
        for line in out.splitlines():
            parts = [p.strip('"') for p in line.split('","')]
            if len(parts) >= 2 and parts[0].lower() == exe_name.lower():
                try:
                    pid = int(parts[1])
                except Exception:
                    pass
                break
    except Exception:
        pass
    _pid_cache[exe_name] = (pid, now)
    return pid

def get_window_rect(hwnd):
    r = wintypes.RECT()
    _user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom

def get_client_rect_screen(hwnd):
    r = wintypes.RECT()
    _user32.GetClientRect(hwnd, ctypes.byref(r))
    pt = wintypes.POINT(0, 0)
    _user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return pt.x, pt.y, pt.x + (r.right - r.left), pt.y + (r.bottom - r.top)

def is_window_alive(hwnd):
    return bool(hwnd) and bool(_user32.IsWindow(hwnd))

def is_window_visible(hwnd):
    return bool(_user32.IsWindowVisible(hwnd))

def is_window_minimized(hwnd):
    return bool(_user32.IsIconic(hwnd))

def is_window_cloaked(hwnd):
    val = ctypes.c_int(0)
    try:
        _dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED,
                                      ctypes.byref(val), ctypes.sizeof(val))
    except:
        return False
    return val.value != 0

def has_valid_rect(hwnd):
    l, t, r, b = get_window_rect(hwnd)
    if r - l <= 0 or b - t <= 0: return False
    if l < -10000 or t < -10000: return False
    return True

def is_window_foreground(hwnd):
    if not hwnd: return False
    try:
        fg = _user32.GetForegroundWindow()
        if not fg: return False
        if fg == hwnd: return True
        return _user32.GetAncestor(fg, GA_ROOT) == hwnd
    except:
        return False

def _is_ancestor_of_any(hwnd, candidates):
    if not hwnd or not candidates: return False
    cand = set(c for c in candidates if c)
    root = _user32.GetAncestor(hwnd, GA_ROOT)
    if root in cand: return True
    cur = hwnd
    for _ in range(8):
        if cur in cand: return True
        cur = _user32.GetAncestor(cur, GA_ROOT)
        if not cur: break
    return False

def is_window_covered(hwnd, exclude_hwnds=(), samples=None):
    if samples is None:
        samples = [(0.5, 0.5), (0.2, 0.2), (0.8, 0.2), (0.2, 0.8), (0.8, 0.8)]
    l, t, r, b = get_client_rect_screen(hwnd)
    w, h = r - l, b - t
    if w <= 0 or h <= 0: return True
    for fx, fy in samples:
        px = l + int(w * fx)
        py = t + int(h * fy)
        pt = wintypes.POINT(px, py)
        top = _user32.WindowFromPoint(pt)
        if not top: return True
        root = _user32.GetAncestor(top, GA_ROOT)
        if root == hwnd: continue
        if _is_ancestor_of_any(top, exclude_hwnds): continue
        return True
    return False

def is_game_window_on_screen(exe_name):
    pid = get_pid_by_exe_name(exe_name)
    if pid is None: return False
    hwnd = get_hwnd_by_pid(pid)
    if not hwnd: return False
    if not is_window_alive(hwnd) or not is_window_visible(hwnd): return False
    if is_window_minimized(hwnd) or is_window_cloaked(hwnd): return False
    return True

def is_process_running(exe_path):
    if not exe_path: return False
    exe_name = os.path.basename(exe_path)
    try:
        cmd = f'tasklist /fi "imagename eq {exe_name}" /fo csv /nh'
        return exe_name in subprocess.check_output(cmd, shell=True, encoding="gbk")
    except:
        return False


# ============================================
# 屏幕捕获排除 API
# WDA_EXCLUDEFROMCAPTURE：让窗口从屏幕捕获中消失（Win10 2004+）
# 用于：让 RoiOverlay 对 mss 截图不可见，但人眼正常可见
# ============================================
WDA_NONE = 0x00000000
WDA_EXCLUDEFROMCAPTURE = 0x00000011


def set_window_capture_exclude(hwnd):
    """让窗口从屏幕捕获 API 中排除（Win10 2004+）。
    成功返回 True；老系统上可能失败返回 False。"""
    try:
        return bool(_user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE))
    except Exception:
        return False


def clear_window_capture_exclude(hwnd):
    """取消排除（恢复默认捕获行为）"""
    try:
        return bool(_user32.SetWindowDisplayAffinity(hwnd, WDA_NONE))
    except Exception:
        return False
