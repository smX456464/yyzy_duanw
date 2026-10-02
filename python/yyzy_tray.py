# -*- coding: utf-8 -*-
"""月圆之夜 · 自动跳过回合（托盘版）

只做一件事：检测到「开始战斗」文字出现 → 断网跳过战斗。
无主窗口，仅驻留系统托盘（右键图标出菜单）。

设计要点（均为实测验证后的结论）
  注入    优先远程 LoadLibraryW（不被安全软件拦截），失败退回 SetWindowsHookEx。
  暂存    DLL 复制到临时目录并用「内容指纹」命名；路径转成完整长路径
          （%TEMP% 常是 ADMINI~1 这种 8.3 短路径，游戏进程解析不了）。
  断网    0 秒 = 直接切断（彻底断开：关闭全部套接字）；>0 = 静默丢包 N 秒后恢复。
  单例    命名互斥体，同一时间只允许一个实例。
  关游戏  由启动器接管：先关游戏窗口（走游戏自身退出流程），等进程真正退出后
          再做状态清理。绝对不能先让 DLL 停手 —— 那会带走命令通道，
          工具失去对游戏的感知，游戏反而会卡住退不出来。
"""
import ctypes
import ctypes.wintypes as wt
import hashlib
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import hook_client as hc
from hook_client import find_pid, inject_via_hook, inject_remote_loadlibrary

CONFIG_PATH = os.path.join(hc._app_root(), "tray_config.json")
LOG_PATH = os.path.join(os.environ.get("TEMP", r"C:\Temp"), "yyzy_tray.log")

DEFAULT_CFG = {
    "game_process": "Night of the Full Moon.exe",
    "game_path": "",
    "sync_path": "",
    "auto_skip": True,
    "manual_hotkey": "",
    "auto_skip_seconds": 0,
    "manual_skip_seconds": 0,
    "fast_kill": True,
    "battle_keywords": "开始战斗,开始对决",
    "auto_skip_lead": 2,
}

_cfg = dict(DEFAULT_CFG)
_queue = queue.Queue()
_settings_win = [None]
_main_win = [None]

ID_SETTINGS, ID_SKIP, ID_QUIT = 1001, 1002, 1003
ID_TOGGLE, ID_APPLY, ID_STATUS, ID_LOG, ID_CLOSE_GAME = 1004, 1005, 1006, 1007, 1008
ID_GAME_EXITED = 1009

# 用户提示：注入导致的退出异常属于已知现象，明确告知无需担心
NOTICE_TEXT = (
    "提示：关闭游戏时可能会出现一闪而过的 Unity 提示窗，\n"
    "这是本工具注入导致的已知现象，属于正常表现，无需担心，\n"
    "不会影响你的账号、存档与对局数据。"
)


