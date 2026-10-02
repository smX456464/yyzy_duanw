// il2cppui.cpp - il2cpp 反射层：UI 枚举 / 按钮点击 / 输入合成
// 仅在 GameAssembly.dll 存在（游戏进程）时可用。
#include "yyzyhook.h"
#include <string.h>
#include <vector>
#include <string>
#include <algorithm>
#include <utility>

#pragma comment(lib, "user32.lib")

// ---------- 动态解析 il2cpp 导出 ----------
typedef void* Il2CppClass;
typedef void* Il2CppObject;
typedef void* Il2CppString;
typedef void* MethodInfo;
typedef void* Il2CppException;
typedef void* Il2CppImage;
typedef void* Il2CppAssembly;
typedef void* Il2CppDomain;

typedef void(__cdecl* Il2CppGCCallback)(void* ctx, void* obj, Il2CppClass* klass, void** desc);

static void* (__cdecl* p_il2cpp_domain_get)() = nullptr;
static Il2CppAssembly** (__cdecl* p_il2cpp_domain_get_assemblies)(Il2CppDomain, size_t*) = nullptr;
static const char* (__cdecl* p_il2cpp_assembly_get_name)(Il2CppAssembly*) = nullptr;
static Il2CppImage* (__cdecl* p_il2cpp_assembly_get_image)(Il2CppAssembly*) = nullptr;
static const char* (__cdecl* p_il2cpp_image_get_name)(Il2CppImage*) = nullptr;
static Il2CppString* (__cdecl* p_il2cpp_string_new)(const char*) = nullptr;
static const void* (__cdecl* p_il2cpp_class_get_type)(Il2CppClass*) = nullptr;
static void* (__cdecl* p_il2cpp_type_get_object)(const void*) = nullptr;
static void* (__cdecl* p_il2cpp_object_unbox)(void*) = nullptr;
static size_t (__cdecl* p_il2cpp_image_get_class_count)(const Il2CppImage*) = nullptr;
static Il2CppClass* (__cdecl* p_il2cpp_image_get_class)(const Il2CppImage*, size_t) = nullptr;
static const char* (__cdecl* p_il2cpp_class_get_name)(Il2CppClass*) = nullptr;
static void* (__cdecl* p_il2cpp_class_get_fields)(Il2CppClass*, void*) = nullptr;
static const char* (__cdecl* p_il2cpp_field_get_name)(void*) = nullptr;
static size_t (__cdecl* p_il2cpp_field_get_offset)(void*) = nullptr;
static const MethodInfo* (__cdecl* p_il2cpp_class_get_method_from_name)(Il2CppClass*, const char*, int) = nullptr;
static void* (__cdecl* p_il2cpp_runtime_invoke)(const MethodInfo*, void*, void**, Il2CppException**) = nullptr;
static Il2CppClass* (__cdecl* p_il2cpp_object_get_class)(Il2CppObject*) = nullptr;
static uint16_t* (__cdecl* p_il2cpp_string_chars)(Il2CppString*) = nullptr;
static int (__cdecl* p_il2cpp_string_length)(Il2CppString*) = nullptr;
static void (__cdecl* p_il2cpp_gc_foreach_heap)(void* ctx, Il2CppGCCallback) = nullptr;
#define p_il2cpp_gc_foreach_heap(ctx, cb) ((void)0)   // 禁用：见下方说明
static void* (__cdecl* p_il2cpp_thread_attach)(void*) = nullptr;
static int (__cdecl* p_il2cpp_class_get_method_count)(const Il2CppClass*) = nullptr;
static const MethodInfo* (__cdecl* p_il2cpp_class_get_methods)(const Il2CppClass*, void*) = nullptr;
static const char* (__cdecl* p_il2cpp_method_get_name)(const MethodInfo*) = nullptr;
static Il2CppClass* (__cdecl* p_il2cpp_class_get_parent)(Il2CppClass*) = nullptr;
static const char* (__cdecl* p_il2cpp_class_get_namespace)(Il2CppClass*) = nullptr;
static uint32_t (__cdecl* p_il2cpp_gchandle_new)(void*, bool) = nullptr;
static void* (__cdecl* p_il2cpp_gchandle_get_target)(uint32_t) = nullptr;
static void (__cdecl* p_il2cpp_gchandle_free)(uint32_t) = nullptr;

static HMODULE g_gameAssembly = nullptr;
static Il2CppClass* g_classButton = nullptr;
static Il2CppClass* g_classGameObject = nullptr;
static Il2CppClass* g_classTransform = nullptr;
static Il2CppClass* g_classRectTransform = nullptr;
static Il2CppClass* g_classTMP = nullptr; // TMPro.TextMeshProUGUI

static size_t g_offGO_Name = 0;      // GameObject.m_Name
static size_t g_offGO_Active = 0;    // GameObject.m_IsActive
static size_t g_offGO_Transform = 0; // GameObject.m_Transform
static size_t g_offComp_GameObject = 0; // Component.m_GameObject
static size_t g_offButton_onClick = 0;  // Button.m_OnClick
static size_t g_offTransform_Parent = 0; // Transform.m_Parent
static size_t g_offTMP_text = 0;      // TMP_Text.m_text

static std::string U16ToString(const uint16_t* s, int len) {
    std::string out;
    for (int i = 0; i < len; i++) {
        uint16_t c = s[i];
        if (c < 0x80) out += (char)c;
        else {
            // 简单 UTF-16 → UTF-8
            if (c >= 0xD800 && c <= 0xDBFF && i + 1 < len) {
                uint32_t cp = 0x10000 + ((c - 0xD800) << 10) + (s[++i] - 0xDC00);
                out += (char)(0xF0 | (cp >> 18));
                out += (char)(0x80 | ((cp >> 12) & 0x3F));
                out += (char)(0x80 | ((cp >> 6) & 0x3F));
                out += (char)(0x80 | (cp & 0x3F));
            } else {
                out += (char)(0xE0 | (c >> 12));
                out += (char)(0x80 | ((c >> 6) & 0x3F));
                out += (char)(0x80 | (c & 0x3F));
            }
        }
    }
    return out;
}

static Il2CppString* ReadStringField(void* obj, size_t off) {
    if (!obj || !off) return nullptr;
    return *(Il2CppString**)((char*)obj + off);
}

static size_t FindFieldOffsetDeep(Il2CppClass* klass, const char* name);

static std::string ReadStringObj(Il2CppString* s);   // 前置声明
// ---------- 属性方法访问层 ----------
// 重要：本游戏的 UnityEngine.GameObject / Component / Transform 没有托管字段
// （dump 里只有属性 get_transform / get_gameObject / get_parent / get_name / get_activeSelf），
// 所以名字、父子关系、激活状态只能通过调用这些方法获取。
static const MethodInfo* m_comp_getGameObject = nullptr;
static const MethodInfo* m_go_getTransform = nullptr;
static const MethodInfo* m_tr_getParent = nullptr;
static const MethodInfo* m_obj_getName = nullptr;
static const MethodInfo* m_go_getActiveSelf = nullptr;

static void* InvokeNoArg(void* obj, const MethodInfo* m) {
    if (!obj || !m || !p_il2cpp_runtime_invoke) return nullptr;
    Il2CppObject* exc = nullptr;
    void* r = p_il2cpp_runtime_invoke((const MethodInfo*)m, obj, nullptr, &exc);
    if (exc) return nullptr;
    return r;
}

static void* GetGameObjectOf(void* comp) { return InvokeNoArg(comp, m_comp_getGameObject); }
static void* GetTransformOf(void* go) { return InvokeNoArg(go, m_go_getTransform); }
static void* GetParentOf(void* tr) { return InvokeNoArg(tr, m_tr_getParent); }

static bool UnboxBool(void* boxed) {
    if (!boxed) return false;
    return *(bool*)((char*)boxed + sizeof(void*) * 2);   // 跳过 Il2CppObject 头（klass+monitor）
}

