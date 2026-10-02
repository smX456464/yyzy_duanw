# -*- coding: utf-8 -*-
"""游戏关闭监听（纯用户态，不需要跨进程改窗口过程）。

背景：跨进程 SetWindowLongPtr 返回 err=5（游戏以管理员运行，我们没有权限），
      SetWinEventHook 的 UIA 事件也不能 OUTOFCONTEXT 跨进程（err=1004）。
可行方案：在本进程内高频轮询"游戏窗口是否还可见"——用户点关闭后，
        窗口会在几十毫秒内变为不可见，这段时间足够我们发出 shutdown。
"""
import ctypes
import ctypes.wintypes as wt
import threading
import time

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.IsWindowVisible.restype = wt.BOOL
user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
user32.EnumWindows.restype = wt.BOOL

UNITY_CLASS = "UnityWndClass"


def find_unity_window(pid):
    """找出目标进程的 Unity 主窗口（可见）。"""
    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(h, l):
        wpid = wt.DWORD(0)
        user32.GetWindowThreadProcessId(h, ctypes.byref(wpid))
        if wpid.value != pid:
            return True
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(h, cls, 256)
        if cls.value == UNITY_CLASS:
            found.append((h, bool(user32.IsWindowVisible(h))))
        return True

    user32.EnumWindows(cb, 0)
    for h, vis in found:
        if vis:
            return h
    return found[0][0] if found else None


class CloseWatcher:
    """轮询游戏窗口可见性：一旦从"可见"变为"不可见/消失"，立即回调。

    轮询间隔 15ms —— 远快于 Unity 销毁内存所需的时间。
    """

    def __init__(self, pid, on_closing, interval=0.015):
        self.pid = pid
        self.on_closing = on_closing
        self.interval = interval
        self._stop = threading.Event()
        self._thread = None
        self.fired = False
        self.started_ok = False

    def _run(self):
        hwnd = find_unity_window(self.pid)
        self.started_ok = hwnd is not None
        if not hwnd:
            return
        last_visible = True
        misses = 0
        while not self._stop.is_set():
            time.sleep(self.interval)
            h = find_unity_window(self.pid)
            if h is None:
                # 窗口句柄查不到（正在销毁）
                if not self.fired:
                    self.fired = True
                    try:
                        self.on_closing()
                    except Exception:
                        pass
                return
            vis = bool(user32.IsWindowVisible(h))
            if last_visible and not vis:
                # 刚被隐藏 → 用户点了关闭（或最小化）
                if not self.fired:
                    self.fired = True
                    try:
                        self.on_closing()
                    except Exception:
                        pass
                return
            last_visible = vis
            misses += 1

    def start(self):
        if self._thread:
            return self.started_ok
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        time.sleep(0.1)          # 等它找到窗口
        return self.started_ok

    def stop(self):
        self._stop.set()