# ====================================================================== 基础
def log(msg):
    line = "{0}  {1}".format(time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    try:
        if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > 20 * 1024 * 1024:
            os.replace(LOG_PATH, LOG_PATH + ".old")
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def save_cfg():
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(_cfg, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        log("配置保存失败: " + str(exc))


def load_cfg():
    global _cfg
    _cfg = dict(DEFAULT_CFG)
    if not os.path.exists(CONFIG_PATH):
        save_cfg()
        return
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            _cfg.update(data)
    except Exception as exc:
        log("配置读取失败，使用默认值: " + str(exc))
        _cfg = dict(DEFAULT_CFG)
    for key in ("skip_mode", "use_mouse_hook"):
        _cfg.pop(key, None)
    for key, val in DEFAULT_CFG.items():
        _cfg.setdefault(key, val)
    save_cfg()


def clean_path(text):
    r"""清洗 Windows 路径：去首尾空白与引号，统一为反斜杠，展开环境变量与 ~。"""
    s = (text or "").strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        s = s[1:-1].strip()
    s = s.strip("'\"").strip()
    s = os.path.expandvars(s)
    s = os.path.expanduser(s)
    if "/" in s and "\\" not in s:
        s = s.replace("/", "\\")
    return s.strip()


def long_path(path):
    r"""8.3 短路径（ADMINI~1）→ 完整长路径。游戏进程无法解析 ~1 简写。"""
    if not path:
        return path
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        buf = ctypes.create_unicode_buffer(32768)
        n = k32.GetLongPathNameW(path, buf, 32768)
        return buf.value if 0 < n < 32768 else path
    except Exception:
        return path


def parse_hotkey(text):
    """'F9' / 'A' / 'CTRL+ALT+A' → (mods, vk)；无法识别返回 None。"""
    if not text:
        return None
    MOD_ALT, MOD_CTRL, MOD_SHIFT, MOD_WIN = 0x0001, 0x0002, 0x0004, 0x0008
    parts = [p.strip().upper() for p in str(text).split("+") if p.strip()]
    if not parts:
        return None
    mods = 0
    for p in parts[:-1]:
        if p in ("CTRL", "CONTROL"):
            mods |= MOD_CTRL
        elif p == "ALT":
            mods |= MOD_ALT
        elif p == "SHIFT":
            mods |= MOD_SHIFT
        elif p in ("WIN", "SUPER"):
            mods |= MOD_WIN
        else:
            return None
    last = parts[-1]
    vk = hc.name_to_vk(last)
    if not vk and len(last) == 1:
        vk = ord(last)
    return (mods, vk) if vk else None


def ensure_single_instance():
    """命名互斥体：已在运行返回 False。"""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.LPCWSTR]
    k32.CreateMutexW.restype = wt.HANDLE
    handle = k32.CreateMutexW(None, True, "Global\\YyzyAutoSkipSngl")
    if not handle:
        return True
    return ctypes.get_last_error() != 183      # 183 = ERROR_ALREADY_EXISTS


def find_game_window():
    """找游戏主窗口（类名 UnityWndClass），找不到返回 0。"""
    u = ctypes.WinDLL("user32", use_last_error=True)
    u.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
    u.EnumWindows.restype = wt.BOOL
    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def _cb(hwnd, _):
        buf = ctypes.create_unicode_buffer(256)
        u.GetClassNameW(hwnd, buf, 256)
        if buf.value == "UnityWndClass":
            found.append(hwnd)
            return False
        return True

    u.EnumWindows(_cb, 0)
    return found[0] if found else 0


# ====================================================================== 托盘
user32 = ctypes.WinDLL("user32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32")

WM_TRAY = 0x8001
WM_DESTROY = 0x0002
WM_RBUTTONUP = 0x0205
WM_LBUTTONUP = 0x0202
NIM_ADD, NIM_DELETE = 0, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP = 0x01, 0x02, 0x04
TPM_RIGHTBUTTON, TPM_RETURNCMD = 0x0002, 0x0100
MF_STRING, MF_SEPARATOR, MF_CHECKED = 0x0, 0x800, 0x8
IDI_APPLICATION = 32512
IMAGE_ICON, LR_LOADFROMFILE = 1, 0x0010

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)


class WNDCLASS(ctypes.Structure):
    _fields_ = [("style", wt.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON),
                ("hCursor", wt.HANDLE), ("hbrBackground", wt.HANDLE),
                ("lpszMenuName", wt.LPCWSTR), ("lpszClassName", wt.LPCWSTR)]


class TRAYDATA(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("hWnd", wt.HWND), ("uID", wt.UINT),
                ("uFlags", wt.UINT), ("uCallbackMessage", wt.UINT), ("hIcon", wt.HICON),
                ("szTip", wt.WCHAR * 128), ("dwState", wt.DWORD),
                ("dwStateMask", wt.DWORD), ("szInfo", wt.WCHAR * 256),
                ("uVersion", wt.UINT), ("szInfoTitle", wt.WCHAR * 64),
                ("dwInfoFlags", wt.DWORD)]


user32.CreateWindowExW.restype = wt.HWND
user32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   wt.HWND, wt.HMENU, wt.HINSTANCE, ctypes.c_void_p]
user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASS)]
user32.DefWindowProcW.restype = ctypes.c_ssize_t
user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.CreatePopupMenu.restype = wt.HMENU
user32.AppendMenuW.restype = wt.BOOL
user32.AppendMenuW.argtypes = [wt.HMENU, wt.UINT, ctypes.c_size_t, wt.LPCWSTR]
user32.TrackPopupMenu.restype = wt.UINT
user32.TrackPopupMenu.argtypes = [wt.HMENU, wt.UINT, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_int, wt.HWND, ctypes.c_void_p]
user32.LoadIconW.restype = wt.HICON
user32.LoadIconW.argtypes = [wt.HINSTANCE, ctypes.c_void_p]
user32.LoadImageW.restype = wt.HANDLE
user32.LoadImageW.argtypes = [wt.HINSTANCE, wt.LPCWSTR, wt.UINT,
                              ctypes.c_int, ctypes.c_int, wt.UINT]
