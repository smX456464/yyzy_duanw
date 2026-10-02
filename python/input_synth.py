# -*- coding: utf-8 -*-
"""外部输入合成（SendInput）——完全不进入游戏进程。

为什么不用进程内方案：本游戏内部钩 ws2_32 / il2cpp 会与游戏自带的
CrashSight(MinHook) 冲突并导致游戏卡死。改用纯外部方式：
  * 坐标按"游戏窗口客户区的归一化比例"保存 → 换分辨率依然可用
  * 点击/移动用 SendInput，与真人操作同一条路径
"""
import ctypes
import ctypes.wintypes as wt
import time

user32 = ctypes.WinDLL("user32", use_last_error=True)

INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_ABSOLUTE = 0x8000
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD),
                ("dwFlags", wt.DWORD), ("time", wt.DWORD),
                ("dwExtraInfo", ctypes.POINTER(wt.ULONG))]


class INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT)]
    _anonymous_ = ("u",)
    _fields_ = [("type", wt.DWORD), ("u", _U)]


user32.SendInput.argtypes = [wt.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wt.UINT


def _send(flags, x=0, y=0):
    """x,y 为屏幕绝对像素；内部换算到 0..65535 归一化坐标。"""
    vx = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    vy = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    vw = max(1, user32.GetSystemMetrics(SM_CXVIRTUALSCREEN))
    vh = max(1, user32.GetSystemMetrics(SM_CYVIRTUALSCREEN))
    nx = int((x - vx) * 65535 / vw)
    ny = int((y - vy) * 65535 / vh)
    inp = INPUT(type=INPUT_MOUSE)
    inp.mi = MOUSEINPUT(nx, ny, 0, flags | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_MOVE, 0, None)
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def cursor_pos():
    pt = wt.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def move_to(x, y):
    _send(0, x, y)


def click_at(x, y, delay=0.05):
    _send(0, x, y)
    time.sleep(delay)
    _send(MOUSEEVENTF_LEFTDOWN, x, y)
    time.sleep(0.02)
    _send(MOUSEEVENTF_LEFTUP, x, y)


def drag(from_xy, to_xy, steps=12, hold=0.25):
    """按住拖动（卖牌等需要拖拽的操作）。"""
    x1, y1 = from_xy
    x2, y2 = to_xy
    _send(0, x1, y1)
    time.sleep(0.05)
    _send(MOUSEEVENTF_LEFTDOWN, x1, y1)
    time.sleep(hold)
    for i in range(1, steps + 1):
        _send(0, int(x1 + (x2 - x1) * i / steps), int(y1 + (y2 - y1) * i / steps))
        time.sleep(0.02)
    time.sleep(0.05)
    _send(MOUSEEVENTF_LEFTUP, x2, y2)


# ---- 游戏窗口 ----


def find_window(pid, title_hint=None):
    """找目标进程的主窗口（优先可见、有标题的）。"""
    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(hwnd, lparam):
        owner = wt.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value != pid:
            return True
        if not user32.IsWindowVisible(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        rect = wt.RECT()
        user32.GetClientRect(hwnd, ctypes.byref(rect))
        w, h = rect.right - rect.left, rect.bottom - rect.top
        if w > 200 and h > 200:
            found.append((hwnd, buf.value, w, h))
        return True

    user32.EnumWindows(cb, 0)
    if not found:
        return None
    return max(found, key=lambda t: t[2] * t[3])


def client_rect_on_screen(hwnd):
    """返回客户区在屏幕上的 (left, top, width, height)。"""
    rect = wt.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    pt = wt.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return pt.x, pt.y, rect.right - rect.left, rect.bottom - rect.top


def ratio_to_screen(hwnd, rx, ry):
    """归一化比例 → 屏幕像素。"""
    l, t, w, h = client_rect_on_screen(hwnd)
    return int(l + rx * w), int(t + ry * h)


def screen_to_ratio(hwnd, x, y):
    l, t, w, h = client_rect_on_screen(hwnd)
    if w <= 0 or h <= 0:
        return None
    return round((x - l) / w, 4), round((y - t) / h, 4)