static bool GetActiveOf(void* go) { return UnboxBool(InvokeNoArg(go, m_go_getActiveSelf)); }

static std::string GetNameOf(void* go) {
    void* s = InvokeNoArg(go, m_obj_getName);
    if (!s) return std::string();
    return ReadStringObj((Il2CppString*)s);
}

static std::string ReadStringObj(Il2CppString* s) {
    if (!s || !p_il2cpp_string_chars) return "";
    int len = p_il2cpp_string_length(s);
    if (len <= 0) return "";
    return U16ToString(p_il2cpp_string_chars(s), len);
}

static void* ReadFieldPtr(void* obj, size_t off) {
    if (!obj || !off) return nullptr;
    return *(void**)((char*)obj + off);
}

// 找字段偏移：遍历类字段
static size_t FindFieldOffset(Il2CppClass* klass, const char* name) {
    if (!klass || !p_il2cpp_class_get_fields) return 0;
    void* iter = nullptr;
    void* field;
    while ((field = p_il2cpp_class_get_fields(klass, &iter)) != nullptr) {
        if (p_il2cpp_field_get_name && strcmp(p_il2cpp_field_get_name(field), name) == 0) {
            return p_il2cpp_field_get_offset(field);
        }
    }
    return 0;
}

static void InitLog(const char* step);   // 前置声明（FindClass 会用到）

// 找类：遍历所有程序集（含 HybridCLR 热更程序集）
// 关键：必须同时匹配命名空间 —— 否则会命中同名类
//（实测本游戏里 Component 有 System.ComponentModel.Component 与 UnityEngine.Component 同名）
static Il2CppClass* FindClass(const char* ns, const char* name) {
    if (!p_il2cpp_domain_get || !p_il2cpp_domain_get_assemblies) return nullptr;
    Il2CppDomain domain = p_il2cpp_domain_get();
    if (!domain) return nullptr;
    size_t count = 0;
    Il2CppAssembly** asms = p_il2cpp_domain_get_assemblies(domain, &count);
    if (!asms) return nullptr;
    {
        char buf[160];
        sprintf_s(buf, "init: FindClass(%s) assemblies=%zu", name, count);
        InitLog(buf);
    }
    for (size_t i = 0; i < count; i++) {
        Il2CppImage* img = p_il2cpp_assembly_get_image(asms[i]);
        if (!img) continue;
        const char* imgName = p_il2cpp_image_get_name ? p_il2cpp_image_get_name(img) : "?";
        size_t n = p_il2cpp_image_get_class_count(img);
        {
            // 逐个程序集记录（含类数量），用于定位是哪个程序集/类枚举卡住
            char buf[200];
            sprintf_s(buf, "init:   image[%zu/%zu] %s classes=%zu", i + 1, count,
                      imgName ? imgName : "?", n);
            InitLog(buf);
        }
        for (size_t j = 0; j < n; j++) {
            Il2CppClass* k = p_il2cpp_image_get_class(img, j);
            if (!k) continue;
            const char* kn = p_il2cpp_class_get_name(k);
            if (!kn || strcmp(kn, name) != 0) continue;
            if (ns && *ns && p_il2cpp_class_get_namespace) {
                const char* kns = p_il2cpp_class_get_namespace(k);
                if (!kns || strcmp(kns, ns) != 0) continue;   // 命名空间不匹配 → 跳过
            }
            InitLog("init:   -> class matched");
            return k;
        }
    }
    InitLog("init:   -> class NOT found");
    return nullptr;
}

static volatile long g_walkCount = 0;   // 堆遍历进度（诊断用）

static bool Il2CppReady() {
    return g_gameAssembly && p_il2cpp_class_get_name;
}