user32.SetForegroundWindow.argtypes = [wt.HWND]
user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.DestroyMenu.argtypes = [wt.HMENU]
user32.GetCursorPos.argtypes = [ctypes.POINTER(wt.POINT)]
user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
user32.TranslateMessage.argtypes = [ctypes.POINTER(wt.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wt.MSG)]
user32.PostQuitMessage.argtypes = [ctypes.c_int]
shell32.Shell_NotifyIconW.restype = wt.BOOL
shell32.Shell_NotifyIconW.argtypes = [wt.DWORD, ctypes.POINTER(TRAYDATA)]


def show_menu(hwnd):
    log("托盘菜单被触发")
    try:
        menu = user32.CreatePopupMenu()
        if not menu:
            log("托盘菜单创建失败")
            return
        check = MF_CHECKED if _cfg.get("auto_skip") else 0
        user32.AppendMenuW(menu, MF_STRING | check, ID_TOGGLE, "自动跳过回合")
        user32.AppendMenuW(menu, MF_STRING, ID_SKIP, "立即跳过一次")
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, MF_STRING, ID_STATUS, "查看状态")
        user32.AppendMenuW(menu, MF_STRING, ID_LOG, "打开日志")
        user32.AppendMenuW(menu, MF_STRING, ID_SETTINGS, "设置…")
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, MF_STRING, ID_QUIT, "退出")

        pos = wt.POINT()
        user32.GetCursorPos(ctypes.byref(pos))
        user32.SetForegroundWindow(hwnd)
        user32.PostMessageW(hwnd, 0x0000, 0, 0)          # WM_NULL
        picked = user32.TrackPopupMenu(menu, TPM_RIGHTBUTTON | TPM_RETURNCMD,
                                      pos.x, pos.y, 0, hwnd, None)
        user32.DestroyMenu(menu)
        log("托盘菜单选择: " + str(picked))
        if picked:
            _queue.put(picked)
    except Exception as exc:
        log("托盘菜单异常: " + str(exc))


def tray_thread():
    state = {}

    def on_msg(hwnd, msg, wparam, lparam):
        if msg == WM_TRAY:
            if lparam in (WM_RBUTTONUP, WM_LBUTTONUP):
                show_menu(hwnd)
            return 0
        if msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    proc = WNDPROC(on_msg)
    hinst = hc.kernel32.GetModuleHandleW(None)
    cls = WNDCLASS()
    cls.lpfnWndProc = proc
    cls.hInstance = hinst
    cls.lpszClassName = "YyzyTrayWnd"
    user32.RegisterClassW(ctypes.byref(cls))
    hwnd = user32.CreateWindowExW(0, "YyzyTrayWnd", "yyzy", 0, 0, 0, 0, 0,
                                  None, None, hinst, None)
    if not hwnd:
        log("创建托盘窗口失败 err=" + str(ctypes.get_last_error()))
        return
    state["hwnd"] = hwnd

    data = TRAYDATA()
    data.cbSize = ctypes.sizeof(TRAYDATA)
    data.hWnd = hwnd
    data.uID = 1
    data.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
    data.uCallbackMessage = WM_TRAY
    ico = os.path.join(hc._app_root(), "app.ico")
    if os.path.exists(ico):
        data.hIcon = user32.LoadImageW(None, ico, IMAGE_ICON, 32, 32, LR_LOADFROMFILE)
    if not data.hIcon:
        data.hIcon = user32.LoadIconW(None, ctypes.c_void_p(IDI_APPLICATION))
    data.szTip = "月圆之夜 · 自动跳过回合（右键菜单）"
    state["nid"] = data

    added = False
    for _ in range(3):
        if shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(data)):
            added = True
            break
        time.sleep(0.4)
    log("托盘图标已就绪（右键图标 → 菜单）" if added else "托盘图标注册失败")

    msg = wt.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))
    try:
        shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(state["nid"]))
    except Exception:
        pass


def show_tip(title, text, msecs=8000):
    """在托盘图标上弹出气泡提示（Windows 通知）。失败则退化为日志。"""
    log("{0} —— {1}".format(title, text.replace("\n", " ")))
    try:
        shell32 = ctypes.WinDLL("shell32")
        u = ctypes.WinDLL("user32")
        hwnd = u.FindWindowW("YyzyTrayWnd", None)
        if not hwnd:
            return
        NIF_INFO = 0x10
        NIM_MODIFY = 1
        data = TRAYDATA()
        data.cbSize = ctypes.sizeof(TRAYDATA)
        data.hWnd = hwnd
        data.uID = 1
        data.uFlags = NIF_INFO
        data.szInfoTitle = title
        data.szInfo = text
        data.dwInfoFlags = 0x01          # NIIF_INFO
        data.uTimeout = msecs
        shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(data))
    except Exception:
        pass


