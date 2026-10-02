# -*- coding: utf-8 -*-
"""
yyzy_hook 客户端（Phase 1）
- 命名管道服务：接收钩子 DLL 事件、下发命令
- 注入器：把 yyzyhook.dll 注入目标进程
- 全局热键：默认 F8 = 秒断战斗连接（键位后续进配置）
- 简易状态窗（正式界面在 Phase 4 重做）
"""
import ctypes
import ctypes.wintypes as wt
import json
import os
import sys
import threading
import time

PIPE_NAME = r"\\.\pipe\yyzyhook_v16"   # 与 DLL 的管道名保持一致（版本化，避免旧模块抢占）


def _app_root():
    """程序根目录：源码模式=tools_hook；打包模式=exe 所在目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


DLL_PATH = os.path.join(_app_root(), "yyzyhook.dll")
GAME_PROCESS = "Night of the Full Moon.exe"

# ---------------- Win32 helpers ----------------
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)

# ---- 64 位安全：显式声明返回类型（默认 c_int 会截断句柄/地址） ----
kernel32.OpenProcess.restype = wt.HANDLE
kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
kernel32.VirtualAllocEx.restype = ctypes.c_void_p
kernel32.VirtualAllocEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wt.DWORD, wt.DWORD]
kernel32.WriteProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
kernel32.CreateRemoteThread.restype = wt.HANDLE
kernel32.CreateRemoteThread.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD)]
kernel32.GetProcAddress.restype = ctypes.c_void_p
kernel32.GetProcAddress.argtypes = [wt.HMODULE, ctypes.c_char_p]
kernel32.GetModuleHandleW.restype = wt.HMODULE
kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
kernel32.CreateToolhelp32Snapshot.restype = wt.HANDLE
kernel32.CreateNamedPipeW.restype = wt.HANDLE
kernel32.ConnectNamedPipe.restype = wt.BOOL
kernel32.ConnectNamedPipe.argtypes = [wt.HANDLE, ctypes.c_void_p]
kernel32.DisconnectNamedPipe.restype = wt.BOOL
kernel32.DisconnectNamedPipe.argtypes = [wt.HANDLE]
kernel32.ReadFile.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
kernel32.WriteFile.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
kernel32.PeekNamedPipe.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD), ctypes.POINTER(wt.DWORD), ctypes.POINTER(wt.DWORD)]
kernel32.PeekNamedPipe.restype = wt.BOOL
kernel32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
kernel32.WaitForSingleObject.restype = wt.DWORD
kernel32.GetExitCodeThread.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]
kernel32.GetExitCodeThread.restype = wt.BOOL
kernel32.LoadLibraryW.restype = wt.HMODULE
kernel32.LoadLibraryW.argtypes = [wt.LPCWSTR]
kernel32.LoadLibraryExW.restype = wt.HMODULE
kernel32.LoadLibraryExW.argtypes = [wt.LPCWSTR, wt.HANDLE, wt.DWORD]
kernel32.Thread32First.restype = wt.BOOL
kernel32.Thread32Next.restype = wt.BOOL
user32.SetWindowsHookExW.restype = ctypes.c_void_p
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, ctypes.c_void_p, wt.HINSTANCE, wt.DWORD]
user32.PostThreadMessageW.restype = wt.BOOL
user32.PostThreadMessageW.argtypes = [wt.DWORD, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.UnhookWindowsHookEx.restype = wt.BOOL
user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
user32.CallNextHookEx.restype = ctypes.c_ssize_t
user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, wt.WPARAM, wt.LPARAM]

PROCESS_ALL_ACCESS = 0x001F0FFF
MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
PAGE_READWRITE = 0x04
INFINITE = 0xFFFFFFFF
PIPE_ACCESS_DUPLEX = 0x00000003
PIPE_TYPE_MESSAGE = 0x00000004
PIPE_READMODE_MESSAGE = 0x00000002
PIPE_WAIT = 0x00000000
TH32CS_SNAPPROCESS = 0x00000002
WM_HOTKEY = 0x0312
MOD_NOREPEAT = 0x4000


def find_pid(proc_name):
    """按进程名找 PID（CTRL+ALT+DEL 风格，无需 psutil）。"""
    class PROCESSENTRY32(ctypes.Structure):
        _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD),
                    ("th32ProcessID", wt.DWORD), ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                    ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD),
                    ("th32ParentProcessID", wt.DWORD), ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", wt.DWORD), ("szExeFile", ctypes.c_char * 260)]

    h = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if h == -1:
        return None
    entry = PROCESSENTRY32()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
    try:
        if kernel32.Process32First(h, ctypes.byref(entry)):
            while True:
                if entry.szExeFile.decode("gbk", "ignore") == proc_name:
                    return int(entry.th32ProcessID)
                if not kernel32.Process32Next(h, ctypes.byref(entry)):
                    break
    finally:
        kernel32.CloseHandle(h)
    return None


def inject_via_hook(pid, dll_path):
    """SetWindowsHookEx(WH_GETMESSAGE) 钩子注入。
    对 CreateRemoteThread 被安全软件拦截的场景更友好（官方文档化的注入机制）。
    要求：目标进程有消息循环（Unity 游戏满足）。返回 (True, hooks)。"""
    # 1. 只映射 DLL（不执行 DllMain、不解析导入），拿到钩子过程地址
    #    这样 DLL 不会在本进程运行，避免干扰副本
    DONT_RESOLVE_DLL_REFERENCES = 0x00000001
    hmod = kernel32.LoadLibraryExW(os.path.abspath(dll_path), None, DONT_RESOLVE_DLL_REFERENCES)
    if not hmod:
        raise OSError(f"本地映射 DLL 失败 err={ctypes.get_last_error()}")
    proc = kernel32.GetProcAddress(hmod, b"yyzyHookProc")
    if not proc:
        raise OSError("DLL 未导出 yyzyHookProc")

    # 2. 枚举目标进程全部线程
    tids = _enum_threads(pid)
    if not tids:
        raise OSError("枚举目标线程失败")

    # 3. 对每个线程挂 WH_GETMESSAGE 钩子并触发消息
    WH_GETMESSAGE = 3
    hooks = []
    for tid in tids:
        h = user32.SetWindowsHookExW(WH_GETMESSAGE, proc, hmod, tid)
        if h:
            hooks.append(h)
        user32.PostThreadMessageW(tid, 0x0000, 0, 0)  # WM_NULL 触发
    return len(hooks) > 0, hooks


def inject_remote_loadlibrary(pid, dll_path):
    """远程 LoadLibraryW 注入（SetWindowsHookEx 的替代方案）。

    背景：SetWindowsHookEx 会被火绒等安全软件拦截（错误 5/126），
    而 OpenProcess + 远程 LoadLibraryW 通常不被拦（本机实测可成功）。
    返回 (True, dll_path)。
    """
    stage = os.path.abspath(dll_path)
    h = kernel32.OpenProcess(0x1F0FFF, False, pid)     # PROCESS_ALL
    if not h:
        return False, stage
    try:
        data = (stage + "\x00").encode("utf-16-le")
        size = len(data)
        mem = kernel32.VirtualAllocEx(h, None, size, 0x3000, 0x04)   # MEM_COMMIT|MEM_RESERVE, RW
        if not mem:
            return False, stage
        buf = ctypes.create_string_buffer(data)
        written = ctypes.c_size_t()
        if not kernel32.WriteProcessMemory(h, mem, buf, size, ctypes.byref(written)):
            return False, stage
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetModuleHandleW.restype = wt.HMODULE
        k32.GetProcAddress.restype = ctypes.c_void_p
        k32.GetProcAddress.argtypes = [wt.HMODULE, ctypes.c_char_p]
        k32.CreateRemoteThread.restype = wt.HANDLE
        k32.CreateRemoteThread.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t,
                                          ctypes.c_void_p, ctypes.c_size_t, wt.DWORD,
                                          ctypes.POINTER(wt.DWORD)]
        k32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
        # 系统 DLL 在所有进程同一地址，直接用本进程算出的地址
        loadlib = k32.GetProcAddress(k32.GetModuleHandleW("kernel32.dll"), b"LoadLibraryW")
        th = k32.CreateRemoteThread(h, None, 0, loadlib, mem, 0, None)
        if not th:
            return False, stage
        k32.WaitForSingleObject(th, 8000)
        k32.CloseHandle(th)
        return True, stage
    finally:
        kernel32.CloseHandle(h)


def _enum_threads(pid):
    TH32CS_SNAPTHREAD = 0x00000004

    class THREADENTRY32(ctypes.Structure):
        _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD),
                    ("th32ThreadID", wt.DWORD), ("th32OwnerProcessID", wt.DWORD),
                    ("tpBasePri", ctypes.c_long), ("tpDeltaPri", ctypes.c_long),
                    ("dwFlags", wt.DWORD)]
    h = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    if not h or h == 0xFFFFFFFFFFFFFFFF:
        return []
    tids = []
    entry = THREADENTRY32()
    entry.dwSize = ctypes.sizeof(THREADENTRY32)
    try:
        if kernel32.Thread32First(h, ctypes.byref(entry)):
            while True:
                if entry.th32OwnerProcessID == pid:
                    tids.append(int(entry.th32ThreadID))
                if not kernel32.Thread32Next(h, ctypes.byref(entry)):
                    break
    finally:
        kernel32.CloseHandle(h)
    return tids


def inject(pid, dll_path, stage=True):
    """CreateRemoteThread + LoadLibraryW 注入。
    stage=True 时先把 DLL 暂存到 %TEMP%（ASCII 长名路径）再注入。"""
    # ---- 暂存到 %TEMP%（规避远程加载中文路径的兼容问题） ----
    if stage:
        import shutil
        temp_dir = os.path.join(os.environ.get("TEMP", r"C:\Temp"), "yyzyhook_stage")
        os.makedirs(temp_dir, exist_ok=True)
        inject_path = os.path.join(temp_dir, "yyzyhook.dll")
        src = os.path.abspath(dll_path)
        need_copy = True
        if os.path.exists(inject_path):
            try:
                if os.path.getsize(inject_path) == os.path.getsize(src) and \
                   os.path.getmtime(inject_path) >= os.path.getmtime(src):
                    need_copy = False
            except OSError:
                pass
        if need_copy:
            shutil.copy2(src, inject_path)
        if not os.path.exists(inject_path):
            raise OSError("无法暂存 DLL 到 TEMP")
    else:
        inject_path = os.path.abspath(dll_path)

    h_proc = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
    if not h_proc:
        raise OSError(f"OpenProcess({pid}) 失败, err={ctypes.get_last_error()}")
    try:
        path_b = inject_path.encode("utf-16-le")
        size = len(path_b) + 2
        remote = kernel32.VirtualAllocEx(h_proc, None, size, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE)
        if not remote:
            raise OSError(f"VirtualAllocEx 失败, err={ctypes.get_last_error()}")
        written = ctypes.c_size_t(0)
        ok = kernel32.WriteProcessMemory(h_proc, remote, path_b, size, ctypes.byref(written))
        if not ok or written.value != size:
            raise OSError(f"WriteProcessMemory 失败, err={ctypes.get_last_error()}, written={written.value}")
        loadlib = kernel32.GetProcAddress(kernel32.GetModuleHandleW("kernel32.dll"), b"LoadLibraryW")
        if not loadlib:
            raise OSError("GetProcAddress(LoadLibraryW) 失败")
        thread_id = wt.DWORD(0)
        h_thread = kernel32.CreateRemoteThread(h_proc, None, 0, loadlib, remote, 0, ctypes.byref(thread_id))
        if not h_thread:
            raise OSError(f"CreateRemoteThread 失败, err={ctypes.get_last_error()}")
        wait_r = kernel32.WaitForSingleObject(h_thread, 10000)
        exit_code = wt.DWORD(0)
        kernel32.GetExitCodeThread(h_thread, ctypes.byref(exit_code))
        kernel32.CloseHandle(h_thread)
        if wait_r != 0:  # WAIT_OBJECT_0
            raise OSError(f"LoadLibraryW 未在 10s 内返回 (wait={wait_r})")
        if not exit_code.value:
            raise OSError(f"LoadLibraryW 在目标进程返回 0（DLL 加载失败）path={inject_path}")
        return True
    finally:
        kernel32.CloseHandle(h_proc)


# ---------------- 管道服务 ----------------
class PipeServer:
    def __init__(self, on_event):
        self.on_event = on_event
        self._client = None
        self._running = False
        self._send_lock = threading.Lock()

    def start(self):
        self._running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self._running = False

    def send_cmd(self, cmd):
        """向注入的 DLL 发送命令，返回是否成功。
        注意：必须 ensure_ascii=False —— 否则中文参数会被转义成 \\uXXXX 字面量，
        DLL 侧永远匹配不到（UI 对象名可能是中文）。"""
        with self._send_lock:
            if not self._client:
                return False
            data = (json.dumps(cmd, ensure_ascii=False) + "\n").encode("utf-8")
            try:
                written = wt.DWORD(0)
                ok = kernel32.WriteFile(self._client, data, len(data), ctypes.byref(written), None)
                return bool(ok)
            except Exception:
                return False

    def kill_sockets(self):
        return self.send_cmd({"cmd": "kill"})

    def kill_battle(self):
        """只断战斗连接（跳过 80/443），一条没断到则全断兜底。"""
        return self.send_cmd({"cmd": "kill_battle"})

    def _loop(self):
        while self._running:
            h = kernel32.CreateNamedPipeW(PIPE_NAME, PIPE_ACCESS_DUPLEX,
                                          PIPE_TYPE_MESSAGE | PIPE_READMODE_MESSAGE | PIPE_WAIT,
                                          1, 4096, 4096, 0, None)
            if not h or h == 0xFFFFFFFFFFFFFFFF:
                time.sleep(1)
                continue
            if not kernel32.ConnectNamedPipe(h, None):
                # 客户端可能已连上（ERROR_PIPE_CONNECTED=535）
                if ctypes.get_last_error() != 535:
                    kernel32.CloseHandle(h)
                    time.sleep(0.2)
                    continue
            self._client = h
            try:
                buf = ctypes.create_string_buffer(4096)
                while self._running:
                    # 关键修复：不能挂阻塞 ReadFile —— Windows 会串行化同一同步句柄上的 I/O，
                    # 挂起的读会让本端 WriteFile（下发命令）一直阻塞，表现为"命令发不出去"。
                    # 改用 PeekNamedPipe 轮询，有数据才读。
                    avail = wt.DWORD(0)
                    if not kernel32.PeekNamedPipe(h, None, 0, None, ctypes.byref(avail), None):
                        break
                    if avail.value == 0:
                        time.sleep(0.02)
                        continue
                    got = wt.DWORD(0)
                    ok = kernel32.ReadFile(h, buf, 4096, ctypes.byref(got), None)
                    if not ok or got.value == 0:
                        break
                    raw = buf.raw[:got.value].decode("utf-8", "replace")
                    for line in raw.splitlines():
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            self.on_event(json.loads(line))
                        except Exception:
                            # DLL 的清单类响应是裸文本行（如 "name|path"），不是 JSON：
                            # 必须原样转发，否则会被静默丢弃。
                            self.on_event({"ev": "raw", "text": line})
            finally:
                self._client = None
                kernel32.DisconnectNamedPipe(h)
                kernel32.CloseHandle(h)


VK_NAMES = {
    "F1": 0x70, "F2": 0x71, "F3": 0x72, "F4": 0x73, "F5": 0x74, "F6": 0x75,
    "F7": 0x76, "F8": 0x77, "F9": 0x78, "F10": 0x79, "F11": 0x7A, "F12": 0x7B,
    "SPACE": 0x20, "ENTER": 0x0D, "TAB": 0x09, "ESC": 0x1B, "BACKSPACE": 0x08,
}
def name_to_vk(name):
    n = str(name).upper()
    if n in VK_NAMES:
        return VK_NAMES[n]
    if len(n) == 1:
        return ord(n)
    return 0


def vk_to_name(vk):
    for name, v in VK_NAMES.items():
        if v == vk:
            return name
    if 0x30 <= vk <= 0x39:
        return chr(vk)
    if 0x41 <= vk <= 0x5A:
        return chr(vk)
    return f"VK{hex(vk)}"


def capture_key_blocking(timeout=10.0):
    """挂 WH_KEYBOARD_LL 捕获下一个按键，返回键名（超时返回空串）。"""
    WH_KEYBOARD_LL = 13
    WM_KEYDOWN = 0x0100
    WM_SYSKEYDOWN = 0x0104

    class KBDLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [("vkCode", wt.DWORD), ("scanCode", wt.DWORD), ("flags", wt.DWORD),
                    ("time", wt.DWORD), ("dwExtraInfo", ctypes.c_void_p)]

    result = {"vk": 0}
    done = threading.Event()
    HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wt.WPARAM, wt.LPARAM)

    def _proc(nCode, wParam, lParam):
        if nCode >= 0 and wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
            kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            vk = int(kb.vkCode)
            # 排除纯修饰键（Shift/Ctrl/Alt/Win）
            if vk not in (0x10, 0x11, 0x12, 0xA0, 0xA1, 0xA2, 0xA3, 0x5B, 0x5C):
                result["vk"] = vk
                done.set()
                return 1  # 吞掉这次按键
        return user32.CallNextHookEx(None, nCode, wParam, lParam)

    cb = HOOKPROC(_proc)
    holder = {}

    def runner():
        h = user32.SetWindowsHookExW(WH_KEYBOARD_LL, cb, kernel32.GetModuleHandleW(None), 0)
        holder["h"] = h
        msg = wt.MSG()
        end = time.time() + timeout
        while not done.is_set() and time.time() < end:
            while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            time.sleep(0.02)
        if h:
            user32.UnhookWindowsHookEx(h)
            holder["h"] = None

    threading.Thread(target=runner, daemon=True).start()
    done.wait(timeout + 1)
    return vk_to_name(result["vk"]) if result["vk"] else ""


# ---------------- 热键 ----------------
def is_foreground_pid(pid):
    """判断目标进程是否在前台。pid 为空表示未注入 → 不允许触发。"""
    if not pid:
        return False
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return False
    wpid = wt.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
    return wpid.value == pid

user32.GetForegroundWindow.restype = wt.HWND
user32.GetWindowThreadProcessId.restype = wt.DWORD
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]


class HotkeyManager:
    """全局热键 + 鼠标中键（低级鼠标钩子）：注册 → 回调。
    foreground_pid 非空时，仅当该进程在前台才触发。"""
    def __init__(self, hwnd, bindings, mouse_bindings=None, foreground_pid=None):
        self.hwnd = hwnd
        self.bindings = bindings  # {vkey: callback}
        self.mouse_bindings = mouse_bindings or {}  # {"MMB": callback}
        self.foreground_pid = foreground_pid
        self._ids = {}
        self._next_id = 1
        self._running = True
        self._mhook = None
        self._mhook_cb = None
        self.thread_id = 0
        self.last_register_failed = []
        self.mmb_hook_failed = False

    def _allowed(self):
        ok = is_foreground_pid(self.foreground_pid)
        if not ok:
            # 限频提示，避免"按了没反应"的困惑
            now = time.time()
            if now - getattr(self, "_last_block_log", 0) > 15:
                self._last_block_log = now
                cb = getattr(self, "on_blocked", None)
                if cb:
                    try:
                        cb()
                    except Exception:
                        pass
        return ok

    def start(self):
        threading.Thread(target=self._register_and_pump, daemon=True).start()

    def _register_and_pump(self):
        """必须在同一个线程里注册热键并抽消息。

        WM_HOTKEY 投递到"注册它的那个线程"的消息队列：
          - 用 hwnd 注册 → 投到该窗口所属线程（Tk 主线程），我们的泵收不到
          - 用 hwnd=NULL 注册 → 投到调用线程队列 ✓
        实测教训：之前在主线程注册、另起线程抽消息，热键从未触发过。
        """
        failed = []
        for key, cb in self.bindings.items():
            # key 可以是 vk（int）或 (mods, vk) 元组
            if isinstance(key, tuple):
                mods, vk = key
            else:
                mods, vk = 0, key
            hid = self._next_id
            self._next_id += 1
            ok = user32.RegisterHotKey(None, hid, mods | MOD_NOREPEAT, vk)
            if not ok:                      # 退回带窗口句柄的注册方式
                ok = user32.RegisterHotKey(self.hwnd, hid, mods | MOD_NOREPEAT, vk)
            if not ok:
                failed.append((mods, vk, ctypes.get_last_error()))
            else:
                self._ids[hid] = cb
        self.last_register_failed = failed
        try:
            self.thread_id = kernel32.GetCurrentThreadId()
        except Exception:
            self.thread_id = 0
        if "MMB" in self.mouse_bindings:
            self._install_mmb_hook()
        self._pump()

    def _install_mmb_hook(self):
        WH_MOUSE_LL = 14
        WM_MBUTTONDOWN = 0x0207

        class MSLLHOOKSTRUCT(ctypes.Structure):
            _fields_ = [("pt", wt.POINT), ("mouseData", wt.DWORD),
                        ("flags", wt.DWORD), ("time", wt.DWORD),
                        ("dwExtraInfo", ctypes.c_void_p)]

        HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wt.WPARAM, wt.LPARAM)
        self._mouse_cb = self.mouse_bindings["MMB"]

        def _proc(nCode, wParam, lParam):
            if nCode >= 0 and wParam == WM_MBUTTONDOWN:
                if self._allowed():
                    try:
                        threading.Thread(target=self._mouse_cb, daemon=True).start()
                    except Exception:
                        pass
                    return 1  # 吞掉中键事件，不让游戏收到
            return user32.CallNextHookEx(self._mhook, nCode, wParam, lParam)

        self._mhook_cb = HOOKPROC(_proc)
        self._mhook = user32.SetWindowsHookExW(
            WH_MOUSE_LL, self._mhook_cb, kernel32.GetModuleHandleW(None), 0)
        if not self._mhook:
            self.mmb_hook_failed = True

    def _pump(self):
        msg = wt.MSG()
        while self._running:
            if user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):  # PM_REMOVE
                if msg.message == WM_HOTKEY:
                    cb = self._ids.get(msg.wParam)
                    if cb and self._allowed():
                        threading.Thread(target=cb, daemon=True).start()
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            else:
                time.sleep(0.01)

    def stop(self):
        self._running = False
        for hid in self._ids:
            user32.UnregisterHotKey(self.hwnd, hid)
        self._ids = {}
        if self._mhook:
            user32.UnhookWindowsHookEx(self._mhook)
            self._mhook = None

    def rebind(self, bindings, mouse_bindings=None):
        """换绑后重建热键。"""
        self.stop()
        self.bindings = bindings
        self.mouse_bindings = mouse_bindings or self.mouse_bindings
        self._running = True
        self._next_id = 1
        self.start()


# ---------------- 命令行模式（无 GUI 冒烟测试用） ----------------
def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default=None, help="进程名（默认游戏）")
    ap.add_argument("--inject-only", action="store_true", help="只注入然后退出")
    ap.add_argument("--test", action="store_true", help="测试模式：注入 test_net.exe，10 秒后 kill")
    args = ap.parse_args()

    events = []

    def on_event(ev):
        events.append(ev)
        print("[ev]", json.dumps(ev, ensure_ascii=False))

    srv = PipeServer(on_event)
    srv.start()
    print(f"[cli] pipe server ready, dll={DLL_PATH}")

    target = args.target or ("test_net.exe" if args.test else GAME_PROCESS)
    for _ in range(60):
        pid = find_pid(target)
        if pid:
            break
        time.sleep(0.5)
    if not pid:
        print(f"[cli] 未找到进程 {target}")
        return
    print(f"[cli] found {target} pid={pid}, injecting...")
    inject(pid, os.path.abspath(DLL_PATH))
    print("[cli] injected")

    if args.inject_only:
        return

    time.sleep(5)
    if args.test:
        print("[cli] sending kill...")
        srv.kill_sockets()
        time.sleep(5)
    else:
        # 交互：回车=kill，q=退出
        while True:
            cmd = input("[cli] 回车=秒断 kill / q=退出 > ").strip()
            if cmd == "q":
                break
            srv.kill_sockets()
    srv.stop()


if __name__ == "__main__":
    main()
