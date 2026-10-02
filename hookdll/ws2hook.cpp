// ws2hook.cpp - ws2_32 hooks: track sockets, provide instant kill
#include "yyzyhook.h"
#include "MinHook.h"
#include <string.h>
#include <algorithm>
#pragma comment(lib, "ws2_32.lib")

static int (WSAAPI* TrueConnect)(SOCKET, const sockaddr*, int) = nullptr;
static int (WSAAPI* TrueSend)(SOCKET, const char*, int, int) = nullptr;
static int (WSAAPI* TrueRecv)(SOCKET, char*, int, int) = nullptr;
static int (WSAAPI* TrueCloseSocket)(SOCKET) = nullptr;
static int (WSAAPI* TrueShutdown)(SOCKET, int) = nullptr;

struct TrackedSocket {
    SOCKET s;
    sockaddr_in addr;
};
static std::vector<TrackedSocket> g_sockets;
static SRWLOCK g_lock = SRWLOCK_INIT;
static TrafficStats g_stats = {};

static DWORD g_lastFlush = 0;

// ---- 软断网（静默丢包）状态 ----
static volatile LONG g_holdUntil = 0;   // GetTickCount 基准的时刻
static volatile LONG g_holdActive = 0;

void Ws2SetHold(int ms) {
    if (ms <= 0) {
        g_holdActive = 0;
        g_holdUntil = 0;
    } else {
        g_holdUntil = (LONG)GetTickCount() + ms;
        g_holdActive = 1;
    }
}

bool Ws2IsHolding() {
    if (!g_holdActive) return false;
    if ((LONG)GetTickCount() - g_holdUntil >= 0) {
        g_holdActive = 0;   // 窗口结束
        PipeSendEvent("{\"ev\":\"hold_end\"}");
        return false;
    }
    return true;
}

static bool Holding() { return Ws2IsHolding(); }

static void AddSocket(SOCKET s, const sockaddr_in& a) {
    AcquireSRWLockExclusive(&g_lock);
    for (auto& t : g_sockets) if (t.s == s) { ReleaseSRWLockExclusive(&g_lock); return; }
    g_sockets.push_back({ s, a });
    ReleaseSRWLockExclusive(&g_lock);
}

static bool FindAndErase(SOCKET s, sockaddr_in* out) {
    AcquireSRWLockExclusive(&g_lock);
    for (size_t i = 0; i < g_sockets.size(); i++) {
        if (g_sockets[i].s == s) {
            if (out) *out = g_sockets[i].addr;
            g_sockets.erase(g_sockets.begin() + i);
            ReleaseSRWLockExclusive(&g_lock);
            return true;
        }
    }
    ReleaseSRWLockExclusive(&g_lock);
    return false;
}

static void TrackIfUnknown(SOCKET s) {
    sockaddr_in a{};
    int alen = sizeof(a);
    if (getpeername(s, (sockaddr*)&a, &alen) == 0 && a.sin_family == AF_INET) {
        AddSocket(s, a);
    }
}

static void FlushStats(bool force) {
    DWORD now = GetTickCount();
    if (!force && now - g_lastFlush < 500) return;
    g_lastFlush = now;
    if (g_stats.txBytes || g_stats.rxBytes) {
        PipeSendEventFmt("{\"ev\":\"traffic\",\"pid\":%lu,\"tx\":%llu,\"rx\":%llu}",
            GetCurrentProcessId(), g_stats.txBytes, g_stats.rxBytes);
        g_stats.txBytes = 0;
        g_stats.rxBytes = 0;
    }
}

static int WSAAPI HookConnect(SOCKET s, const sockaddr* name, int namelen) {
    int r = TrueConnect(s, name, namelen);
    if (r == 0 && name && name->sa_family == AF_INET) {
        sockaddr_in a{};
        memcpy(&a, name, std::min(namelen, (int)sizeof(a)));
        AddSocket(s, a);
        char ip[64] = "?";
        inet_ntop(AF_INET, &a.sin_addr, ip, sizeof(ip));
        PipeSendEventFmt("{\"ev\":\"connect\",\"pid\":%lu,\"s\":%llu,\"ip\":\"%s\",\"port\":%d}",
            GetCurrentProcessId(), (unsigned long long)s, ip, ntohs(a.sin_port));
        g_stats.connects++;
    }
    return r;
}

static int WSAAPI HookSend(SOCKET s, const char* buf, int len, int flags) {
    if (Holding()) {
        // 软断网：假装发送成功，实际丢弃（服务器看到"客户端沉默"，但不发 RST）
        g_stats.txBytes += (unsigned long long)(len > 0 ? len : 0);
        FlushStats(false);
        return len > 0 ? len : 0;
    }
    TrackIfUnknown(s);
    int r = TrueSend(s, buf, len, flags);
    if (r > 0) g_stats.txBytes += (unsigned long long)r;
    FlushStats(false);
    return r;
}

