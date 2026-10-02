// pipe.cpp - named pipe client + command loop
#include "yyzyhook.h"
#include <stdarg.h>

#define PIPE_NAME PIPE_NAME_W   // 诊断版为 yyzyhook_diag，正式版为 yyzyhook

// ---- 探测本进程是否还有主窗口（游戏窗口）----
// 游戏窗口消失 = 用户点了关闭 → 立刻停手，不能再碰引擎。
struct WinProbe { DWORD pid; HWND found; };

static BOOL CALLBACK WinProbeCb(HWND h, LPARAM lp) {
    WinProbe* c = (WinProbe*)lp;
    DWORD wpid = 0;
    GetWindowThreadProcessId(h, &wpid);
    if (wpid != c->pid) return TRUE;
    if (!IsWindowVisible(h)) return TRUE;
    RECT r;
    if (!GetWindowRect(h, &r)) return TRUE;
    int w = r.right - r.left, ht = r.bottom - r.top;
    if (w > 200 && ht > 200) { c->found = h; return FALSE; }
    return TRUE;
}

static bool GameMainWindowAlive() {
    WinProbe c;
    c.pid = GetCurrentProcessId();
    c.found = nullptr;
    EnumWindows(WinProbeCb, (LPARAM)&c);
    return c.found != nullptr;
}
static volatile HANDLE g_pipe = INVALID_HANDLE_VALUE;
static HANDLE g_stopEvent = nullptr;
static SRWLOCK g_writeLock = SRWLOCK_INIT;
static bool g_il2cppReady = false;

