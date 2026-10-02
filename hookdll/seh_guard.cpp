// seh_guard.cpp - 反射操作的结构化异常护栏
// 目的：注入到真实游戏进程后，任何反射层意外（空指针/字段偏移错误等）
//       都只能让该条命令失败，绝不能把游戏搞崩。
// 注意：含 __try 的函数不能同时持有需要栈展开的 C++ 对象，
//       故这些包装函数只使用指针/POD 局部变量，把真正的实现放在被调函数里。
#include "yyzyhook.h"

static void ReportFault(const char* where, unsigned long code) {
    PipeSendEventFmt("{\"ev\":\"fault\",\"where\":\"%s\",\"code\":%lu}", where, code);
}

int SafeUiInit() {
    __try {
        return Il2CppUiInit() ? 1 : 0;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        ReportFault("init", GetExceptionCode());
        return -999;
    }
}

int SafeDumpButtons(std::vector<std::string>* lines) {
    __try {
        return Il2CppUiDumpButtons(*lines, 400);
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        ReportFault("dump_ui", GetExceptionCode());
        return -999;
    }
}

int SafeDumpTexts(std::vector<std::string>* lines) {
    __try {
        return Il2CppUiDumpTexts(*lines, 300);
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        ReportFault("dump_texts", GetExceptionCode());
        return -999;
    }
}

int SafeClickButton(const char* name, const char* path) {
    __try {
        return Il2CppUiClickButton(name, path);
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        ReportFault("click_btn", GetExceptionCode());
        return -999;
    }
}

int SafeClickNth(const char* path, int index) {
    __try {
        return Il2CppUiClickNth(path, index);
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        ReportFault("click_nth", GetExceptionCode());
        return -999;
    }
}

int SafeGetScreenPos(const char* name, int* x, int* y) {
    __try {
        return Il2CppUiGetScreenPos(name, x, y) ? 1 : 0;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        ReportFault("ui_pos", GetExceptionCode());
        return -999;
    }
}

int SafePhase(int* secs) {
    __try {
        return Il2CppUiPhase(secs);
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        ReportFault("phase", GetExceptionCode());
        return -999;
    }
}

int SafeDetectCountdown(std::vector<std::string>* report) {
    __try {
        return Il2CppUiDetectCountdown(*report);
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        ReportFault("detect_countdown", GetExceptionCode());
        return -999;
    }
}

int SafeReadWatchTexts(std::string* out) {
    __try {
        Il2CppUiReadWatchTextsInto(out);
        return 1;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        ReportFault("watch_texts", GetExceptionCode());
        return -999;
    }
}

int SafeKillBattle() {
    __try {
        Ws2KillSockets(true);
        return 1;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        ReportFault("kill_battle", GetExceptionCode());
        return -999;
    }
}

int SafeKillAll() {
    __try {
        Ws2KillAllSockets();
        return 1;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        ReportFault("kill_all", GetExceptionCode());
        return -999;
    }
}

int SafeHold(int ms) {
    __try {
        Ws2SetHold(ms);
        return 1;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        ReportFault("hold", GetExceptionCode());
        return -999;
    }
}