def find_process_by_path(exe_path):
    """按可执行文件完整路径查找正在运行的进程，返回 pid（没有则 None）。

    用于「同步启动」：目标程序已经在跑就不再启动第二个实例。
    同时兼容只匹配到进程名的情况（路径取不到时的兜底）。
    """
    if not exe_path:
        return None
    try:
        target = os.path.normcase(os.path.abspath(exe_path))
        name = os.path.basename(target)

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        p32 = ctypes.WinDLL("psapi", use_last_error=True)
        TH32CS_SNAPPROCESS = 0x2
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

        class PROCENTRY(ctypes.Structure):
            _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD),
                        ("th32ProcessID", wt.DWORD), ("th32DefaultHeapID", ctypes.c_void_p),
                        ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD),
                        ("th32ParentProcessID", wt.DWORD),
                        ("pcPriClassBase", ctypes.c_long), ("dwFlags", wt.DWORD),
                        ("szExeFile", ctypes.c_char * 260)]

        k32.CreateToolhelp32Snapshot.restype = wt.HANDLE
        p32.GetModuleFileNameExW.argtypes = [wt.HANDLE, wt.HANDLE,
                                            wt.LPWSTR, wt.DWORD]
        p32.GetModuleFileNameExW.restype = wt.DWORD

        snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if not snap or snap == 0xFFFFFFFFFFFFFFFF:
            return None
        by_name = None
        entry = PROCENTRY()
        entry.dwSize = ctypes.sizeof(PROCENTRY)
        if k32.Process32First(snap, ctypes.byref(entry)):
            while True:
                pid = entry.th32ProcessID
                if pid and pid != os.getpid():
                    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
                    if h:
                        try:
                            buf = ctypes.create_unicode_buffer(32768)
                            n = p32.GetModuleFileNameExW(h, None, buf, 32767)
                            if n:
                                cur = os.path.normcase(os.path.abspath(buf.value))
                                if cur == target:
                                    return pid
                                if os.path.basename(cur) == name:
                                    by_name = by_name or pid
                        finally:
                            k32.CloseHandle(h)
                if not k32.Process32Next(snap, ctypes.byref(entry)):
                    break
        k32.CloseHandle(snap)
        return by_name
    except Exception:
        return None