// 诊断：把初始化进度写文件（定位卡死步骤用）—— 所有构建都开启，便于用户侧排查
static void InitLog(const char* step) {
    wchar_t path[MAX_PATH];
    DWORD n = GetEnvironmentVariableW(L"TEMP", path, MAX_PATH);
    if (n == 0 || n >= MAX_PATH) wcscpy_s(path, L"C:\\Temp");
    wcscat_s(path, L"\\yyzyhook_init.log");
    HANDLE h = CreateFileW(path, FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE,
                           nullptr, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (h != INVALID_HANDLE_VALUE) {
        char line[256];
        int m = sprintf_s(line, "pid=%lu %s\n", GetCurrentProcessId(), step);
        DWORD written = 0;
        WriteFile(h, line, (DWORD)m, &written, nullptr);
        CloseHandle(h);
    }
}

static volatile int g_initMaxStep = 0;   // 0=全量；1=仅解析导出；2=+线程挂载；3=+查类

static void CacheUnityApi();   // 定义在 unityapi_impl.h（文件末尾包含）

bool Il2CppUiInit() {
    InitLog("init: enter");
    g_gameAssembly = GetModuleHandleW(L"GameAssembly.dll");
    if (!g_gameAssembly) { InitLog("init: no GameAssembly.dll"); return false; }
#define RESOLVE(name) p_##name = (decltype(p_##name))GetProcAddress(g_gameAssembly, #name)
    RESOLVE(il2cpp_domain_get);
    RESOLVE(il2cpp_domain_get_assemblies);
    RESOLVE(il2cpp_assembly_get_image);
    RESOLVE(il2cpp_image_get_class_count);
    RESOLVE(il2cpp_image_get_class);
    RESOLVE(il2cpp_class_get_name);
    RESOLVE(il2cpp_class_get_fields);
    RESOLVE(il2cpp_field_get_name);
    RESOLVE(il2cpp_field_get_offset);
    RESOLVE(il2cpp_class_get_method_from_name);
    RESOLVE(il2cpp_runtime_invoke);
    RESOLVE(il2cpp_object_get_class);
    RESOLVE(il2cpp_string_chars);
    RESOLVE(il2cpp_string_new);
    RESOLVE(il2cpp_class_get_type);
    RESOLVE(il2cpp_type_get_object);
    RESOLVE(il2cpp_object_unbox);
    RESOLVE(il2cpp_string_length);
    // 堆遍历已彻底弃用：其回调签名与 Unity 实际不一致（void(*)(obj,user_data)），
    // 错位后会拿垃圾指针当类指针 → 挂死/崩溃。改为 Unity API（Find/FindObjectsOfType）。
    // p_il2cpp_gc_foreach_heap 不解析，且下面的宏让任何残留调用都变成空操作。
    RESOLVE(il2cpp_thread_attach);
    RESOLVE(il2cpp_class_get_parent);
    RESOLVE(il2cpp_class_get_namespace);
    RESOLVE(il2cpp_image_get_name);
    RESOLVE(il2cpp_gchandle_new);
    RESOLVE(il2cpp_gchandle_get_target);
    RESOLVE(il2cpp_gchandle_free);
#undef RESOLVE
    // 注意：不要检查 p_il2cpp_gc_foreach_heap —— 堆遍历已刻意不解析（见上方说明），
    // 曾因把它列入必需项导致初始化直接失败、所有命令回 no il2cpp。
    if (!p_il2cpp_domain_get || !p_il2cpp_class_get_name || !p_il2cpp_class_get_fields ||
        !p_il2cpp_class_get_method_from_name || !p_il2cpp_runtime_invoke || !p_il2cpp_string_new) {
        InitLog("init: missing required exports");
        return false;
    }
    InitLog("init: exports resolved");
    if (g_initMaxStep == 1) { InitLog("init: STOP after step1 (exports)"); return false; }
    p_il2cpp_thread_attach(p_il2cpp_domain_get()); // 本线程挂到 il2cpp 运行时
    InitLog("init: thread attached");
    if (g_initMaxStep == 2) { InitLog("init: STOP after step2 (thread attach)"); return false; }

    // 缓存常用类 + 字段偏移
    g_classButton = FindClass("UnityEngine.UI", "Button");
    InitLog("init: FindClass Button done");
    g_classGameObject = FindClass("UnityEngine", "GameObject");
    InitLog("init: FindClass GameObject done");
    g_classTransform = FindClass("UnityEngine", "Transform");
    InitLog("init: FindClass Transform done");
    g_classRectTransform = FindClass("UnityEngine", "RectTransform");
    InitLog("init: FindClass RectTransform done");
    g_classTMP = FindClass("TMPro", "TextMeshProUGUI");
    InitLog("init: FindClass TMP done");
    if (g_initMaxStep == 3) { InitLog("init: STOP after step3 (FindClass)"); return false; }
    if (g_classGameObject) {
        g_offGO_Name = FindFieldOffsetDeep(g_classGameObject, "m_Name");
        g_offGO_Active = FindFieldOffsetDeep(g_classGameObject, "m_IsActive");
        g_offGO_Transform = FindFieldOffsetDeep(g_classGameObject, "m_Transform");
    }
    if (g_classButton) {
        g_offButton_onClick = FindFieldOffsetDeep(g_classButton, "m_OnClick");
        if (!g_offComp_GameObject) g_offComp_GameObject = FindFieldOffsetDeep(g_classButton, "m_GameObject");
    }
    if (g_classTransform) {
        g_offTransform_Parent = FindFieldOffsetDeep(g_classTransform, "m_Parent");
    }
    if (g_classTMP) {
        g_offTMP_text = FindFieldOffsetDeep(g_classTMP, "m_text");
    }
    // 缓存属性方法（本游戏这些类型没有托管字段，只能调用属性）
    if (g_classGameObject) {
        m_go_getTransform = p_il2cpp_class_get_method_from_name
            ? p_il2cpp_class_get_method_from_name((Il2CppClass*)g_classGameObject, "get_transform", 0) : nullptr;
        m_go_getActiveSelf = p_il2cpp_class_get_method_from_name
            ? p_il2cpp_class_get_method_from_name((Il2CppClass*)g_classGameObject, "get_activeSelf", 0) : nullptr;
        m_obj_getName = p_il2cpp_class_get_method_from_name
            ? p_il2cpp_class_get_method_from_name((Il2CppClass*)g_classGameObject, "get_name", 0) : nullptr;
    }
    if (g_classButton && p_il2cpp_class_get_method_from_name) {
        m_comp_getGameObject = p_il2cpp_class_get_method_from_name((Il2CppClass*)g_classButton, "get_gameObject", 0);
    }
    if (g_classTransform && p_il2cpp_class_get_method_from_name) {
        m_tr_getParent = p_il2cpp_class_get_method_from_name((Il2CppClass*)g_classTransform, "get_parent", 0);
    }
    {
        char b[200];
        sprintf_s(b, "init: methods goTr=%d goAct=%d goName=%d compGO=%d trParent=%d",
                  m_go_getTransform ? 1 : 0, m_go_getActiveSelf ? 1 : 0, m_obj_getName ? 1 : 0,
                  m_comp_getGameObject ? 1 : 0, m_tr_getParent ? 1 : 0);
        InitLog(b);
    }
    CacheUnityApi();
    return true;
}

static size_t FindFieldOffsetDeep(Il2CppClass* klass, const char* name) {
    size_t off = FindFieldOffset(klass, name);
    if (off) return off;
    if (p_il2cpp_class_get_parent) {
        Il2CppClass* parent = p_il2cpp_class_get_parent(klass);
        if (parent) return FindFieldOffsetDeep(parent, name);
    }
    return 0;
}

// ---------- 堆遍历收集 UI ----------
struct UiCollectCtx {
    std::vector<std::string>* lines;
    int limit;
};

static bool GameObjectActive(void* go) {
    return GetActiveOf(go);
}

static std::string GameObjectName(void* go) {
    return GetNameOf(go);
}

static std::string GameObjectPath(void* go) {
    std::string path = GameObjectName(go);
    void* tr = GetTransformOf(go);
    int depth = 0;
    while (tr && depth < 6) {
        void* parent = GetParentOf(tr);
        if (!parent) break;
        // parent 是 Transform，取其 GameObject
        void* pgo = ReadFieldPtr(parent, g_offComp_GameObject);
        if (!pgo) break;
        path = GameObjectName(pgo) + "/" + path;
        tr = parent;
        depth++;
    }
    return path;
}

static void __cdecl GcCallback(void* ctx, void* obj, Il2CppClass* klass, void** desc) {
    (void)desc;
    UiCollectCtx* c = (UiCollectCtx*)ctx;
    if (c->limit <= 0) return;
    const char* cname = p_il2cpp_class_get_name(klass);
    if (!cname) return;
    if (strcmp(cname, "Button") == 0) {
        void* go = GetGameObjectOf(obj);
        if (go && GameObjectActive(go)) {
            std::string name = GameObjectName(go);
            std::string path = GameObjectPath(go);
            char line[512];
            snprintf(line, sizeof(line), "{\"ev\":\"ui\",\"type\":\"btn\",\"name\":\"%s\",\"path\":\"%s\"}",
                name.c_str(), path.c_str());
            c->lines->push_back(line);
            c->limit--;
        }
    }
}

int HeapWalk_DumpButtons(std::vector<std::string>& lines, int limit) {
    if (!Il2CppReady() || !g_classButton) return -1;
    UiCollectCtx ctx = { &lines, limit };
    p_il2cpp_gc_foreach_heap(&ctx, GcCallback);
    return (int)lines.size();
}

// ---------- 按钮点击 ----------
// 找到"激活的、名字匹配"的按钮并调 onClick.Invoke()
int HeapWalk_ClickButton(const char* name, const char* pathContains) {
    if (!Il2CppReady() || !g_classButton) return -1;
    struct Ctx {
        const char* name;
        const char* pathContains;
        Il2CppObject* found;
    } ctx = { name, pathContains, nullptr };
    struct Walk {
        static void __cdecl cb(void* c, void* obj, Il2CppClass* klass, void** desc) {
            (void)desc;
            Ctx* x = (Ctx*)c;
            if (x->found) return;
            const char* cname = p_il2cpp_class_get_name(klass);
            if (!cname || strcmp(cname, "Button") != 0) return;
            void* go = GetGameObjectOf(obj);
            if (!go || !GameObjectActive(go)) return;
            std::string n = GameObjectName(go);
            if (strcmp(n.c_str(), x->name) != 0) return;
            if (x->pathContains && *x->pathContains) {
                std::string p = GameObjectPath(go);
                if (p.find(x->pathContains) == std::string::npos) return;
            }
            x->found = (Il2CppObject*)obj;
        }
    };
    p_il2cpp_gc_foreach_heap(&ctx, Walk::cb);
    if (!ctx.found) return 0;

    // onClick 字段 → ButtonClickedEvent 对象 → Invoke()
    Il2CppObject* onClickObj = (Il2CppObject*)ReadFieldPtr(ctx.found, g_offButton_onClick);
    if (!onClickObj) return -2;
    Il2CppClass* evClass = p_il2cpp_object_get_class(onClickObj);
    const MethodInfo* invoke = p_il2cpp_class_get_method_from_name(evClass, "Invoke", 0);
    if (!invoke) return -3;
    Il2CppException* exc = nullptr;
    p_il2cpp_runtime_invoke(invoke, onClickObj, nullptr, &exc);
    if (exc) return -4;
    return 1;
}

// ---------- 按路径+序号点击（名字对不上时的兜底：按屏幕 X 排序取第 N 个） ----------
struct NthButton {
    void* obj;
    float x;
};

int HeapWalk_ClickNth(const char* pathContains, int index) {
    if (!Il2CppReady() || !g_classButton || !pathContains) return -1;

    // 1) 收集匹配路径的激活按钮
    struct Ctx { const char* pathKw; std::vector<NthButton>* out; };
    struct WalkBtn {
        static void __cdecl cb(void* c, void* obj, Il2CppClass* klass, void** desc) {
            (void)desc;
            Ctx* x = (Ctx*)c;
            if (x->out->size() >= 16) return;
            const char* cname = p_il2cpp_class_get_name(klass);
            if (!cname || strcmp(cname, "Button") != 0) return;
            void* go = GetGameObjectOf(obj);
            if (!go || !GameObjectActive(go)) return;
            std::string p = GameObjectPath(go);
            if (p.find(x->pathKw) == std::string::npos) return;
            x->out->push_back({ obj, 0.0f });
        }
    };
    std::vector<NthButton> buttons;
    Ctx ctx = { pathContains, &buttons };
    p_il2cpp_gc_foreach_heap(&ctx, WalkBtn::cb);
    if (buttons.empty()) return 0;

    // 2) 一次性遍历 RectTransform，建立 GameObject → x 坐标映射
    struct PosCtx { std::vector<std::pair<void*, float>>* out; };
    struct WalkRt {
        static void __cdecl cb(void* c, void* obj, Il2CppClass* klass, void** desc) {
            (void)desc;
            PosCtx* x = (PosCtx*)c;
            if (x->out->size() >= 2000) return;
            const char* cname = p_il2cpp_class_get_name(klass);
            if (!cname || strcmp(cname, "RectTransform") != 0) return;
            void* go = GetGameObjectOf(obj);
            if (!go || !GameObjectActive(go)) return;
            const MethodInfo* m = p_il2cpp_class_get_method_from_name(g_classRectTransform, "get_position", 0);
            if (!m) return;
            Il2CppException* exc = nullptr;
            void* ret = p_il2cpp_runtime_invoke(m, obj, nullptr, &exc);
            if (!ret || exc) return;
            x->out->push_back({ go, ((float*)ret)[0] });
        }
    };
    std::vector<std::pair<void*, float>> positions;
    PosCtx pctx = { &positions };
    p_il2cpp_gc_foreach_heap(&pctx, WalkRt::cb);

    for (auto& b : buttons) {
        void* go = ReadFieldPtr(b.obj, g_offComp_GameObject);
        for (auto& pr : positions) {
            if (pr.first == go) { b.x = pr.second; break; }
        }
    }
    std::sort(buttons.begin(), buttons.end(),
              [](const NthButton& a, const NthButton& b) { return a.x < b.x; });

    if (index < 0 || index >= (int)buttons.size()) return -5;

    // 3) 点击第 index 个
    Il2CppObject* target = (Il2CppObject*)buttons[index].obj;
    Il2CppObject* onClickObj = (Il2CppObject*)ReadFieldPtr(target, g_offButton_onClick);
    if (!onClickObj) return -2;
    Il2CppClass* evClass = p_il2cpp_object_get_class(onClickObj);
    const MethodInfo* invoke = p_il2cpp_class_get_method_from_name(evClass, "Invoke", 0);
    if (!invoke) return -3;
    Il2CppException* exc2 = nullptr;
    p_il2cpp_runtime_invoke(invoke, onClickObj, nullptr, &exc2);
    if (exc2) return -4;
    return 1;
}

// ---------- 倒计时对象自动识别 ----------
// 思路：扫描所有"纯数字文本"，间隔采样，找出数值随时间递减的那个
struct CdCandidate {
    char name[64];
    uint32_t handle;
    int last;
    int delta;
};
static CdCandidate g_cdCand[8];
static int g_cdCount = 0;
static char g_detectedCountdown[64] = {};

static bool ParseSmallInt(const std::string& s, int* out) {
    if (s.empty() || s.size() > 3) return false;
    for (char ch : s) if (ch < '0' || ch > '9') return false;
    int v = atoi(s.c_str());
    if (v < 0 || v > 120) return false;
    *out = v;
    return true;
}

int HeapWalk_DetectCountdown(std::vector<std::string>& report) {
    if (!Il2CppReady() || !g_classTMP || !g_offTMP_text) return -1;
    // 首次采集：找出所有纯数字文本
    if (g_cdCount == 0) {
        struct Ctx { };
        struct Walk {
            static void __cdecl cb(void* c, void* obj, Il2CppClass* klass, void** desc) {
                (void)c; (void)desc;
                if (g_cdCount >= 8) return;
                const char* cname = p_il2cpp_class_get_name(klass);
                if (!cname || strcmp(cname, "TextMeshProUGUI") != 0) return;
                void* go = GetGameObjectOf(obj);
                if (!go || !GameObjectActive(go)) return;
                std::string tx = ReadStringObj(ReadStringField(obj, g_offTMP_text));
                int v = 0;
                if (!ParseSmallInt(tx, &v)) return;
                std::string nm = GameObjectName(go);
                if (nm.empty() || nm.size() > 63) return;
                strncpy_s(g_cdCand[g_cdCount].name, nm.c_str(), 63);
                g_cdCand[g_cdCount].handle = p_il2cpp_gchandle_new ? p_il2cpp_gchandle_new(obj, false) : 0;
                g_cdCand[g_cdCount].last = v;
                g_cdCand[g_cdCount].delta = 0;
                g_cdCount++;
            }
        };
        p_il2cpp_gc_foreach_heap(nullptr, Walk::cb);
        char line[160];
        snprintf(line, sizeof(line), "{\"ev\":\"cd_scan\",\"found\":%d}", g_cdCount);
        report.push_back(line);
        return 0;  // 需要再采样一次
    }
    // 二次采样：算变化量，挑递减最明显的
    int best = -1;
    for (int i = 0; i < g_cdCount; i++) {
        if (!g_cdCand[i].handle) continue;
        void* obj = p_il2cpp_gchandle_get_target ? p_il2cpp_gchandle_get_target(g_cdCand[i].handle) : nullptr;
        if (!obj) continue;
        std::string tx = ReadStringObj(ReadStringField(obj, g_offTMP_text));
        int v = 0;
        if (!ParseSmallInt(tx, &v)) continue;
        g_cdCand[i].delta = g_cdCand[i].last - v;  // 正值 = 递减
        if (g_cdCand[i].delta > 0 && (best < 0 || g_cdCand[i].delta > g_cdCand[best].delta))
            best = i;
        char line[192];
        snprintf(line, sizeof(line),
                 "{\"ev\":\"cd_cand\",\"name\":\"%s\",\"from\":%d,\"to\":%d}",
                 g_cdCand[i].name, g_cdCand[i].last, v);
        report.push_back(line);
    }
    if (best >= 0) {
        strncpy_s(g_detectedCountdown, g_cdCand[best].name, 63);
        char line[192];
        snprintf(line, sizeof(line), "{\"ev\":\"cd_detected\",\"name\":\"%s\"}", g_detectedCountdown);
        report.push_back(line);
        return 1;
    }
    report.push_back("{\"ev\":\"cd_detected\",\"name\":\"\"}");
    return 0;
}

void HeapWalk_ResetCountdownDetect() {
    for (int i = 0; i < g_cdCount; i++) {
        if (g_cdCand[i].handle && p_il2cpp_gchandle_free) p_il2cpp_gchandle_free(g_cdCand[i].handle);
        g_cdCand[i].handle = 0;
    }
    g_cdCount = 0;
}

// ---------- 输入合成（原生 SendInput，进程内调用即系统级输入） ----------
void Il2CppUiSyntheticClick(int x, int y) {
    SetCursorPos(x, y);
    Sleep(10);
    INPUT in[2] = {};
    in[0].type = INPUT_MOUSE;
    in[0].mi.dwFlags = MOUSEEVENTF_LEFTDOWN;
    in[1].type = INPUT_MOUSE;
    in[1].mi.dwFlags = MOUSEEVENTF_LEFTUP;
    SendInput(2, in, sizeof(INPUT));
}

// 只移动光标（用于"悬停查看"类操作）
void Il2CppUiSyntheticMove(int x, int y) {
    SetCursorPos(x, y);
}

void Il2CppUiSyntheticDrag(int x1, int y1, int x2, int y2) {
    SetCursorPos(x1, y1);
    Sleep(15);
    INPUT down = {};
    down.type = INPUT_MOUSE;
    down.mi.dwFlags = MOUSEEVENTF_LEFTDOWN;
    SendInput(1, &down, sizeof(INPUT));
    int steps = 8;
    for (int i = 1; i <= steps; i++) {
        int cx = x1 + (x2 - x1) * i / steps;
        int cy = y1 + (y2 - y1) * i / steps;
        SetCursorPos(cx, cy);
        Sleep(10);
    }
    INPUT up = {};
    up.type = INPUT_MOUSE;
    up.mi.dwFlags = MOUSEEVENTF_LEFTUP;
    SendInput(1, &up, sizeof(INPUT));
}

// ---------- TMP 文本 / 阶段检测 / 自动跳过 ----------
bool Il2CppUiIsReady() {
    return Il2CppReady();
}

static std::string Il2CppUiGetTMPText(const char* goName) {
    if (!Il2CppReady() || !g_classTMP || !g_offTMP_text) return "";
    struct Ctx { const char* name; void* found; };
    struct Walk {
        static void __cdecl cb(void* c, void* obj, Il2CppClass* klass, void** desc) {
            (void)desc;
            Ctx* x = (Ctx*)c;
            if (x->found) return;
            const char* cname = p_il2cpp_class_get_name(klass);
            if (!cname || strcmp(cname, "TextMeshProUGUI") != 0) return;
            void* go = GetGameObjectOf(obj);
            if (!go || !GameObjectActive(go)) return;
            if (GameObjectName(go) == x->name) x->found = obj;
        }
    };
    Ctx ctx = { goName, nullptr };
    p_il2cpp_gc_foreach_heap(&ctx, Walk::cb);
    if (!ctx.found) return "";
    return ReadStringObj(ReadStringField(ctx.found, g_offTMP_text));
}

// 带缓存的 TMP 查找：用 GC 强句柄固定对象，避免每次全堆遍历（性能）与悬空指针（安全）
struct TextCacheEntry {
    char name[64];
    uint32_t handle;
    bool valid;
};
static TextCacheEntry g_textCache[8];

static void* FindTMPByName(const char* goName) {
    if (!p_il2cpp_gchandle_get_target) return nullptr;
    for (auto& e : g_textCache) {
        if (e.valid && strcmp(e.name, goName) == 0) {
            void* obj = p_il2cpp_gchandle_get_target(e.handle);
            if (obj) {
                void* go = GetGameObjectOf(obj);
                if (go && GameObjectActive(go) && GameObjectName(go) == goName) return obj;
            }
            if (p_il2cpp_gchandle_free) p_il2cpp_gchandle_free(e.handle);
            e.valid = false;
        }
    }
    struct Ctx { const char* name; void* found; };
    struct Walk {
        static void __cdecl cb(void* c, void* obj, Il2CppClass* klass, void** desc) {
            (void)desc;
            Ctx* x = (Ctx*)c;
            if (x->found) return;
            const char* cname = p_il2cpp_class_get_name(klass);
            if (!cname || strcmp(cname, "TextMeshProUGUI") != 0) return;
            void* go = GetGameObjectOf(obj);
            if (!go || !GameObjectActive(go)) return;
            if (GameObjectName(go) == x->name) x->found = obj;
        }
    };
    Ctx ctx = { goName, nullptr };
    p_il2cpp_gc_foreach_heap(&ctx, Walk::cb);
    if (!ctx.found) return nullptr;
    for (auto& e : g_textCache) {
        if (!e.valid) {
            strncpy_s(e.name, goName, sizeof(e.name) - 1);
            e.handle = p_il2cpp_gchandle_new ? p_il2cpp_gchandle_new(ctx.found, false) : 0;
            e.valid = (e.handle != 0);
            break;
        }
    }
    return ctx.found;
}

static std::string HeapWalk_GetTMPTextFast(const char* goName) {
    void* obj = FindTMPByName(goName);
    if (!obj) return "";
    return ReadStringObj(ReadStringField(obj, g_offTMP_text));
}

// 可配置的额外监视文本（如回合数），由 watch_texts 命令设置
static char g_watchNames[4][64] = {};

void Il2CppUiSetWatchTexts(const char* csv) {
    for (auto& n : g_watchNames) n[0] = 0;
    if (!csv) return;
    int idx = 0;
    const char* p = csv;
    while (*p && idx < 4) {
        const char* comma = strchr(p, ',');
        size_t len = comma ? (size_t)(comma - p) : strlen(p);
        if (len > 0 && len < 64) {
            memcpy(g_watchNames[idx], p, len);
            g_watchNames[idx][len] = 0;
            idx++;
        }
        if (!comma) break;
        p = comma + 1;
    }
}

static bool HeapWalk_GOActive(const char* name) {
    if (!Il2CppReady() || !g_classGameObject) return false;
    struct Ctx { const char* name; bool found; };
    struct Walk {
        static void __cdecl cb(void* c, void* obj, Il2CppClass* klass, void** desc) {
            (void)desc;
            Ctx* x = (Ctx*)c;
            if (x->found) return;
            const char* cname = p_il2cpp_class_get_name(klass);
            if (!cname || strcmp(cname, "GameObject") != 0) return;
            if (!GameObjectActive(obj)) return;
            if (GameObjectName(obj) == x->name) x->found = true;
        }
    };
    Ctx ctx = { name, false };
    p_il2cpp_gc_foreach_heap(&ctx, Walk::cb);
    return ctx.found;
}

// 运行时诊断：把类与字段偏移解析结果一次性报出来（首次实机排查用）
std::string Il2CppUiDumpOffsets() {
    char buf[512];
    snprintf(buf, sizeof(buf),
             "{\"ev\":\"offsets\",\"inited\":%s,\"m_name\":%d,\"m_active\":%d,\"m_gameobj\":%d,"
             "\"btn\":%d,\"go\":%d,\"tr\":%d,\"rt\":%d,\"tmp\":%d,"
             "\"off_onClick\":%zu,\"off_compGO\":%zu,\"off_goName\":%zu,\"off_goActive\":%zu,"
             "\"off_goTr\":%zu,\"off_trParent\":%zu,\"off_tmpText\":%zu}",
             Il2CppReady() ? "true" : "false",
             m_obj_getName ? 1 : 0, m_go_getActiveSelf ? 1 : 0, m_comp_getGameObject ? 1 : 0,
             g_classButton ? 1 : 0, g_classGameObject ? 1 : 0, g_classTransform ? 1 : 0,
             g_classRectTransform ? 1 : 0, g_classTMP ? 1 : 0,
             g_offButton_onClick, g_offComp_GameObject, g_offGO_Name, g_offGO_Active,
             g_offGO_Transform, g_offTransform_Parent, g_offTMP_text);
    return std::string(buf);
}

// ---------- 文本清单 / UI 坐标 ----------
int HeapWalk_DumpTexts(std::vector<std::string>& lines, int limit) {
    if (!Il2CppReady() || !g_classTMP || !g_offTMP_text) return -1;
    struct Ctx { std::vector<std::string>* lines; int limit; };
    struct Walk {
        static void __cdecl cb(void* c, void* obj, Il2CppClass* klass, void** desc) {
            (void)desc;
            Ctx* x = (Ctx*)c;
            if (x->limit <= 0) return;
            const char* cname = p_il2cpp_class_get_name(klass);
            if (!cname || strcmp(cname, "TextMeshProUGUI") != 0) return;
            void* go = GetGameObjectOf(obj);
            if (!go || !GameObjectActive(go)) return;
            std::string nm = GameObjectName(go);
            std::string tx = ReadStringObj(ReadStringField(obj, g_offTMP_text));
            if (tx.size() > 40) tx = tx.substr(0, 40);
            std::string esc;
            for (size_t i = 0; i < tx.size(); i++) {
                if (tx[i] == '"' || tx[i] == '\\') esc += '\\';
                esc += tx[i];
            }
            char line[512];
            snprintf(line, sizeof(line),
                     "{\"ev\":\"ui_text\",\"name\":\"%s\",\"text\":\"%s\"}", nm.c_str(), esc.c_str());
            x->lines->push_back(line);
            x->limit--;
        }
    };
    Ctx ctx = { &lines, limit };
    p_il2cpp_gc_foreach_heap(&ctx, Walk::cb);
    return (int)lines.size();
}

struct WinSearchCtx { HWND best; LONG area; };
static WinSearchCtx g_winSearch;

static BOOL CALLBACK EnumWinProc(HWND h, LPARAM lp) {
    (void)lp;
    DWORD pid = 0;
    GetWindowThreadProcessId(h, &pid);
    if (pid == GetCurrentProcessId() && IsWindowVisible(h)) {
        RECT r;
        GetClientRect(h, &r);
        LONG area = (r.right - r.left) * (r.bottom - r.top);
        if (area > g_winSearch.area) {
            g_winSearch.area = area;
            g_winSearch.best = h;
        }
    }
    return TRUE;
}

static HWND FindOwnMainWindow() {
    g_winSearch.best = nullptr;
    g_winSearch.area = 0;
    EnumWindows(EnumWinProc, 0);
    return g_winSearch.best;
}

// 按 GameObject 名取 UI 元素屏幕坐标（桌面坐标，左上原点）
bool HeapWalk_GetScreenPos(const char* name, int* outX, int* outY) {
    if (!Il2CppReady() || !g_classRectTransform || !g_offComp_GameObject) return false;
    struct Ctx { const char* name; void* found; };
    struct Walk {
        static void __cdecl cb(void* c, void* obj, Il2CppClass* klass, void** desc) {
            (void)desc;
            Ctx* x = (Ctx*)c;
            if (x->found) return;
            const char* cname = p_il2cpp_class_get_name(klass);
            if (!cname || strcmp(cname, "RectTransform") != 0) return;
            void* go = GetGameObjectOf(obj);
            if (!go || !GameObjectActive(go)) return;
            if (GameObjectName(go) == x->name) x->found = obj;
        }
    };
    Ctx ctx = { name, nullptr };
    p_il2cpp_gc_foreach_heap(&ctx, Walk::cb);
    if (!ctx.found) return false;

    const MethodInfo* m = nullptr;
    if (p_il2cpp_class_get_method_from_name) {
        m = p_il2cpp_class_get_method_from_name(g_classRectTransform, "get_position", 0);
        if (!m && g_classTransform)
            m = p_il2cpp_class_get_method_from_name(g_classTransform, "get_position", 0);
    }
    if (!m) return false;
    Il2CppException* exc = nullptr;
    void* ret = p_il2cpp_runtime_invoke(m, ctx.found, nullptr, &exc);
    if (!ret || exc) return false;
    float* v = (float*)ret;
    float ux = v[0], uy = v[1];

    HWND hwnd = FindOwnMainWindow();
    if (!hwnd) return false;
    RECT cr;
    GetClientRect(hwnd, &cr);
    POINT origin = { 0, 0 };
    ClientToScreen(hwnd, &origin);
    int clientH = cr.bottom - cr.top;
    *outX = origin.x + (int)ux;
    *outY = origin.y + (clientH - (int)uy);  // Unity Y 轴向上 → 桌面 Y 轴向下
    return true;
}

// 返回阶段：0=未知 1=准备(商店) 2=战斗；secsOut=倒计时秒数(-1 未知)
int HeapWalk_Phase(int* secsOut) {
    int secs = -1;
    if (!Il2CppReady()) { if (secsOut) *secsOut = secs; return 0; }
    // 走缓存快路径（GC 句柄固定，无全堆遍历）
    std::string t = HeapWalk_GetTMPTextFast("countDown_text");
    if (t.empty()) t = HeapWalk_GetTMPTextFast("CountdownText");
    if (t.empty()) t = HeapWalk_GetTMPTextFast("remainingTime_text");
    if (t.empty() && g_detectedCountdown[0]) t = HeapWalk_GetTMPTextFast(g_detectedCountdown);
    if (!t.empty()) secs = atoi(t.c_str());
    if (secsOut) *secsOut = secs;
    if (HeapWalk_GOActive("battlePage")) return 2;
    if (HeapWalk_GOActive("Shop")) return 1;
    return 0;
}

// 读取配置的监视文本（回合数等），写入调用方提供的字符串（避免返回临时对象，便于 SEH 保护）
void HeapWalk_ReadWatchTextsInto(std::string* out) {
    if (!out) return;
    out->clear();
    bool first = true;
    for (int i = 0; i < 4; i++) {
        if (!g_watchNames[i][0]) continue;
        std::string v = HeapWalk_GetTMPTextFast(g_watchNames[i]);
        for (size_t k = 0; k < v.size(); k++) {
            if (v[k] == '"' || v[k] == '\n' || v[k] == '\r') v[k] = ' ';
        }
        if (!first) out->append("|");
        out->append(v);
        first = false;
    }
}

std::string Il2CppUiReadWatchTexts() {
    std::string out;
    Il2CppUiReadWatchTextsInto(&out);
    return out;
}

static volatile bool g_autoSkip = false;
static volatile int g_autoSkipAt = 0;
static volatile DWORD g_lastSkipTick = 0;
static volatile int g_lastPhase = -1;
static volatile int g_lastSecs = -1;
static volatile DWORD g_lastPhaseReport = 0;
static volatile bool g_lastShopSeen = false;   // 本局是否已见过商店界面
static volatile int g_lastRound = -1;         // 上一次的回合数（备用判据）
static volatile int g_lastElem = -1;         // 上一次元素存在性位图
enum AutoState { ST_IDLE = 0, ST_PREP = 1, ST_BATTLE = 2 };
static volatile int g_autoState = ST_IDLE;       // 自动跳过状态机当前状态
static volatile int g_lastStateBefore = ST_IDLE; // 上一轮状态（用于检测 PREP→BATTLE 跃迁）
static volatile bool g_skipArmed = false;         // 是否已武装（每场战斗只触发一次）
static volatile bool g_shuttingDown = false;      // 游戏退出中：所有循环必须立刻停止调用 il2cpp
static char g_battleKeywords[192] = "开始战斗,战斗开始,开始对决,战斗";  // 可配置
void Il2CppUiSetBattleKeywords(const char* kw) {
    if (kw && *kw) strncpy_s(g_battleKeywords, kw, sizeof(g_battleKeywords) - 1);
    else strncpy_s(g_battleKeywords, "开始战斗,战斗开始,开始对决,战斗", sizeof(g_battleKeywords) - 1);
}
static volatile bool g_skipUseHold = false;      // 跳过方式：true=软断网 hold，false=瞬断 kill
static volatile int g_skipHoldMs = 0;            // 软断网时长(ms)
static volatile bool g_skipFastKill = true;      // 彻底断开：关掉全部套接字

// ================= il2cpp 调用隔离层 =================
// 教训：反射调用（尤其 il2cpp_thread_attach / 类枚举）可能在游戏内挂起。
// 因此所有 il2cpp 调用都只能在专用工作线程上执行，调用方带超时等待；
// 一旦超时，永久熔断反射（g_reflectionBroken），保证命令通道与游戏都不受影响。
enum UiOp {
    OP_NONE = 0, OP_INIT, OP_DUMP_BUTTONS, OP_DUMP_TEXTS, OP_CLICK_BTN,
    OP_CLICK_NTH, OP_UI_POS, OP_PHASE, OP_DETECT_CD, OP_WATCH, OP_OFFSETS, OP_UI_RECT, OP_UI_NTHPOS, OP_PROBE, OP_SNAPSHOT
};

struct UiJob {
    volatile int op;
    char a1[128];
    char a2[128];
    int index;
    std::vector<std::string> lines;
    std::string str;
    int x, y, result, secs, phase, rw, rh;
};

static UiJob g_job;
static HANDLE g_jobDone = nullptr;
static HANDLE g_workerThread = nullptr;
static volatile bool g_jobBusy = false;
static volatile bool g_reflectionBroken = false;
static SRWLOCK g_jobLock = SRWLOCK_INIT;

bool Il2CppUiReflectionBroken() { return g_reflectionBroken; }

static DWORD WINAPI UiWorkerThread(LPVOID) {
    for (;;) {
        if (g_shuttingDown) { Sleep(20); continue; }   // 退出中：不再执行任何任务
        if (!g_jobBusy) { Sleep(3); continue; }
        int op = g_job.op;
        g_job.result = 0;
        {
            char b[96];
            sprintf_s(b, "job op=%d start", op);
            InitLog(b);
        }
        switch (op) {
        case OP_INIT:
            g_job.result = Il2CppUiInit() ? 1 : 0;
            break;
        case OP_DUMP_BUTTONS:
            g_job.result = Il2CppUiDumpButtons(g_job.lines, 400);
            break;
        case OP_DUMP_TEXTS:
            g_job.result = Il2CppUiDumpTexts(g_job.lines, 300);
            break;
        case OP_CLICK_BTN:
            g_job.result = Il2CppUiClickButton(g_job.a1, g_job.a2);
            break;
        case OP_CLICK_NTH:
            g_job.result = Il2CppUiClickNth(g_job.a1, g_job.index);
            break;
        case OP_UI_POS:
            g_job.result = Il2CppUiGetScreenPos(g_job.a1, &g_job.x, &g_job.y) ? 1 : 0;
            break;
        case OP_PHASE:
            g_job.secs = -1;
            g_job.phase = Il2CppUiPhase(&g_job.secs);
            g_job.result = 1;
            break;
        case OP_DETECT_CD:
            g_job.result = Il2CppUiDetectCountdown(g_job.lines);
            break;
        case OP_WATCH:
            Il2CppUiReadWatchTextsInto(&g_job.str);
            g_job.result = 1;
            break;
        case OP_OFFSETS:
            g_job.str = Il2CppUiDumpOffsets();
            g_job.result = 1;
            break;
        case OP_UI_RECT:
            g_job.rw = g_job.rh = 0;
            g_job.result = Il2CppUiGetRect(g_job.a1, &g_job.x, &g_job.y, &g_job.rw, &g_job.rh) ? 1 : 0;
            break;
        case OP_PROBE:
            g_job.result = Il2CppUiProbe();
            break;
        case OP_UI_NTHPOS:
            g_job.result = Il2CppUiNthPos(g_job.a1, g_job.index, &g_job.x, &g_job.y) ? 1 : 0;
            break;
        default:
            break;
        }
        g_job.op = OP_NONE;
        g_jobBusy = false;
        SetEvent(g_jobDone);
        {
            char b[96];
            sprintf_s(b, "job op=%d done result=%d", op, g_job.result);
            InitLog(b);
        }
    }
    return 0;
}

// 提交任务并等待完成。
// 返回 1=成功；0=工作线程忙（上一次调用还没回来，调用方稍后重试）；-1=超时熔断
static int RunUiJob(int op, const char* a1, const char* a2, int index, DWORD timeoutMs) {
    if (g_reflectionBroken || g_shuttingDown) return -1;
    AcquireSRWLockExclusive(&g_jobLock);
    if (!g_jobDone) {
        g_jobDone = CreateEventW(nullptr, FALSE, FALSE, nullptr);
        g_workerThread = CreateThread(nullptr, 0, UiWorkerThread, nullptr, 0, nullptr);
    }
    if (g_jobBusy) {
        // 上一次任务还没跑完：等待它结束再执行本次（而不是直接返回 busy）。
        // 否则上一个耗时命令（如倒计时扫描）进行中时，按钮/文本清单会被跳过，
        // 表现为"清单共 0 个"（实测踩过）。
        // 注意：这里只是"排队等待"，即使等不到也**不熔断** —— 熔断只发生在
        // 真正开始执行任务之后（下面第二处）。否则一次慢任务会让整条反射链永久失效。
        ReleaseSRWLockExclusive(&g_jobLock);
        if (WaitForSingleObject(g_jobDone, timeoutMs) != WAIT_OBJECT_0) {
            PipeSendEventFmt("{\"ev\":\"busy\",\"op\":%d}", op);
            return 0;                    // 稍后重试，不熔断
        }
        AcquireSRWLockExclusive(&g_jobLock);
        if (g_jobBusy) {          // 仍忙（极少见）→ 放弃本次
            ReleaseSRWLockExclusive(&g_jobLock);
            return 0;
        }
    }
    g_job.op = op;
    g_job.a1[0] = g_job.a2[0] = 0;
    if (a1) strncpy_s(g_job.a1, a1, sizeof(g_job.a1) - 1);
    if (a2) strncpy_s(g_job.a2, a2, sizeof(g_job.a2) - 1);
    g_job.index = index;
    g_job.x = g_job.y = 0;
    g_job.secs = -1;
    g_job.lines.clear();
    g_job.str.clear();
    ResetEvent(g_jobDone);
    g_jobBusy = true;
    ReleaseSRWLockExclusive(&g_jobLock);

    if (WaitForSingleObject(g_jobDone, timeoutMs) != WAIT_OBJECT_0) {
        // 只在"工作线程真的卡在 il2cpp 调用里"时才熔断。
        // 判据：g_jobBusy 仍为 true 表示任务还没被 worker 取走或尚未做完。
        //   - 若 g_jobBusy 仍为 true 且已超时 → 真卡死 → 熔断（保护游戏与进程）
        //   - 反之视为"排队/调度抖动" → 不熔断，避免一次偶发慢任务把整条反射链废掉
        //     （实测教训：录制任务与 watch 任务竞争 → watch 超时 → 反射被永久熔断）
        if (g_jobBusy) {
            g_reflectionBroken = true;
            PipeSendEventFmt("{\"ev\":\"reflection_broken\",\"op\":%d}", op);
            return -1;
        }
        return 1;      // 任务实际已完成，视为成功
    }
    return 1;
}

// ---- 供 pipe.cpp 使用的安全入口（-999=超时熔断，-998=忙，其余为业务结果） ----
void Il2CppUiSetInitStep(int step) { g_initMaxStep = step; }

int UiSafeInit() {
    // 反射若已熔断，先尝试恢复（可能只是上一次的偶发慢任务）
    g_reflectionBroken = false;
    int r = RunUiJob(OP_INIT, nullptr, nullptr, 0, 20000);
    if (r == 0) return -998;
    if (r < 0) return -999;
    return g_job.result;
}

int UiSafeDumpButtons(std::vector<std::string>* out) {
    int r = RunUiJob(OP_DUMP_BUTTONS, nullptr, nullptr, 0, 40000);
    if (r == 0) return -998;
    if (r < 0) return -999;
    if (out) *out = g_job.lines;
    return g_job.result;
}

int UiSafeDumpTexts(std::vector<std::string>* out) {
    int r = RunUiJob(OP_DUMP_TEXTS, nullptr, nullptr, 0, 40000);
    if (r == 0) return -998;
    if (r < 0) return -999;
    if (out) *out = g_job.lines;
    return g_job.result;
}

int UiSafeClickButton(const char* name, const char* path) {
    int r = RunUiJob(OP_CLICK_BTN, name, path, 0, 3000);
    if (r == 0) return -998;
    if (r < 0) return -999;
    return g_job.result;
}

int UiSafeClickNth(const char* path, int index) {
    int r = RunUiJob(OP_CLICK_NTH, path, nullptr, index, 3000);
    if (r == 0) return -998;
    if (r < 0) return -999;
    return g_job.result;
}

int UiSafeGetScreenPos(const char* name, int* x, int* y) {
    int r = RunUiJob(OP_UI_POS, name, nullptr, 0, 3000);
    if (r <= 0) return r == 0 ? -998 : -999;
    if (x) *x = g_job.x;
    if (y) *y = g_job.y;
    return g_job.result;
}

int UiSafePhase(int* secs) {
    int r = RunUiJob(OP_PHASE, nullptr, nullptr, 0, 15000);
    if (r <= 0) { if (secs) *secs = -1; return r == 0 ? -998 : -999; }
    if (secs) *secs = g_job.secs;
    return g_job.phase;
}

int UiSafeDetectCountdown(std::vector<std::string>* out) {
    int r = RunUiJob(OP_DETECT_CD, nullptr, nullptr, 0, 40000);
    if (r == 0) return -998;
    if (r < 0) return -999;
    if (out) *out = g_job.lines;
    return g_job.result;
}

int UiSafeWatchTexts(std::string* out) {
    int r = RunUiJob(OP_WATCH, nullptr, nullptr, 0, 1500);
    if (r <= 0) return r == 0 ? -998 : -999;
    if (out) *out = g_job.str;
    return 1;
}

int UiSafeSnapshot(int* n) {
    int r = RunUiJob(OP_SNAPSHOT, nullptr, nullptr, 0, 15000);
    if (n) *n = (r == 1) ? g_job.result : -1;
    return r == 1 ? g_job.result : -1;
}

int UiSafeProbe() {
    int r = RunUiJob(OP_PROBE, nullptr, nullptr, 0, 3000);
    return r == 1 ? g_job.result : -1;
}

int UiSafeNthPos(const char* goName, int index, int* x, int* y) {
    int r = RunUiJob(OP_UI_NTHPOS, goName, nullptr, index, 3000);
    if (r == 0) return -998;
    if (r < 0) return -999;
    if (x) *x = g_job.x;
    if (y) *y = g_job.y;
    return g_job.result;
}

int UiSafeGetRect(const char* name, int* x, int* y, int* w, int* h) {
    int r = RunUiJob(OP_UI_RECT, name, nullptr, 0, 3000);
    if (r == 0) return -998;
    if (r < 0) return -999;
    if (x) *x = g_job.x;
    if (y) *y = g_job.y;
    if (w) *w = g_job.rw;
    if (h) *h = g_job.rh;
    return g_job.result;
}

int UiSafeOffsets(std::string* out) {
    int r = RunUiJob(OP_OFFSETS, nullptr, nullptr, 0, 3000);
    if (r <= 0) return r == 0 ? -998 : -999;
    if (out) *out = g_job.str;
    return 1;
}


static DWORD WINAPI AutoSkipWatcher(LPVOID) {
    for (;;) {
        if (g_shuttingDown) break;          // 游戏退出：线程彻底结束
        Sleep(250);
        if (g_shuttingDown) break;
        if (!g_autoSkip) continue;
        if (Il2CppUiReflectionBroken()) {
            PipeSendEvent("{\"ev\":\"auto_skip_stop\",\"reason\":\"reflection_unavailable\"}");
            g_autoSkip = false;
            continue;
        }
        int secs = -1;
        int phase = UiSafePhase(&secs);
        if (phase == -998) continue;            // 忙，稍后重试
        if (phase == -999) {                     // 反射不可用 → 关闭自动跳过，不影响其它功能
            PipeSendEvent("{\"ev\":\"auto_skip_stop\",\"reason\":\"reflection_timeout\"}");
            g_autoSkip = false;
            continue;
        }

        int roundNo = Il2CppUiRoundNum();      // 回合数（最可靠的"准备结束进战斗"信号）
        DWORD now = GetTickCount();
        if (now - g_lastPhaseReport > 1000) {
            g_lastPhaseReport = now;
            std::string watch;
            if (UiSafeWatchTexts(&watch) == -999) watch.clear();
            if (watch.empty())
                PipeSendEventFmt("{\"ev\":\"phase\",\"phase\":%d,\"secs\":%d,\"round\":%d}", phase, secs, roundNo);
            else
                PipeSendEventFmt("{\"ev\":\"phase\",\"phase\":%d,\"secs\":%d,\"round\":%d,\"watch\":\"%s\"}",
                                 phase, secs, roundNo, watch.c_str());
        }
        // ================= 自动跳过：按「开始战斗」文字触发 =================
        // 用户需求：准备回合结束、战斗开始时屏幕上会显示一段"开始战斗"字样，
        //           就那一刻断网。文字内容是明确信号，不依赖对象名猜测。
        // 流程：扫描全部激活 TMP 文本 → 命中关键字（默认 开始战斗/战斗开始/开始对决）
        //       → 断网一次（每场只触发一次，冷却 8 秒）
        std::string hit = Il2CppUiFindTextByContent(g_battleKeywords);
        bool textHit = !hit.empty();
        if (textHit != (g_autoState == ST_BATTLE)) {
            PipeSendEventFmt("{\"ev\":\"auto_state\",\"from\":%d,\"to\":%d,\"hit\":\"%s\"}",
                             (int)g_autoState, textHit ? (int)ST_BATTLE : (int)ST_IDLE, hit.c_str());
            g_autoState = textHit ? ST_BATTLE : ST_IDLE;
        }
        if (textHit && g_skipArmed && (now - g_lastSkipTick > 8000)) {
            g_lastSkipTick = now;
            g_skipArmed = false;                       // 每场战斗只断一次
            PipeSendEventFmt("{\"ev\":\"auto_skip\",\"phase\":%d,\"secs\":%d,"
                             "\"hit\":\"%s\",\"reason\":\"battle_text\"}",
                             phase, secs, hit.c_str());
            if (g_skipUseHold && g_skipHoldMs > 0) SafeHold(g_skipHoldMs);
            else if (g_skipFastKill) SafeKillAll();
            else SafeKillBattle();
        } else if (textHit) {
            g_skipArmed = false;                       // 文字仍在 → 同一场不重复
        } else {
            g_skipArmed = true;                        // 文字消失（下回合）→ 重新武装
        }
        g_lastStateBefore = (AutoState)g_autoState;
        if (roundNo >= 0) g_lastRound = roundNo;
        g_lastPhase = phase;
        g_lastSecs = secs;
    }
    return 0;
}

void Il2CppUiAutoSkipCfg(int useHold, int holdMs, int fastKill) {
    g_skipUseHold = (useHold != 0);
    g_skipHoldMs = holdMs;
    g_skipFastKill = (fastKill != 0);
}

// 游戏退出前调用：停掉所有会触碰 il2cpp 的线程。
// 根因背景：自动跳过线程每 250ms 调一次 il2cpp；Unity 退出时引擎开始销毁内存，
// 我们正好在调用中间 → 访问已释放内存 → 0xc0000005（用户看到的错误弹窗）。
// 这里不只是"置标志"，还要让所有循环立刻看到标志并退出，不能再发起新调用。
void Il2CppUiShutdown() {
    g_autoSkip = false;              // 自动跳过线程会在下一次循环检查时退出
    g_reflectionBroken = true;       // RunUiJob 入口直接拒绝新任务
    g_shuttingDown = true;           // 关键：全局退出标志（下面所有循环都检查它）
    if (g_workerThread) {
        // 不等待：工作线程可能正卡在 il2cpp 里，等待只会让游戏退出更卡。
        g_job.op = OP_NONE;
        g_jobBusy = false;
        if (g_jobDone) SetEvent(g_jobDone);
    }
}

void Il2CppUiAutoSkipSet(bool on, int atSecs) {
    g_autoSkipAt = atSecs;
    if (on) g_lastShopSeen = false;   // 重新开启时重置商店状态
    if (on && !g_autoSkip) {
        g_autoSkip = true;
        g_lastPhase = -1;
        g_lastSecs = -1;
        CreateThread(nullptr, 0, AutoSkipWatcher, nullptr, 0, nullptr);
    } else if (!on) {
        g_autoSkip = false;
    }
}

#include "unityapi_impl.h"