static int WSAAPI HookRecv(SOCKET s, char* buf, int len, int flags) {
    if (Holding()) {
        // 软断网：报告"暂时无数据"，不返回 0（那会被当成连接关闭）
        Sleep(15);
        WSASetLastError(WSAEWOULDBLOCK);
        return SOCKET_ERROR;
    }
    TrackIfUnknown(s);
    int r = TrueRecv(s, buf, len, flags);
    if (r > 0) g_stats.rxBytes += (unsigned long long)r;
    FlushStats(false);
    return r;
}

static int WSAAPI HookCloseSocket(SOCKET s) {
    sockaddr_in a{};
    bool wasTracked = FindAndErase(s, &a);
    int r = TrueCloseSocket(s);
    if (wasTracked) {
        char ip[64] = "?";
        inet_ntop(AF_INET, &a.sin_addr, ip, sizeof(ip));
        PipeSendEventFmt("{\"ev\":\"closed\",\"pid\":%lu,\"s\":%llu,\"ip\":\"%s\",\"port\":%d}",
            GetCurrentProcessId(), (unsigned long long)s, ip, ntohs(a.sin_port));
        g_stats.closes++;
    }
    return r;
}

static int WSAAPI HookShutdown(SOCKET s, int how) {
    sockaddr_in a{};
    AcquireSRWLockShared(&g_lock);
    bool tracked = false;
    for (auto& t : g_sockets) if (t.s == s) { tracked = true; a = t.addr; break; }
    ReleaseSRWLockShared(&g_lock);
    int r = TrueShutdown(s, how);
    if (tracked) {
        char ip[64] = "?";
        inet_ntop(AF_INET, &a.sin_addr, ip, sizeof(ip));
        PipeSendEventFmt("{\"ev\":\"shutdown\",\"pid\":%lu,\"s\":%llu,\"ip\":\"%s\",\"port\":%d,\"how\":%d}",
            GetCurrentProcessId(), (unsigned long long)s, ip, ntohs(a.sin_port), how);
    }
    return r;
}

bool Ws2InstallHooks() {
    if (MH_Initialize() != MH_OK) return false;
    MH_CreateHookApi(L"ws2_32.dll", "connect", &HookConnect, (void**)&TrueConnect);
    MH_CreateHookApi(L"ws2_32.dll", "send", &HookSend, (void**)&TrueSend);
    MH_CreateHookApi(L"ws2_32.dll", "recv", &HookRecv, (void**)&TrueRecv);
    MH_CreateHookApi(L"ws2_32.dll", "closesocket", &HookCloseSocket, (void**)&TrueCloseSocket);
    MH_CreateHookApi(L"ws2_32.dll", "shutdown", &HookShutdown, (void**)&TrueShutdown);
    MH_EnableHook(MH_ALL_HOOKS);
    return true;
}

void Ws2RemoveHooks() {
    FlushStats(true);
    MH_DisableHook(MH_ALL_HOOKS);
    MH_Uninitialize();
}

void Ws2KillAllSockets() {
    Ws2KillSockets(false);
}

// battleOnly=true 时跳过 HTTP(S) 端口（80/443）；若一条都没断到则全断兜底
void Ws2KillSockets(bool battleOnly) {
    int killed = 0;
    AcquireSRWLockShared(&g_lock);
    std::vector<TrackedSocket> copy = g_sockets;
    ReleaseSRWLockShared(&g_lock);
    for (auto& t : copy) {
        int port = ntohs(t.addr.sin_port);
        if (battleOnly && (port == 80 || port == 443)) continue;
        shutdown(t.s, SD_BOTH);
        killed++;
    }
    if (battleOnly && killed == 0) {
        for (auto& t : copy) {
            shutdown(t.s, SD_BOTH);
            killed++;
        }
    }
    FlushStats(true);
    // 连端口一起上报：便于判断"切的是不是战斗连接"（排查跳过战斗是否生效的关键信息）
    {
        char ports[160] = "";
        int shown = 0;
        for (auto& t : copy) {
            if (shown >= 8) break;
            char one[24];
            sprintf_s(one, "%s%d", shown ? "," : "", ntohs(t.addr.sin_port));
            strcat_s(ports, one);
            shown++;
        }
        PipeSendEventFmt("{\"ev\":\"kill\",\"n\":%d,\"battle_only\":%s,\"ports\":\"%s\",\"tracked\":%d}",
                         killed, battleOnly ? "true" : "false", ports, (int)copy.size());
    }
}

int Ws2TrackedCount() {
    AcquireSRWLockShared(&g_lock);
    int n = (int)g_sockets.size();
    ReleaseSRWLockShared(&g_lock);
    return n;
}

TrafficStats Ws2GetStats() { return g_stats; }