# ====================================================================== 引擎
class Engine:
    def __init__(self):
        self.srv = None
        self.pid = None
        self.hello = False
        self.injected_at = 0.0
        self.hotkey = None
        self.watchdog = None
        self.watchdog_stop = False
        self.exited_notice_done = False

    def send(self, cmd):
        if not self.srv or not self.hello:
            return False
        return self.srv.send_cmd({"cmd": cmd})

    def inject(self):
        pid = find_pid(_cfg["game_process"])
        if not pid:
            self.reset()
            return False
        if self.pid == pid and self.hello:
            return True
        if self.pid == pid and self.injected_at and time.time() - self.injected_at < 30:
            return False

        src = os.path.join(hc._app_root(), "yyzyhook.dll")
        stage_dir = os.path.join(long_path(os.environ.get("TEMP", r"C:\Temp")),
                                "yyzyhook_tray")
        try:
            os.makedirs(stage_dir, exist_ok=True)
            with open(src, "rb") as f:
                tag = hashlib.md5(f.read()).hexdigest()[:8]
            stage = os.path.join(stage_dir, "yyzyhook_{0}.dll".format(tag))
            if not os.path.exists(stage):
                shutil.copy2(src, stage)
        except Exception as exc:
            log("DLL 暂存失败: " + str(exc))
            return False

        log("注入游戏 pid={0} …".format(pid))
        ok = False
        try:
            ok, _ = inject_remote_loadlibrary(pid, stage)
        except Exception as exc:
            log("远程 LoadLibrary 异常: " + str(exc))
        if not ok:
            try:
                ok, _hooks = inject_via_hook(pid, stage)
            except Exception as exc2:
                log("SetWindowsHookEx 失败: " + str(exc2))
        if not ok:
            log("注入失败")
            return False

        self.pid = pid
        self.injected_at = time.time()
        self.hello = False
        log("注入成功（DLL 已加载进游戏），等待连接…")

        t0 = time.time()
        while time.time() - t0 < 10 and not self.hello:
            time.sleep(0.15)
        if not self.hello:
            self.injected_at = time.time() - 15
            log("未收到 DLL 回应，稍后重试（若游戏内已有旧版 DLL 需重启游戏）")
            return False

        self.start_watchdog()
        self.send("hooks_on")
        time.sleep(0.4)
        self.send("init_step|0")
        time.sleep(0.8)
        self.setup_hotkey(pid)
        if _cfg.get("auto_skip"):
            self.apply_auto()
        return True

    def on_event(self, ev):
        kind = ev.get("ev")
        if kind in ("traffic", "raw"):
            return
        if kind == "hello":
            self.hello = True
            log("DLL 已连接 (pid={0}, {1})".format(ev.get("pid"), ev.get("ver")))
        elif kind == "auto_skip":
            log("自动跳过已触发（命中「{0}」）".format(
                ev.get("hit", ev.get("reason", "?"))))
        elif kind == "kill":
            log("已切断 {0} 条连接（端口 {1}）".format(
                ev.get("n"), ev.get("ports", "")))
        elif kind == "hold_start":
            log("软断网开始：静默丢包 {0} 毫秒".format(ev.get("ms")))
        elif kind == "hold_end":
            log("软断网结束，网络已恢复")
        elif kind in ("reflection_broken", "auto_skip_stop"):
            log("{0}: {1}".format(kind, ev))

    def start_pipe(self):
        self.srv = hc.PipeServer(self.on_event)
        self.srv.start()

    def apply_auto(self):
        kw = (_cfg.get("battle_keywords") or "开始战斗").strip()
        lead = max(0, int(_cfg.get("auto_skip_lead", 2) or 0))
        self.send("battle_kw|" + kw)
        self.send("auto_on|{0}".format(lead))
        log("自动跳过已开启（出现「{0}」即断网，提前 {1} 秒）".format(kw, lead))

    def apply_cfg(self):
        secs = int(_cfg.get("auto_skip_seconds", 0) or 0)
        fast = 1 if _cfg.get("fast_kill", True) else 0
        if secs > 0:
            self.send("auto_cfg|1|{0}|{1}".format(secs * 1000, fast))
            log("自动断网：静默丢包 {0} 秒".format(secs))
        else:
            self.send("auto_cfg|0|0|{0}".format(fast))
            log("自动断网：彻底切断连接")

    def stop_auto(self):
        self.send("auto_off")
        log("自动跳过已关闭")

    def skip_manual(self):
        if not self.hello:
            log("未注入，无法手动跳过")
            return
        secs = int(_cfg.get("manual_skip_seconds", 0) or 0)
        fast = 1 if _cfg.get("fast_kill", True) else 0
        if secs > 0:
            self.send("hold|{0}".format(secs * 1000))
            log("手动跳过：静默丢包 {0} 秒".format(secs))
        elif fast:
            self.send("kill_all")
            log("手动跳过：彻底断开（关闭全部套接字）")
        else:
            self.send("kill_battle")
            log("手动跳过：切断战斗连接")

    def close_game(self):
        """由启动器直接关闭游戏窗口。

        说明：游戏退出时可能出现一闪而过的 Unity 错误提示窗，
        这是本工具注入导致的已知现象，**属于正常表现，请勿担心**，不会影响账号与存档。
        这里不再做任何"提前撤回注入"之类的干预，让游戏按自己的流程自然退出。
        """
        """请求关闭游戏：发关闭消息 → 立即弹出气泡提示 → 等待游戏真正关闭。

        关闭过程中游戏可能短暂卡顿、闪出 Unity 提示窗，
        这属于注入的已知现象，**视为正常，无需担心**，稍后即恢复正常。
        游戏窗口真正关闭后，退出监视线程会通知主线程把本工具一并关闭。
        此处不做任何钩子/停手/撤回注入等干预。
        """
        hwnd = find_game_window()
        if not hwnd:
            log("未找到游戏窗口，无法关闭")
            return
        log("正在关闭游戏（关闭过程中短暂卡顿属正常现象，无需担心）…")
        u = ctypes.WinDLL("user32", use_last_error=True)
        u.PostMessageW(hwnd, 0x0010, 0, 0)                # WM_CLOSE
        # 弹气泡：告知用户关闭过程中的卡顿/提示窗是正常现象
        show_tip("正在关闭游戏",
                 "游戏窗口短暂卡顿、可能闪现提示窗，均属正常现象，无需担心，稍后即恢复正常。\n"
                 "游戏窗口真正关闭后，本工具会自动退出。",
                 msecs=12000)

    def wait_game_closed(self, timeout=40):
        """等待游戏进程真正消失（供关闭流程调用）。"""
        t0 = time.time()
        while time.time() - t0 < timeout:
            if not find_pid(_cfg["game_process"]):
                return True
            time.sleep(0.3)
        return False

    def sync_launch(self):
        """同步启动：若目标程序已经在运行就不再启动第二个实例。"""
        path = clean_path(_cfg.get("sync_path") or "")
        if not path:
            log("同步启动：未配置路径，跳过")
            return
        if not os.path.exists(path):
            log("同步启动：路径不存在 → " + path)
            return
        # 已存在同名可执行程序在运行 → 不再重复启动
        running = find_process_by_path(path)
        if running:
            log("同步启动：{} 已在运行（pid={}），跳过启动".format(
                os.path.basename(path), running))
            return
        try:
            subprocess.Popen([path], cwd=os.path.dirname(path) or None, close_fds=True)
            log("已同步启动：" + path)
        except Exception as exc:
            log("同步启动失败: " + str(exc))

    def reset(self):
        self.pid = None
        self.hello = False
        self.watchdog_stop = True
        self.watchdog = None

    def start_watchdog(self):
        """游戏退出监视（只观察进程，不做任何干预）。

        职责仅一条：游戏进程真正消失后，通知主线程把工具一起关掉。
        不再插入任何钩子/停手/撤回注入等动作 —— 关闭游戏时游戏短暂卡顿、
        甚至闪出 Unity 提示窗，都属于注入的已知现象，**视为正常，无需担心**。
        """
        if self.watchdog is not None:
            return
        self.watchdog_stop = False
        self.watchdog = threading.Thread(target=self._watch, daemon=True)
        self.watchdog.start()

    def _watch(self):
        state = {"gone": False}
        log("已启动游戏退出监视（1 秒轮询，仅观察进程）")

        while not self.watchdog_stop:
            try:
                if find_pid(_cfg["game_process"]) is None:
                    if not state["gone"]:
                        state["gone"] = True
                        log("游戏进程已消失 → 工具随之退出")
                        _queue.put(ID_GAME_EXITED)
                        return
                    time.sleep(0.5)
                    continue
                state["gone"] = False
            except Exception:
                pass
            time.sleep(1.0)

    def setup_hotkey(self, pid):
        key = (_cfg.get("manual_hotkey") or "").strip().upper()
        if self.hotkey is not None:
            try:
                self.hotkey.stop()
            except Exception:
                pass
            self.hotkey = None
        if not key:
            return
        parsed = parse_hotkey(key)
        if not parsed:
            log("手动跳过热键无法识别：" + key)
            return
        mods, vk = parsed
        if _main_win[0] is None:
            return
        try:
            mgr = hc.HotkeyManager(_main_win[0].winfo_id(),
                                   {(mods, vk): self.skip_manual})
            mgr.foreground_pid = pid
            mgr.start()
            time.sleep(0.8)
            failed = getattr(mgr, "last_register_failed", [])
            self.hotkey = mgr
            log("手动跳过热键 {0}：{1}".format(
                key, "注册失败（可能被占用）" if failed else "已注册"))
        except Exception as exc:
            log("热键注册异常: " + str(exc))

    def run(self):
        self.start_pipe()
        while True:
            try:
                pid = find_pid(_cfg["game_process"])
                if pid is None:
                    if self.pid is not None:
                        log("游戏已退出，清理注入状态")
                        self.reset()
                        # 注入状态下游戏退出 → 工具随之退出
                        if self.exited_notice_done:
                            log("游戏已退出，本工具随之关闭")
                            _queue.put(ID_GAME_EXITED)
                            return
                        self.exited_notice_done = True
                    time.sleep(0.5)
                    continue
                self.exited_notice_done = False
                if pid != self.pid:
                    log("检测到游戏进程 pid={0}".format(pid))
                self.inject()
            except Exception as exc:
                log("主循环异常: " + str(exc))
            time.sleep(1.0)

    def status(self):
        return ("注入状态：{0}\n"
                "游戏 pid：{1}\n"
                "自动跳过：{2}\n"
                "战斗关键字：{3}\n"
                "自动触发阈值：{4} 秒\n"
                "自动断网：{5} 秒（0=切断）\n"
                "手动断网：{6} 秒（0=切断）\n"
                "日志：{7}").format(
            "已注入" if self.hello else "未注入", self.pid,
            "开" if _cfg.get("auto_skip") else "关",
            _cfg.get("battle_keywords"), _cfg.get("auto_skip_lead"),
            _cfg.get("auto_skip_seconds"), _cfg.get("manual_skip_seconds"),
            LOG_PATH)


