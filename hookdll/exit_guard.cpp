// exit_guard.cpp - 退出守卫：在游戏窗口收到 WM_CLOSE 的瞬间就停手。
//
// 实测证据（test_close_game.py 自动复现）：
//   13:30:07.827 发送 WM_CLOSE
//   13:30:09.084 Unity 错误弹窗出现（+1.26 秒）
//   退出码 0xC0000005，模块 UnityPlayer.dll
// 关键：弹窗出现时游戏主窗口仍然存在，所以"等窗口消失"永远等不到。
// 正确做法：子类化游戏窗口，拦下 WM_CLOSE/WM_DESTROY，抢在引擎开始
//         销毁之前把我们的钩子全部摘掉、线程全部停掉。
#include "yyzyhook.h"
#include <wchar.h>

static const wchar_t* kWinClass = L"UnityWndClass";
static LRESULT CALLBACK SubProc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp,
                               UINT_PTR id, DWORD_PTR ref);

// 原始窗口过程（保存在 GWLP_USERDATA 之外的全局表里）
struct GuardEntry {
    HWND hwnd;
    WNDPROC orig;
};
static GuardEntry g_guards[16] = {};
static CRITICAL_SECTION g_guardLock;
static bool g_guardLockReady = false;
static volatile bool g_armed = false;

static void LogExit(const char* step) {
    wchar_t path[MAX_PATH];
    DWORD n = GetEnvironmentVariableW(L"TEMP", path, MAX_PATH);
    if (n == 0 || n >= MAX_PATH) wcscpy_s(path, L"C:\\Temp");
    wcscat_s(path, L"\\yyzyhook_exit_guard.log");
    HANDLE h = CreateFileW(path, FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE,
                           nullptr, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (h != INVALID_HANDLE_VALUE) {
        char line[192];
        int m = sprintf_s(line, "pid=%lu %s\n", GetCurrentProcessId(), step);
        DWORD w = 0;
        WriteFile(h, line, (DWORD)m, &w, nullptr);
        CloseHandle(h);
    }
}

// 只做停手，绝不做可能阻塞的事（游戏退出路径上最危险的地方）
static void ShutdownNow(const char* why) {
    if (!g_armed) return;          // 只响应一次
    g_armed = false;
    LogExit(why);
    Il2CppUiShutdown();            // 置 g_shuttingDown：所有 il2cpp 循环立即停止
    Ws2RemoveHooks();              // 摘掉所有 ws2_32 钩子
    LogExit("hooks removed + il2cpp threads stopped");
}

static LRESULT CALLBACK RealSubProc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp) {
    WNDPROC orig = nullptr;
    EnterCriticalSection(&g_guardLock);
    for (int i = 0; i < 16; i++) {
        if (g_guards[i].hwnd == hwnd) { orig = g_guards[i].orig; break; }
    }
    LeaveCriticalSection(&g_guardLock);
    if (!orig) return DefWindowProcW(hwnd, msg, wp, lp);

    if (msg == WM_CLOSE) {
        ShutdownNow("WM_CLOSE intercepted");
    } else if (msg == WM_DESTROY) {
        ShutdownNow("WM_DESTROY intercepted");
    } else if (msg == WM_QUIT) {
        ShutdownNow("WM_QUIT intercepted");
    }
    return CallWindowProcW(orig, hwnd, msg, wp, lp);
}

// 监视线程：找到游戏主窗口并子类化
static DWORD WINAPI GuardThread(LPVOID) {
    for (int tries = 0; tries < 600 && !g_armed; tries++) {
        if (g_guardLockReady) {
            HWND target = FindWindowW(kWinClass, NULL);
            if (target && IsWindowVisible(target)) {
                WNDPROC orig = (WNDPROC)SetWindowLongPtrW(
                    target, GWLP_WNDPROC, (LONG_PTR)RealSubProc);
                if (orig) {
                    EnterCriticalSection(&g_guardLock);
                    for (int i = 0; i < 16; i++) {
                        if (!g_guards[i].hwnd) {
                            g_guards[i].hwnd = target;
                            g_guards[i].orig = orig;
                            break;
                        }
                    }
                    LeaveCriticalSection(&g_guardLock);
                    g_armed = true;
                    LogExit("game window subclassed (WM_CLOSE guard active)");
                }
            }
        }
        Sleep(200);
    }
    // 持续守护：窗口被重建时重新挂上
    while (true) {
        Sleep(500);
        if (!g_armed) {
            HWND target = FindWindowW(kWinClass, NULL);
            if (target && IsWindowVisible(target)) {
                WNDPROC orig = (WNDPROC)SetWindowLongPtrW(
                    target, GWLP_WNDPROC, (LONG_PTR)RealSubProc);
                if (orig) {
                    EnterCriticalSection(&g_guardLock);
                    for (int i = 0; i < 16; i++) {
                        if (!g_guards[i].hwnd) {
                            g_guards[i].hwnd = target;
                            g_guards[i].orig = orig;
                            break;
                        }
                    }
                    LeaveCriticalSection(&g_guardLock);
                    g_armed = true;
                    LogExit("window re-subclassed");
                }
            }
        }
    }
    return 0;
}

void ExitGuardStart() {
    if (!g_guardLockReady) {
        InitializeCriticalSection(&g_guardLock);
        g_guardLockReady = true;
    }
    CreateThread(nullptr, 0, GuardThread, nullptr, 0, nullptr);
}
