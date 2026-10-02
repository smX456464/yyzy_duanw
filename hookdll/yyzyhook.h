// yyzyhook.h - shared declarations
#pragma once
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <winsock2.h>
#include <ws2tcpip.h>
#include <stdio.h>
#include <vector>
#include <string>

// ---------- pipe ----------
#ifdef REC_BUILD
#define PIPE_NAME_W L"\\.\pipe\yyzyhook_rec"   // 录制专用管道（独立，不与生产抢）
#elif defined(DIAG_BUILD)
#define PIPE_NAME_W L"\\\\.\\pipe\\yyzyhook_diag2"
#elif defined(TEST_PIPE)
#define PIPE_NAME_W L"\\\\.\\pipe\\yyzyhook_test"
#else
#define PIPE_NAME_W L"\\\\.\\pipe\\yyzyhook_v16"   // 版本化：避免游戏里遗留的旧版 DLL 抢占管道
#endif

bool PipeStart();
void PipeStop();
void PipeSignalStop();   // DllMain 专用，无锁
void PipeStopThreads();  // 停管道线程（游戏退出前由外部调用）
void Il2CppUiShutdown();
void CloseInterceptStart();
void CloseInterceptMarkClosing();
void CloseInterceptRequestUnload(); // 请求自卸载（彻底撤出游戏进程）  // 外部确认游戏要关闭      // 在进程内拦截关闭消息（关键）
void ExitGuardStart();          // 启动退出守卫（拦 WM_CLOSE 立刻停手） // 停 il2cpp 工作线程与自动跳过线程
void PipeSendEvent(const char* json);
void PipeSendEventFmt(const char* fmt, ...);

// ---------- ws2_32 hooks ----------
bool Ws2InstallHooks();
void Ws2RemoveHooks();
void Ws2KillAllSockets();
void Ws2KillSockets(bool battleOnly);
void Ws2SetHold(int ms);      // 软断网：静默丢包 ms 毫秒（不发 RST）
bool Ws2IsHolding();
int  Ws2TrackedCount();

// ---------- stats ----------
struct TrafficStats {
    unsigned long long txBytes;
    unsigned long long rxBytes;
    int connects;
    int closes;
};
TrafficStats Ws2GetStats();

// ---------- il2cpp UI 反射层（仅游戏进程可用） ----------
bool Il2CppUiInit();
bool Il2CppUiIsReady();
int  Il2CppUiDumpButtons(std::vector<std::string>& lines, int limit);
int  Il2CppUiDumpTexts(std::vector<std::string>& lines, int limit);
bool Il2CppUiGetScreenPos(const char* name, int* outX, int* outY);
int  Il2CppUiClickNth(const char* pathContains, int index);
int  Il2CppUiDetectCountdown(std::vector<std::string>& report);
void Il2CppUiResetCountdownDetect();
std::string Il2CppUiDumpOffsets();
std::string Il2CppUiReadWatchTexts();
void Il2CppUiReadWatchTextsInto(std::string* out);

// ---------- il2cpp 调用隔离层（带超时熔断，pipe.cpp 用这些） ----------
int UiSafeInit();
void Il2CppUiSetInitStep(int step);   // 分步探测：0=全量 1=导出 2=+挂载 3=+查类
int UiSafeDumpButtons(std::vector<std::string>* out);
int UiSafeDumpTexts(std::vector<std::string>* out);
int UiSafeClickButton(const char* name, const char* path);
int UiSafeClickNth(const char* path, int index);
int UiSafeGetScreenPos(const char* name, int* x, int* y);
bool Il2CppUiGetRect(const char* name, int* x, int* y, int* w, int* h);
bool Il2CppUiNthPos(const char* goName, int index, int* outX, int* outY);
int UiSafeNthPos(const char* goName, int index, int* x, int* y);
int UiSafeProbe();
int UiSafeSnapshot(int* n);
int UiSafePhase(int* secs);
int UiSafeDetectCountdown(std::vector<std::string>* out);
int UiSafeWatchTexts(std::string* out);
int UiSafeOffsets(std::string* out);
int UiSafeGetRect(const char* name, int* x, int* y, int* w, int* h);
bool Il2CppUiReflectionBroken();
bool Il2CppUiShopActive();
bool Il2CppUiCountdownPresent();
int  Il2CppUiRoundNum();
int  Il2CppUiProbe();
int  Il2CppUiElementState();
std::string Il2CppUiFindTextByContent(const char* keywords);
int  Il2CppUiSnapshotAll(int maxItems);

// ---------- SEH 护栏（反射操作全程受保护，异常只让该命令失败） ----------
int SafeUiInit();
int SafeDumpButtons(std::vector<std::string>* lines);
int SafeDumpTexts(std::vector<std::string>* lines);
int SafeClickButton(const char* name, const char* path);
int SafeClickNth(const char* path, int index);
int SafeGetScreenPos(const char* name, int* x, int* y);
int SafePhase(int* secs);
int SafeDetectCountdown(std::vector<std::string>* report);
int SafeReadWatchTexts(std::string* out);
int SafeKillBattle();
int SafeKillAll();       // 彻底断开：关闭全部套接字
int SafeHold(int ms);          // 软断网：静默丢包 ms 毫秒
int  Il2CppUiClickButton(const char* name, const char* pathContains);
int  Il2CppUiPhase(int* secsOut);
void Il2CppUiAutoSkipSet(bool on, int atSecs);
void Il2CppUiAutoSkipCfg(int useHold, int holdMs, int fastKill);
void Il2CppUiSetBattleKeywords(const char* kw);   // 战斗开始关键字（逗号分隔）
void Il2CppUiSetWatchTexts(const char* csv);
void Il2CppUiSyntheticClick(int x, int y);
void Il2CppUiSyntheticMove(int x, int y);
void Il2CppUiSyntheticDrag(int x1, int y1, int x2, int y2);