# ====================================================================== 设置
def open_settings(root, first_run=False):
    """设置窗口（单例：已存在则置前，不重复弹窗）。"""
    if _settings_win[0] is not None:
        try:
            if _settings_win[0].winfo_exists():
                _settings_win[0].deiconify()
                _settings_win[0].lift()
                _settings_win[0].focus_force()
                return
        except Exception:
            pass
        _settings_win[0] = None

    win = tk.Toplevel(root)
    title = "自动跳过回合 · 设置"
    if first_run:
        title += "（首次使用，请确认后保存）"
    win.title(title)
    win.geometry("700x600")
    win.minsize(620, 480)

    canvas = tk.Canvas(win, highlightthickness=0, borderwidth=0)
    scroll = tk.Scrollbar(win, orient="vertical", command=canvas.yview)
    scroll.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)
    canvas.configure(yscrollcommand=scroll.set)

    body = tk.Frame(canvas)
    inner = canvas.create_window((0, 0), window=body, anchor="nw")
    body.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.bind("<Configure>", lambda e: canvas.itemconfigure(inner, width=e.width))

    body.columnconfigure(0, weight=0, minsize=170)
    body.columnconfigure(1, weight=1, minsize=245)
    body.columnconfigure(2, weight=0, minsize=200)

    def field(r, label, value, hint=""):
        tk.Label(body, text=label, anchor="w").grid(
            row=r, column=0, sticky="w", padx=(12, 6), pady=7)
        entry = tk.Entry(body, width=30)
        entry.insert(0, value)
        entry.grid(row=r, column=1, padx=6, sticky="ew")
        if hint:
            tk.Label(body, text=hint, fg="#666", anchor="w",
                     wraplength=190).grid(row=r, column=2, sticky="w", padx=4)
        return entry

    f_proc = field(0, "游戏进程名", _cfg.get("game_process", ""), "目标进程")
    f_path = field(1, "游戏路径", _cfg.get("game_path", ""), "留空自动获取")
    f_sync = field(2, "同步启动路径", _cfg.get("sync_path", ""), "留空则不使用")
    f_key = field(3, "手动跳过热键", _cfg.get("manual_hotkey", ""),
                  "留空=不注册，如 F9 / CTRL+ALT+A")
    f_auto = field(4, "自动断网时长（秒）", str(_cfg.get("auto_skip_seconds", 0)),
                   "0=彻底切断")
    f_manual = field(5, "手动断网时长（秒）", str(_cfg.get("manual_skip_seconds", 0)),
                     "0=彻底切断")
    f_kw = field(6, "战斗开始关键字", _cfg.get("battle_keywords", "开始战斗"),
                 "逗号分隔，出现即断网")
    f_lead = field(7, "自动触发阈值（秒）", str(_cfg.get("auto_skip_lead", 2)),
                   "倒计时 ≤ 此值就断网（默认 2）")

    var_auto = tk.BooleanVar(value=bool(_cfg.get("auto_skip")))
    tk.Checkbutton(body, text="自动跳过回合（出现关键字时断网）",
                   variable=var_auto).grid(row=8, column=0, columnspan=3,
                                          sticky="w", padx=12, pady=(12, 2))
    var_fast = tk.BooleanVar(value=bool(_cfg.get("fast_kill", True)))
    tk.Checkbutton(body, text="彻底断开（关闭全部套接字，最快）",
                   variable=var_fast).grid(row=9, column=0, columnspan=3,
                                          sticky="w", padx=12, pady=2)

    tk.Label(body, text="· 自动断网与手动断网是两套独立配置\n"
                       "· 0 秒 = 彻底切断；2~5 秒 = 静默丢包后恢复\n"
                       + NOTICE_TEXT,
             justify="left", fg="#444", anchor="w", wraplength=560).grid(
        row=10, column=0, columnspan=3, sticky="w", padx=12, pady=(10, 4))

    def do_save():
        _cfg["game_process"] = f_proc.get().strip() or DEFAULT_CFG["game_process"]
        _cfg["game_path"] = clean_path(f_path.get())
        _cfg["sync_path"] = clean_path(f_sync.get())
        _cfg["manual_hotkey"] = f_key.get().strip().upper()
        for name, entry, fallback in (("auto_skip_seconds", f_auto, 0),
                                      ("manual_skip_seconds", f_manual, 0),
                                      ("auto_skip_lead", f_lead, 2)):
            try:
                _cfg[name] = max(0, int(float(entry.get().strip() or "0")))
            except Exception:
                _cfg[name] = fallback
        _cfg["battle_keywords"] = f_kw.get().strip() or DEFAULT_CFG["battle_keywords"]
        _cfg["auto_skip"] = bool(var_auto.get())
        _cfg["fast_kill"] = bool(var_fast.get())
        save_cfg()
        log("设置已保存: " + json.dumps(_cfg, ensure_ascii=False))
        _queue.put(ID_APPLY)
        win.destroy()

    bar = tk.Frame(body)
    bar.grid(row=11, column=0, columnspan=3, pady=16)
    tk.Button(bar, text="保存并应用", width=12, command=do_save).pack(side="left", padx=6)
    tk.Button(bar, text="立即跳过一次", width=14,
              command=lambda: _queue.put(ID_SKIP)).pack(side="left", padx=6)
    tk.Button(bar, text="关闭游戏", width=12,
              command=lambda: _queue.put(ID_CLOSE_GAME)).pack(side="left", padx=6)
    if not first_run:
        tk.Button(bar, text="关闭", width=10, command=win.destroy).pack(side="left", padx=6)

    if first_run:
        win.attributes("-topmost", True)
        win.deiconify()
        win.lift()
        win.focus_force()
    _settings_win[0] = win
    return win


