// dllmain.cpp - entry point
#include "yyzyhook.h"
#include <wchar.h>

static void LogLoad(const char* reason) {
    wchar_t path[MAX_PATH];
    DWORD n = GetEnvironmentVariableW(L"TEMP", path, MAX_PATH);
    if (n == 0 || n >= MAX_PATH) wcscpy_s(path, L"C:\\Temp");
    wcscat_s(path, L"\\yyzyhook_dllmain.log");
    HANDLE h = CreateFileW(path, FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE,
                           nullptr, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (h != INVALID_HANDLE_VALUE) {
        char line[256];
        int m = sprintf_s(line, "pid=%lu reason=%s\n", GetCurrentProcessId(), reason);
        DWORD written = 0;
        WriteFile(h, line, (DWORD)m, &written, nullptr);
        CloseHandle(h);
    }
}

static DWORD WINAPI MainThread(LPVOID) {
    Sleep(300); // let the process settle after injection
    // 重要：默认不安装 ws2_32 钩子。
    // 游戏的崩溃上报组件（CrashSight）自身也使用 MinHook；两套 MinHook 同时改写
    // 同一进程的网络函数极易互相破坏。断网默认用「彻底关闭套接字」。
    LogLoad("attached (ws2 hooks disabled by default)");
    PipeStart();
    CloseInterceptStart();   // 关键：进程内拦截关闭消息，抢在 Unity 销毁内存前停手
    // ExitGuardStart();  // 暂时停用：影响注入
    for (;;) Sleep(1000);
    return 0;
}

// 供 SetWindowsHookEx 注入使用的钩子过程（必须导出）
extern "C" __declspec(dllexport) LRESULT CALLBACK yyzyHookProc(int code, WPARAM wParam, LPARAM lParam) {
    return CallNextHookEx(nullptr, code, wParam, lParam);
}

// 收到"游戏要退出"的信号：必须让所有后台线程立刻停手。
// 现象（用户实测）：关闭游戏时游戏窗口卡顿 1~2 秒，然后一闪而过的错误弹窗。
// 事件日志实证：Faulting module: GameAssembly.dll / UnityPlayer.dll，0xc0000005。
// 原因：模块被 PIN 住 → DLL_PROCESS_DETACH 永不触发 → DLL 留在正在销毁的
//       Unity 进程里，管道线程/il2cpp 工作线程继续访问游戏正在释放的内存。
// 对策：外部进程（工具）检测到游戏退出 → 主动通知 DLL 停手（DLL 自己无法可靠
//       感知进程退出，因为 detach 根本不会发生）。
void RequestShutdown() {
    LogLoad("shutdown requested (game exiting) — stopping all threads");
    Il2CppUiShutdown();     // 停 il2cpp 工作线程 + 自动跳过线程
    PipeStopThreads();      // 停管道线程（断开、不再读写）
}

BOOL APIENTRY DllMain(HMODULE hModule, DWORD ul_reason_for_call, LPVOID lpReserved) {
    (void)hModule;
    if (ul_reason_for_call == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls((HMODULE)hModule);
        // 不再 PIN 模块：PIN 会让 detach 永不触发，导致退出时线程仍在已销毁的
        // 引擎里运行 → 访问违规。改为"可卸载 + 退出前主动停线程"。
        LogLoad("attach");
        CreateThread(nullptr, 0, MainThread, nullptr, 0, nullptr);
    } else if (ul_reason_for_call == DLL_PROCESS_DETACH) {
        // DllMain 持有 loader lock：只做无锁的最小动作，绝不 Sleep/取锁。
        LogLoad("detach (quick)");
        PipeSignalStop();
    }
    return TRUE;
}