// 诊断：管道线程逐步日志（排查连接失败）
static void PipeLog(const char* step) {
    wchar_t path[MAX_PATH];
    DWORD n = GetEnvironmentVariableW(L"TEMP", path, MAX_PATH);
    if (n == 0 || n >= MAX_PATH) wcscpy_s(path, L"C:\\Temp");
    wcscat_s(path, L"\\yyzyhook_pipe.log");
    HANDLE h = CreateFileW(path, FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE,
                           nullptr, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (h != INVALID_HANDLE_VALUE) {
        char line[300];
        int m = sprintf_s(line, "pid=%lu %s (err=%lu)\n", GetCurrentProcessId(), step, GetLastError());
        DWORD written = 0;
        WriteFile(h, line, (DWORD)m, &written, nullptr);
        CloseHandle(h);
    }
}

static bool SendRaw(const char* data, size_t n) {
    AcquireSRWLockShared(&g_writeLock);
    bool ok = false;
    if (g_pipe != INVALID_HANDLE_VALUE) {
        DWORD written = 0;
        ok = WriteFile(g_pipe, data, (DWORD)n, &written, nullptr) && written == n;
    }
    ReleaseSRWLockShared(&g_writeLock);
    return ok;
}

void PipeSendEventFmt(const char* fmt, ...) {
    char buf[1024];
    va_list ap;
    va_start(ap, fmt);
    int n = vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    if (n <= 0) return;
    if (n >= (int)sizeof(buf)) n = (int)sizeof(buf) - 1;
    buf[n++] = '\n';
    SendRaw(buf, (size_t)n);
}

void PipeSendEvent(const char* json) {
    char buf[1024];
    int n = snprintf(buf, sizeof(buf), "%s\n", json);
    if (n > 0) SendRaw(buf, (size_t)n);
}

// 诊断：把收到的原始命令与解析结果写文件（排查命令解析问题用）
static void LogCmd(const char* raw, const char* name, const char* arg1) {
    wchar_t path[MAX_PATH];
    DWORD n = GetEnvironmentVariableW(L"TEMP", path, MAX_PATH);
    if (n == 0 || n >= MAX_PATH) wcscpy_s(path, L"C:\\Temp");
    wcscat_s(path, L"\\yyzyhook_cmds.log");
    HANDLE h = CreateFileW(path, FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE,
                           nullptr, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (h != INVALID_HANDLE_VALUE) {
        char line[512];
        int m = sprintf_s(line, "raw=[%s] name=[%s] arg1=[%s]\n", raw, name, arg1);
        DWORD written = 0;
        WriteFile(h, line, (DWORD)m, &written, nullptr);
        CloseHandle(h);
    }
}

static void HandleCommand(const char* cmd) {
    // 提取命令名：兼容 JSON {"cmd": "xxx|arg1|arg2"} 与裸名；命令名在 '|' 处截断
    char name[64] = "";
    const char* p = strstr(cmd, "\"cmd\"");
    if (p && (p = strchr(p, ':')) != nullptr) {
        p++;
        while (*p == ' ' || *p == '"') p++;
        int i = 0;
        while (*p && *p != '"' && *p != ' ' && *p != '|' && *p != '\n' && i < 63) name[i++] = *p++;
        name[i] = 0;
    }
    if (!name[0]) {
        int i = 0;
        while (cmd[i] && cmd[i] != '|' && i < 63) { name[i] = cmd[i]; i++; }
        name[i] = 0;
    }

    // 参数：cmd 后跟 |arg1|arg2...；JSON 形式需先截掉结尾的 " 与 }
    char arg1[128] = "", arg2[128] = "", arg3[128] = "", arg4[128] = "";
    const char* bar = strchr(cmd, '|');
    if (bar) {
        char tmp[512];
        strncpy_s(tmp, bar + 1, sizeof(tmp) - 1);
        char* q = strchr(tmp, '"');   // JSON 值结束引号
        char* br = strchr(tmp, '}');  // JSON 对象结束
        char* endp = nullptr;
        if (q && (!br || q < br)) endp = q;
        else if (br) endp = br;
        if (endp) *endp = 0;
        sscanf_s(tmp, "%127[^|]|%127[^|]|%127[^|]|%127s", arg1, 128, arg2, 128, arg3, 128, arg4, 128);
    }

    if (strstr(cmd, "dbg_echo")) {
        LogCmd(cmd, name, arg1);
        PipeSendEventFmt("{\"ev\":\"dbg\",\"name\":\"%s\",\"arg1\":\"%s\"}", name, arg1);
        return;
    }
    // 记录所有命令（便于事后追查"谁在什么时候下发了什么"）
    LogCmd(cmd, name, arg1);

    if (!strcmp(name, "ping")) {
        PipeSendEventFmt("{\"ev\":\"pong\",\"sockets\":%d}", Ws2TrackedCount());
    } else if (!strcmp(name, "kill")) {
        Ws2KillAllSockets();
    } else if (!strcmp(name, "init_step")) {
        // 分步初始化探测：init_step|1..4（每步独立超时；一旦卡住立即熔断，不会连锁）
        int step = arg1[0] ? atoi(arg1) : 1;
        Il2CppUiSetInitStep(step > 3 ? 0 : step);
        int r = UiSafeInit();
        PipeSendEventFmt("{\"ev\":\"init_step\",\"step\":%d,\"result\":%d,\"broken\":%s}", step, r, Il2CppUiReflectionBroken() ? "true" : "false");
    } else if (!strcmp(name, "hooks_on")) {
        bool ok = Ws2InstallHooks();
        PipeSendEventFmt("{\"ev\":\"hooks_state\",\"on\":%s}", ok ? "true" : "false");
    } else if (!strcmp(name, "hooks_off")) {
        Ws2RemoveHooks();
        PipeSendEvent("{\"ev\":\"hooks_state\",\"on\":false}");
    } else if (!strcmp(name, "hold")) {
        // 软断网：静默丢包（默认 3000ms），对游戏更温和，不发 RST
        int ms = arg1[0] ? atoi(arg1) : 3000;
        if (ms < 100) ms = 100;
        if (ms > 60000) ms = 60000;
        Ws2SetHold(ms);
        PipeSendEventFmt("{\"ev\":\"hold_start\",\"ms\":%d}", ms);
    } else if (!strcmp(name, "hold_off")) {
        Ws2SetHold(0);
        PipeSendEvent("{\"ev\":\"hold_end\"}");
    } else if (!strcmp(name, "kill_all")) {
        // 彻底断开：关闭全部套接字（用户要求"内部断网、断得彻底"）
        SafeKillAll();
        PipeSendEventFmt("{\"ev\":\"kill\",\"n\":%d,\"mode\":\"all\"}", Ws2TrackedCount());
    } else if (!strcmp(name, "kill_battle")) {
        SafeKillBattle();
    } else if (!strcmp(name, "status")) {
        TrafficStats st = Ws2GetStats();
        PipeSendEventFmt("{\"ev\":\"status\",\"sockets\":%d,\"tx\":%llu,\"rx\":%llu}",
            Ws2TrackedCount(), st.txBytes, st.rxBytes);
    } else if (!strcmp(name, "dump_ui")) {
        if (!g_il2cppReady) {
            g_il2cppReady = (UiSafeInit() > 0);
            if (!g_il2cppReady) { PipeSendEvent("{\"ev\":\"ui_error\",\"msg\":\"no il2cpp\"}"); return; }
        }
        std::vector<std::string> lines;
        int n = UiSafeDumpButtons(&lines);
        for (auto& l : lines) PipeSendEvent(l.c_str());
        PipeSendEventFmt("{\"ev\":\"ui_dump_done\",\"n\":%d}", n);
    } else if (!strcmp(name, "dump_texts")) {
        if (!g_il2cppReady) g_il2cppReady = (UiSafeInit() > 0);
        if (!g_il2cppReady) { PipeSendEvent("{\"ev\":\"ui_error\",\"msg\":\"no il2cpp\"}"); return; }
        std::vector<std::string> lines;
        int n = UiSafeDumpTexts(&lines);
        for (auto& l : lines) PipeSendEvent(l.c_str());
        PipeSendEventFmt("{\"ev\":\"ui_text_done\",\"n\":%d}", n);
    } else if (!strcmp(name, "snapshot")) {
        if (!g_il2cppReady) g_il2cppReady = (UiSafeInit() > 0);
        if (!g_il2cppReady) { PipeSendEvent("{\"ev\":\"ui_error\",\"msg\":\"no il2cpp\"}"); return; }
        int n = 0;
        UiSafeSnapshot(&n);
        PipeSendEventFmt("{\"ev\":\"snapshot_done\",\"n\":%d}", n);
    } else if (!strcmp(name, "probe")) {
        if (!g_il2cppReady) g_il2cppReady = (UiSafeInit() > 0);
        if (!g_il2cppReady) { PipeSendEvent("{\"ev\":\"ui_error\",\"msg\":\"no il2cpp\"}"); return; }
        UiSafeProbe();
    } else if (!strcmp(name, "ui_nth_pos")) {
        if (!g_il2cppReady) g_il2cppReady = (UiSafeInit() > 0);
        if (!g_il2cppReady) { PipeSendEvent("{\"ev\":\"ui_error\",\"msg\":\"no il2cpp\"}"); return; }
        int idx = arg2[0] ? atoi(arg2) : 0;
        int x = 0, y = 0;
        bool ok = (UiSafeNthPos(arg1, idx, &x, &y) == 1);
        PipeSendEventFmt("{\"ev\":\"ui_pos\",\"name\":\"%s\",\"ok\":%s,\"x\":%d,\"y\":%d}",
                         arg1, ok ? "true" : "false", x, y);
    } else if (!strcmp(name, "ui_rect")) {
        if (!g_il2cppReady) g_il2cppReady = (UiSafeInit() > 0);
        if (!g_il2cppReady) { PipeSendEvent("{\"ev\":\"ui_error\",\"msg\":\"no il2cpp\"}"); return; }
        int x = 0, y = 0, w = 0, h = 0;
        bool ok = false;
        ok = (UiSafeGetRect(arg1, &x, &y, &w, &h) == 1);
        PipeSendEventFmt("{\"ev\":\"ui_rect\",\"name\":\"%s\",\"ok\":%s,\"x\":%d,\"y\":%d,\"w\":%d,\"h\":%d}",
                         arg1, ok ? "true" : "false", x, y, w, h);
    } else if (!strcmp(name, "ui_pos")) {
        if (!g_il2cppReady) g_il2cppReady = (UiSafeInit() > 0);
        if (!g_il2cppReady) { PipeSendEvent("{\"ev\":\"ui_error\",\"msg\":\"no il2cpp\"}"); return; }
        int x = 0, y = 0;
        bool ok = (UiSafeGetScreenPos(arg1, &x, &y) == 1);
        PipeSendEventFmt("{\"ev\":\"ui_pos\",\"name\":\"%s\",\"ok\":%s,\"x\":%d,\"y\":%d}",
                         arg1, ok ? "true" : "false", x, y);
    } else if (!strcmp(name, "click_nth")) {
        if (!g_il2cppReady) g_il2cppReady = (UiSafeInit() > 0);
        if (!g_il2cppReady) { PipeSendEvent("{\"ev\":\"ui_error\",\"msg\":\"no il2cpp\"}"); return; }
        int idx = arg2[0] ? atoi(arg2) : 0;
        int r = UiSafeClickNth(arg1, idx);
        PipeSendEventFmt("{\"ev\":\"ui_click_nth\",\"path\":\"%s\",\"index\":%d,\"result\":%d}",
                         arg1, idx, r);
    } else if (!strcmp(name, "detect_countdown")) {
        if (!g_il2cppReady) g_il2cppReady = (UiSafeInit() > 0);
        if (!g_il2cppReady) { PipeSendEvent("{\"ev\":\"ui_error\",\"msg\":\"no il2cpp\"}"); return; }
        std::vector<std::string> report;
        int r = UiSafeDetectCountdown(&report);
        for (auto& l : report) PipeSendEvent(l.c_str());
        PipeSendEventFmt("{\"ev\":\"cd_stage\",\"stage\":%d}", r);
    } else if (!strcmp(name, "dump_offsets")) {
        if (!g_il2cppReady) g_il2cppReady = (UiSafeInit() > 0);
        if (!g_il2cppReady) { PipeSendEvent("{\"ev\":\"ui_error\",\"msg\":\"no il2cpp\"}"); return; }
        std::string s; if (UiSafeOffsets(&s) < 0) { PipeSendEvent("{\"ev\":\"ui_error\",\"msg\":\"reflection_timeout\"}"); return; }
        PipeSendEvent(s.c_str());
    } else if (!strcmp(name, "click_btn")) {
        if (!g_il2cppReady) g_il2cppReady = (UiSafeInit() > 0);
        if (!g_il2cppReady) { PipeSendEvent("{\"ev\":\"ui_error\",\"msg\":\"no il2cpp\"}"); return; }
        int r = UiSafeClickButton(arg1, arg2);
        PipeSendEventFmt("{\"ev\":\"ui_click\",\"name\":\"%s\",\"result\":%d}", arg1, r);
    } else if (!strcmp(name, "click_xy")) {
        int x = atoi(arg1), y = atoi(arg2);
        Il2CppUiSyntheticClick(x, y);
        PipeSendEventFmt("{\"ev\":\"ui_click_xy\",\"x\":%d,\"y\":%d}", x, y);
    } else if (!strcmp(name, "move_xy")) {
        int x = atoi(arg1), y = atoi(arg2);
        Il2CppUiSyntheticMove(x, y);
        PipeSendEventFmt("{\"ev\":\"ui_move\",\"x\":%d,\"y\":%d}", x, y);
    } else if (!strcmp(name, "drag")) {
        int x1 = atoi(arg1), y1 = atoi(arg2), x2 = atoi(arg3), y2 = atoi(arg4);
        Il2CppUiSyntheticDrag(x1, y1, x2, y2);
        PipeSendEventFmt("{\"ev\":\"ui_drag\",\"from\":\"%d,%d\",\"to\":\"%d,%d\"}", x1, y1, x2, y2);
    } else if (!strcmp(name, "auto_on")) {
        if (!g_il2cppReady) g_il2cppReady = (UiSafeInit() > 0);
        if (!g_il2cppReady) { PipeSendEvent("{\"ev\":\"ui_error\",\"msg\":\"no il2cpp\"}"); return; }
        int at = arg1[0] ? atoi(arg1) : 0;
        Il2CppUiAutoSkipSet(true, at);
        PipeSendEventFmt("{\"ev\":\"auto_skip_state\",\"on\":true,\"at\":%d}", at);
    } else if (!strcmp(name, "auto_cfg")) {
        int useHold = arg1[0] ? atoi(arg1) : 0;
        int ms = arg2[0] ? atoi(arg2) : 0;
        int fast = arg3[0] ? atoi(arg3) : 1;      // 1=彻底断开（关闭全部套接字）
        Il2CppUiAutoSkipCfg(useHold, ms, fast);
        PipeSendEventFmt("{\"ev\":\"auto_cfg_state\",\"hold\":%d,\"ms\":%d,\"fast\":%d}", useHold, ms, fast);
    } else if (!strcmp(name, "shutdown")) {
        // 游戏退出前由外部进程通知：立刻停手，不再触碰引擎与管道
        Il2CppUiShutdown();
        Ws2RemoveHooks();
        PipeSignalStop();
        PipeSendEvent("{\"ev\":\"shutdown_ack\"}");
    } else if (!strcmp(name, "battle_kw")) {
        Il2CppUiSetBattleKeywords(arg1);
        PipeSendEventFmt("{\"ev\":\"battle_kw_state\",\"kw\":\"%s\"}", arg1);
    } else if (!strcmp(name, "auto_off")) {
        Il2CppUiAutoSkipSet(false, 0);
        PipeSendEvent("{\"ev\":\"auto_skip_state\",\"on\":false,\"at\":0}");
    } else if (!strcmp(name, "watch_texts")) {
        Il2CppUiSetWatchTexts(arg1);
        PipeSendEventFmt("{\"ev\":\"watch_texts_state\",\"names\":\"%s\"}", arg1);
    } else if (!strcmp(name, "phase")) {
        if (!g_il2cppReady) g_il2cppReady = (UiSafeInit() > 0);
        if (!g_il2cppReady) { PipeSendEvent("{\"ev\":\"ui_error\",\"msg\":\"no il2cpp\"}"); return; }
        int secs = -1;
        int ph = UiSafePhase(&secs);
        PipeSendEventFmt("{\"ev\":\"phase\",\"phase\":%d,\"secs\":%d}", ph, secs);
    }
}

static HANDLE ConnectPipe() {
    for (int i = 0; i < 60; i++) {
        HANDLE h = CreateFileW(PIPE_NAME, GENERIC_READ | GENERIC_WRITE,
            0, nullptr, OPEN_EXISTING, 0, nullptr);
        if (h != INVALID_HANDLE_VALUE) {
            if (i > 0) PipeLog("connected after retry");
            return h;
        }
        if (i == 0) PipeLog("CreateFileW failed (will retry)");
        if (WaitForSingleObject(g_stopEvent, 500) == WAIT_OBJECT_0) return nullptr;
    }
    PipeLog("all retries exhausted");
    return nullptr;
}

static DWORD WINAPI PipeThread(LPVOID) {
    PipeLog("pipe thread started");
    for (;;) {
        if (WaitForSingleObject(g_stopEvent, 0) == WAIT_OBJECT_0) break;
        HANDLE h = ConnectPipe();
        if (!h) break;
        PipeLog("pipe connected");
        // 注意：这里绝不能获取写锁 —— 若某个写入方卡在 WriteFile 上持有该锁，
        // 管道线程就会永久阻塞（实测踩过：卡在此处导致读循环根本没启动）。
        // 指针赋值本身是原子的，直接写即可。
        g_pipe = h;

        /* PIPE_NOWAIT：事件写入不阻塞，避免与服务端命令写入形成双端阻塞死锁 */
        DWORD mode = PIPE_READMODE_MESSAGE | PIPE_NOWAIT;
        BOOL smode = SetNamedPipeHandleState(h, &mode, nullptr, nullptr);
        {
            char b[120];
            sprintf_s(b, "setmode ok=%d err=%lu", (int)smode, GetLastError());
            PipeLog(b);
        }

        char hello[128];
        int n = snprintf(hello, sizeof(hello), "{\"ev\":\"hello\",\"pid\":%lu,\"ver\":\"v15\"}\n", GetCurrentProcessId());
        SendRaw(hello, (size_t)n);

        char buf[256];
        int idle = 0;
        for (;;) {
            if (WaitForSingleObject(g_stopEvent, 0) == WAIT_OBJECT_0) break;
            DWORD got = 0;
            // 先用 PeekNamedPipe 窥探：有数据才 ReadFile（避免 NOWAIT 组合下的怪行为）
            DWORD avail = 0;
            BOOL peeked = PeekNamedPipe(h, nullptr, 0, nullptr, &avail, nullptr);
            if (!peeked) {
                char b[96];
                sprintf_s(b, "peek failed err=%lu", GetLastError());
                PipeLog(b);
                break;
            }
            if (avail == 0) {
                // ---- 兜底：窗口探测（每次空闲都查，间隔约 20ms）----
                // 实测：游戏崩溃发生在点关闭后 ~1.3 秒，之前的 1.6 秒周期太慢会漏掉。
                if (!GameMainWindowAlive()) {
                    PipeLog("game window gone -> shutdown (fallback)");
                    Il2CppUiShutdown();
                    Ws2RemoveHooks();
                    PipeLog("stopped all hooks and il2cpp threads");
                    break;
                }
                if (++idle % 40 == 0) {
                    char b[96];
                    sprintf_s(b, "idle heartbeat avail=0 err=%lu", GetLastError());
                    PipeLog(b);
                }
                Sleep(20);
                continue;
            }
            {
                char b[96];
                sprintf_s(b, "peek avail=%lu", avail);
                PipeLog(b);
            }
            BOOL ok = ReadFile(h, buf, sizeof(buf) - 1, &got, nullptr);
            if (!ok) {
                DWORD err = GetLastError();
                char b[96];
                sprintf_s(b, "read failed err=%lu", err);
                PipeLog(b);
                if (err == ERROR_MORE_DATA) { Sleep(20); continue; }
                break;
            }
            if (got == 0) { Sleep(50); continue; }
            idle = 0;
            PipeLog("cmd received");   // 命令确实被读到（区别于"读到但回不去"）
            buf[got] = 0;
            char* p = buf;
            while (*p) {
                char* nl = strchr(p, '\n');
                if (nl) *nl = 0;
                HandleCommand(p);
                if (!nl) break;
                p = nl + 1;
            }
        }
        // 关闭路径也用非阻塞方式，避免被写入方拖死
        if (TryAcquireSRWLockExclusive(&g_writeLock)) {
            g_pipe = INVALID_HANDLE_VALUE;
            ReleaseSRWLockExclusive(&g_writeLock);
        } else {
            g_pipe = INVALID_HANDLE_VALUE;   // 原子赋值，够用
        }
        CloseHandle(h);
    }
    return 0;
}

bool PipeStart() {
    g_stopEvent = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    if (!g_stopEvent) return false;
    CreateThread(nullptr, 0, PipeThread, nullptr, 0, nullptr);
    return true;
}

// DllMain 专用：只置停止事件并原子清空管道句柄，绝不取锁（避免 loader lock 死锁）
void PipeSignalStop() {
    if (g_stopEvent) SetEvent(g_stopEvent);
    g_pipe = INVALID_HANDLE_VALUE;
}

// 游戏退出前调用：停管道线程并断开连接，避免线程在引擎销毁期间继续活动
void PipeStopThreads() {
    if (g_stopEvent) SetEvent(g_stopEvent);
    HANDLE h = g_pipe;
    g_pipe = INVALID_HANDLE_VALUE;
    if (h != INVALID_HANDLE_VALUE) {
        CancelIo(h);                    // 取消任何阻塞中的 I/O
        DisconnectNamedPipe(h);
        CloseHandle(h);
    }
}

void PipeStop() {
    if (g_stopEvent) SetEvent(g_stopEvent);
    AcquireSRWLockExclusive(&g_writeLock);
    if (g_pipe != INVALID_HANDLE_VALUE) {
        CloseHandle(g_pipe);
        g_pipe = INVALID_HANDLE_VALUE;
    }
    ReleaseSRWLockExclusive(&g_writeLock);
}