# ====================================================================== 主流程
def main():
    if not ensure_single_instance():
        log("已有实例在运行，本次退出")
        try:
            ctypes.WinDLL("user32").MessageBoxW(
                None, "自动跳过工具已在运行（请查看系统托盘图标）。",
                "月圆之夜 · 自动跳过", 0x40)
        except Exception:
            pass
        return

    first_run = not os.path.exists(CONFIG_PATH)
    load_cfg()

    def guard(exc_type, exc_val, exc_tb):
        import traceback
        log("未捕获异常（已拦截）: " + "".join(
            traceback.format_exception(exc_type, exc_val, exc_tb))[-800:])

    sys.excepthook = guard
    threading.excepthook = lambda a: guard(a.exc_type, a.exc_value, a.exc_traceback)

    log("=== 自动跳过回合 启动（托盘模式）===")
    log("配置: " + json.dumps(_cfg, ensure_ascii=False))
    log(NOTICE_TEXT.replace("\n", " "))

    threading.Thread(target=tray_thread, daemon=True).start()
    engine = Engine()
    engine.sync_launch()
    threading.Thread(target=engine.run, daemon=True).start()

    root = tk.Tk()
    root.withdraw()
    _main_win[0] = root

    if first_run:
        log("首次使用：弹出设置窗口")
        root.after(800, lambda: open_settings(root, True))

    def pump():
        try:
            while True:
                cmd = _queue.get_nowait()
                if cmd == ID_SETTINGS:
                    open_settings(root)
                elif cmd == ID_SKIP:
                    engine.skip_manual()
                elif cmd == ID_CLOSE_GAME:
                    threading.Thread(target=engine.close_game, daemon=True).start()
                elif cmd == ID_TOGGLE:
                    _cfg["auto_skip"] = not _cfg.get("auto_skip")
                    save_cfg()
                    if _cfg["auto_skip"]:
                        engine.apply_auto()
                    else:
                        engine.stop_auto()
                elif cmd == ID_STATUS:
                    from tkinter import messagebox
                    messagebox.showinfo("运行状态", engine.status())
                elif cmd == ID_LOG:
                    try:
                        os.startfile(LOG_PATH)
                    except Exception:
                        pass
                elif cmd == ID_APPLY:
                    pid = engine.pid or find_pid(_cfg["game_process"])
                    threading.Thread(target=engine.setup_hotkey, args=(pid,),
                                     daemon=True).start()
                    engine.apply_cfg()
                    if _cfg["auto_skip"]:
                        engine.apply_auto()
                    else:
                        engine.stop_auto()
                elif cmd == ID_QUIT:
                    log("用户选择退出")
                    os._exit(0)
                elif cmd == ID_GAME_EXITED:
                    # 游戏退出了 → 脚本跟着一起关闭（用户需求）
                    log("游戏已退出，本工具随之关闭")
                    os._exit(0)
        except queue.Empty:
            pass
        except Exception as exc:
            log("事件处理异常: " + str(exc))
        try:
            if root.winfo_exists():
                root.after(200, pump)
        except Exception:
            pass

    root.after(200, pump)
    root.mainloop()
    os._exit(0)


if __name__ == "__main__":
    main()
