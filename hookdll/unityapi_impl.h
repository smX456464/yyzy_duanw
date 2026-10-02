// unityapi_impl.h - Unity API 访问层（替代堆遍历）
// 背景：il2cpp_gc_foreach_heap 的回调签名与 Unity 实际不一致
//（实际为 void(*)(void* obj, void* user_data)），错位后拿垃圾指针当类指针，
// 导致既取不到对象又把工作线程挂死。改用 Unity 自己的查找 API，
// 完全不触碰 GC 内部。
// 本文件被 il2cppui.cpp 末尾 #include，可直接使用其内部静态符号。

static const MethodInfo* m_go_find = nullptr;                // GameObject.Find(string)
static const MethodInfo* m_go_getComponentType = nullptr;    // GameObject.GetComponent(Type)
static const MethodInfo* m_obj_findObjectsOfType = nullptr;  // Object.FindObjectsOfType(Type)
static const MethodInfo* m_ev_invoke = nullptr;              // UnityEvent.Invoke()
static Il2CppClass* g_classUnityObject = nullptr;
static Il2CppClass* g_classUnityEvent = nullptr;

static void CacheUnityApi() {
    if (!p_il2cpp_class_get_method_from_name) return;
    if (g_classGameObject) {
        m_go_find = p_il2cpp_class_get_method_from_name((Il2CppClass*)g_classGameObject, "Find", 1);
        m_go_getComponentType =
            p_il2cpp_class_get_method_from_name((Il2CppClass*)g_classGameObject, "GetComponent", 1);
    }
    g_classUnityObject = FindClass("UnityEngine", "Object");
    if (g_classUnityObject) {
        m_obj_findObjectsOfType =
            p_il2cpp_class_get_method_from_name(g_classUnityObject, "FindObjectsOfType", 1);
    }
    g_classUnityEvent = FindClass("UnityEngine.Events", "UnityEvent");
    if (g_classUnityEvent) {
        m_ev_invoke = p_il2cpp_class_get_method_from_name(g_classUnityEvent, "Invoke", 0);
    }
    char b[200];
    sprintf_s(b, "init: unityapi find=%d getComp=%d findObjs=%d invoke=%d",
              m_go_find ? 1 : 0, m_go_getComponentType ? 1 : 0,
              m_obj_findObjectsOfType ? 1 : 0, m_ev_invoke ? 1 : 0);
    InitLog(b);
}

// ---- 基础调用helpers ----
static Il2CppString* MakeString(const char* utf8) {
    return p_il2cpp_string_new ? p_il2cpp_string_new(utf8) : nullptr;
}

static void* InvokeStatic1(const MethodInfo* m, void* a1) {
    if (!m || !p_il2cpp_runtime_invoke) return nullptr;
    void* args[1] = { a1 };
    Il2CppException* exc = nullptr;
    void* r = p_il2cpp_runtime_invoke((const MethodInfo*)m, nullptr, args, &exc);
    return exc ? nullptr : r;
}

static void* TypeObjectOf(Il2CppClass* klass) {
    if (!klass || !p_il2cpp_class_get_type || !p_il2cpp_type_get_object) return nullptr;
    const void* t = p_il2cpp_class_get_type(klass);
    return t ? p_il2cpp_type_get_object(t) : nullptr;
}

// ---- 查找：GameObject.Find(name) ----
static void* UiFindGameObject(const char* name) {
    if (!m_go_find || !name || !*name) return nullptr;
    Il2CppString* s = MakeString(name);
    if (!s) return nullptr;
    return InvokeStatic1(m_go_find, s);
}

// ---- 取组件：go.GetComponent(Type) ----
static void* UiGetComponent(void* go, Il2CppClass* klass) {
    if (!go || !klass || !m_go_getComponentType) return nullptr;
    void* t = TypeObjectOf(klass);
    if (!t) return nullptr;
    void* args[1] = { t };
    Il2CppException* exc = nullptr;
    void* r = p_il2cpp_runtime_invoke((const MethodInfo*)m_go_getComponentType, go, args, &exc);
    return exc ? nullptr : r;
}

// ---- 枚举：Object.FindObjectsOfType(Type) ----
static void* UiFindObjectsOfType(Il2CppClass* klass) {
    if (!m_obj_findObjectsOfType || !klass) return nullptr;
    void* t = TypeObjectOf(klass);
    if (!t) return nullptr;
    return InvokeStatic1(m_obj_findObjectsOfType, t);
}

// Il2CppArray 布局（x64）：obj(16) + bounds(8) + max_length(4+pad4) → 元素从 32 开始
static int UiArrayLength(void* arr) {
    return arr ? *(int*)((char*)arr + 24) : 0;
}
static void* UiArrayAt(void* arr, int i) {
    if (!arr || i < 0 || i >= UiArrayLength(arr)) return nullptr;
    return *(void**)((char*)arr + 32 + (size_t)i * sizeof(void*));
}

// ---- 读文本：按 GameObject 名找 TMP 组件并读 m_text（偏移 216，实测有效）----
static std::string UiReadTmpTextByName(const char* name) {
    void* go = UiFindGameObject(name);
    if (!go) return std::string();
    void* tmp = UiGetComponent(go, (Il2CppClass*)g_classTMP);
    if (!tmp) return std::string();
    void* s = ReadFieldPtr(tmp, g_offTMP_text);
    if (!s) return std::string();
    return ReadStringObj((Il2CppString*)s);
}

// 从文本里解析第一个整数（支持 "12"、"12s"、"剩余 12 秒"）
static int ParseFirstInt(const std::string& s) {
    int v = 0;
    bool got = false;
    for (size_t i = 0; i < s.size(); i++) {
        if (s[i] >= '0' && s[i] <= '9') {
            got = true;
            v = v * 10 + (s[i] - '0');
            if (v > 9999) return -1;
        } else if (got) {
            break;
        }
    }
    return got ? v : -1;
}

// ================= 对外实现（覆盖旧的堆遍历版本） =================

int Il2CppUiClickButton(const char* name, const char* pathContains) {
    (void)pathContains;
    if (!Il2CppReady() || !g_classButton) return 0;
    void* go = UiFindGameObject(name);
    if (!go) return 0;
    void* btn = UiGetComponent(go, (Il2CppClass*)g_classButton);
    if (!btn) return 0;
    void* ev = ReadFieldPtr(btn, g_offButton_onClick);   // Button.m_OnClick @248
    if (!ev) return 0;
    if (!m_ev_invoke) {
        Il2CppClass* k = (Il2CppClass*)p_il2cpp_object_get_class((Il2CppObject*)ev);
        if (k && p_il2cpp_class_get_method_from_name)
            m_ev_invoke = p_il2cpp_class_get_method_from_name(k, "Invoke", 0);
    }
    if (!m_ev_invoke) return 0;
    Il2CppException* exc = nullptr;
    p_il2cpp_runtime_invoke((const MethodInfo*)m_ev_invoke, ev, nullptr, &exc);
    return exc ? 0 : 1;
}

int Il2CppUiClickNth(const char* pathContains, int index) {
    if (!Il2CppReady() || !g_classButton) return 0;
    void* arr = UiFindObjectsOfType((Il2CppClass*)g_classButton);
    int n = UiArrayLength(arr);
    if (n <= 0) return 0;
    // 收集 (屏幕x, 按钮) 并按 x 排序 → 与堆遍历版本的"从左到右"语义一致
    std::vector<std::pair<int, void*>> items;
    for (int i = 0; i < n; i++) {
        void* btn = UiArrayAt(arr, i);
        if (!btn) continue;
        void* go = GetGameObjectOf(btn);
        if (!go || !GetActiveOf(go)) continue;
        if (pathContains && *pathContains) {
            std::string path = GameObjectPath(go);
            if (path.find(pathContains) == std::string::npos) continue;
        }
        int x = 0, y = 0;
        void* tr = GetTransformOf(go);
        int px = 0;
        if (tr) {
            const MethodInfo* mp = p_il2cpp_class_get_method_from_name
                ? p_il2cpp_class_get_method_from_name((Il2CppClass*)g_classTransform, "get_position", 0) : nullptr;
            if (mp) {
                Il2CppException* e2 = nullptr;
                void* boxed = p_il2cpp_runtime_invoke(mp, tr, nullptr, &e2);
                if (boxed && !e2 && p_il2cpp_object_unbox) {
                    float* v = (float*)p_il2cpp_object_unbox(boxed);
                    if (v) px = (int)v[0];
                }
            }
        }
        items.push_back(std::make_pair(px, btn));
    }
    if (items.empty()) return 0;
    std::sort(items.begin(), items.end(),
              [](const std::pair<int, void*>& a, const std::pair<int, void*>& b) { return a.first < b.first; });
    if (index < 0 || index >= (int)items.size()) return 0;
    void* btn = items[index].second;
    void* ev = ReadFieldPtr(btn, g_offButton_onClick);
    if (!ev) return 0;
    if (!m_ev_invoke) {
        Il2CppClass* k = (Il2CppClass*)p_il2cpp_object_get_class((Il2CppObject*)ev);
        if (k && p_il2cpp_class_get_method_from_name)
            m_ev_invoke = p_il2cpp_class_get_method_from_name(k, "Invoke", 0);
    }
    if (!m_ev_invoke) return 0;
    Il2CppException* exc = nullptr;
    p_il2cpp_runtime_invoke((const MethodInfo*)m_ev_invoke, ev, nullptr, &exc);
    return exc ? 0 : 1;
}

bool Il2CppUiGetScreenPos(const char* name, int* outX, int* outY) {
    if (!Il2CppReady() || !name || !*name) return false;
    void* go = UiFindGameObject(name);
    if (!go) return false;
    void* comp = UiGetComponent(go, (Il2CppClass*)g_classRectTransform);
    if (!comp) comp = UiGetComponent(go, (Il2CppClass*)g_classTransform);
    if (!comp) comp = go;   // GameObject 本身也可取 get_transform
    if (!g_classTransform || !p_il2cpp_class_get_method_from_name) return false;
    const MethodInfo* m = p_il2cpp_class_get_method_from_name((Il2CppClass*)g_classTransform, "get_position", 0);
    if (!m) return false;
    Il2CppException* exc = nullptr;
    void* boxed = p_il2cpp_runtime_invoke(m, comp, nullptr, &exc);
    if (!boxed || exc || !p_il2cpp_object_unbox) return false;
    float* v = (float*)p_il2cpp_object_unbox(boxed);
    if (!v) return false;
    HWND hwnd = FindOwnMainWindow();
    if (!hwnd) return false;
    RECT cr;
    GetClientRect(hwnd, &cr);
    POINT origin = { 0, 0 };
    ClientToScreen(hwnd, &origin);
    int clientH = cr.bottom - cr.top;
    *outX = origin.x + (int)v[0];
    *outY = origin.y + (clientH - (int)v[1]);   // Unity Y 向上 → 屏幕 Y 向下
    return true;
}

int Il2CppUiPhase(int* secsOut) {
    if (secsOut) *secsOut = -1;
    if (!Il2CppReady() || !g_classGameObject) return 0;

    // 倒计时：先试常见对象名，再试配置的监视名
    static const char* kCdNames[] = { "countDown_text", "CountdownText", "remainingTime_text",
                                      "timeText", "TimerText" };
    int secs = -1;
    for (int i = 0; i < 5 && secs < 0; i++) {
        std::string t = UiReadTmpTextByName(kCdNames[i]);
        if (!t.empty()) secs = ParseFirstInt(t);
    }
    for (int i = 0; i < 4 && secs < 0; i++) {
        if (!g_watchNames[i][0]) continue;
        std::string t = UiReadTmpTextByName(g_watchNames[i]);
        if (!t.empty()) secs = ParseFirstInt(t);
    }
    if (secsOut) *secsOut = secs;

    void* battle = UiFindGameObject("battlePage");
    if (battle && GetActiveOf(battle)) return 2;
    void* shop = UiFindGameObject("Shop");
    if (shop && GetActiveOf(shop)) return 1;
    return 0;
}

void Il2CppUiReadWatchTextsInto(std::string* out) {
    if (!out) return;
    out->clear();
    bool first = true;
    for (int i = 0; i < 4; i++) {
        if (!g_watchNames[i][0]) continue;
        std::string v = UiReadTmpTextByName(g_watchNames[i]);
        for (size_t k = 0; k < v.size(); k++)
            if (v[k] == '"' || v[k] == '\n' || v[k] == '\r') v[k] = ' ';
        if (!first) out->append("|");
        out->append(v);
        first = false;
    }
}

int Il2CppUiDumpButtons(std::vector<std::string>& lines, int limit) {
    if (!Il2CppReady() || !g_classButton) return 0;
    void* arr = UiFindObjectsOfType((Il2CppClass*)g_classButton);
    int n = UiArrayLength(arr);
    for (int i = 0; i < n && (int)lines.size() < limit; i++) {
        void* btn = UiArrayAt(arr, i);
        if (!btn) continue;
        void* go = GetGameObjectOf(btn);
        if (!go) continue;
        if (!GetActiveOf(go)) continue;
        std::string nm = GameObjectName(go);
        std::string path = GameObjectPath(go);
        lines.push_back(nm + "|" + path);
    }
    return (int)lines.size();
}

int Il2CppUiDumpTexts(std::vector<std::string>& lines, int limit) {
    if (!Il2CppReady() || !g_classTMP) return 0;
    void* arr = UiFindObjectsOfType((Il2CppClass*)g_classTMP);
    int n = UiArrayLength(arr);
    for (int i = 0; i < n && (int)lines.size() < limit; i++) {
        void* tmp = UiArrayAt(arr, i);
        if (!tmp) continue;
        void* s = ReadFieldPtr(tmp, g_offTMP_text);
        if (!s) continue;
        std::string txt = ReadStringObj((Il2CppString*)s);
        if (txt.empty()) continue;
        void* go = GetGameObjectOf(tmp);
        std::string nm = go ? GameObjectName(go) : std::string("?");
        lines.push_back(nm + "|" + txt);
    }
    return (int)lines.size();
}

// ---- 取 UI 元素的矩形（位置 + 尺寸），用于"容器均分"式卡位点击 ----
// RectTransform.get_rect() 返回 UnityEngine.Rect（x,y,width,height 四个 float）
bool Il2CppUiGetRect(const char* name, int* x, int* y, int* w, int* h) {
    if (!Il2CppReady() || !name || !*name) return false;
    void* go = UiFindGameObject(name);
    if (!go) return false;
    void* rt = UiGetComponent(go, (Il2CppClass*)g_classRectTransform);
    if (!rt) return false;
    if (!p_il2cpp_class_get_method_from_name || !p_il2cpp_object_unbox) return false;
    Il2CppClass* k = (Il2CppClass*)p_il2cpp_object_get_class((Il2CppObject*)rt);
    const MethodInfo* mRect = p_il2cpp_class_get_method_from_name(k, "get_rect", 0);
    const MethodInfo* mPos = p_il2cpp_class_get_method_from_name((Il2CppClass*)g_classTransform, "get_position", 0);
    if (!mRect || !mPos) return false;
    Il2CppException* e1 = nullptr;
    void* boxedRect = p_il2cpp_runtime_invoke(mRect, rt, nullptr, &e1);
    if (!boxedRect || e1) return false;
    float* r = (float*)p_il2cpp_object_unbox(boxedRect);
    if (!r) return false;
    Il2CppException* e2 = nullptr;
    void* boxedPos = p_il2cpp_runtime_invoke(mPos, rt, nullptr, &e2);
    if (!boxedPos || e2) return false;
    float* p = (float*)p_il2cpp_object_unbox(boxedPos);
    if (!p) return false;

    HWND hwnd = FindOwnMainWindow();
    if (!hwnd) return false;
    RECT cr;
    GetClientRect(hwnd, &cr);
    POINT origin = { 0, 0 };
    ClientToScreen(hwnd, &origin);
    int clientH = cr.bottom - cr.top;
    // RectTransform 锚点居中时，position 是中心；rect.x/y 是相对中心的左下角
    *x = origin.x + (int)(p[0] + r[0]);
    *y = origin.y + (int)(clientH - (p[1] + r[1] + r[3]));
    *w = (int)r[2];
    *h = (int)r[3];
    return (*w > 0 && *h > 0);
}
// ================= 倒计时识别（Unity API 版，不再用堆遍历） =================
static std::vector<std::pair<std::string, int>> g_cdSample;

void Il2CppUiResetCountdownDetect() { g_cdSample.clear(); }

int Il2CppUiDetectCountdown(std::vector<std::string>& report) {
    if (!Il2CppReady() || !g_classTMP) return 0;
    void* arr = UiFindObjectsOfType((Il2CppClass*)g_classTMP);
    int n = UiArrayLength(arr);
    std::vector<std::pair<std::string, int>> now;
    for (int i = 0; i < n && (int)now.size() < 400; i++) {
        void* tmp = UiArrayAt(arr, i);
        if (!tmp) continue;
        void* s = ReadFieldPtr(tmp, g_offTMP_text);
        if (!s) continue;
        std::string txt = ReadStringObj((Il2CppString*)s);
        int v = ParseFirstInt(txt);
        if (v < 0) continue;                      // 只看纯数字类文本
        void* go = GetGameObjectOf(tmp);
        if (!go) continue;
        std::string nm = GameObjectName(go);   // 不再做激活检查：省一次方法调用，显著提速
        if (nm.empty()) continue;
        now.push_back(std::make_pair(nm, v));
    }
    if (g_cdSample.empty()) {                     // 第一次采样
        g_cdSample = now;
        char b[96];
        sprintf_s(b, "cd detect: first sample n=%d", (int)now.size());
        InitLog(b);
        return 0;
    }
    int found = 0;
    for (size_t i = 0; i < now.size() && found < 8; i++) {
        for (size_t j = 0; j < g_cdSample.size(); j++) {
            if (g_cdSample[j].first == now[i].first && now[i].second < g_cdSample[j].second) {
                report.push_back(now[i].first);   // 数值在减少 → 倒计时
                found++;
                break;
            }
        }
    }
    char b[128];
    sprintf_s(b, "cd detect: second sample n=%d found=%d", (int)now.size(), found);
    InitLog(b);
    g_cdSample.clear();
    return found;
}
// ---- 取第 N 个同名/同类型 UI 对象的屏幕坐标（按横坐标排序，不点击）----
bool Il2CppUiNthPos(const char* goName, int index, int* outX, int* outY) {
    if (!Il2CppReady() || !goName || !*goName) return false;
    void* arr = UiFindObjectsOfType((Il2CppClass*)g_classButton);
    int n = UiArrayLength(arr);
    if (n <= 0) return false;
    std::vector<std::pair<int, void*>> items;
    for (int i = 0; i < n; i++) {
        void* btn = UiArrayAt(arr, i);
        if (!btn) continue;
        void* go = GetGameObjectOf(btn);
        if (!go) continue;
        std::string nm = GameObjectName(go);
        if (nm != goName) continue;                 // 名字必须完全一致
        void* tr = GetTransformOf(go);
        if (!tr) continue;
        const MethodInfo* mp = p_il2cpp_class_get_method_from_name
            ? p_il2cpp_class_get_method_from_name((Il2CppClass*)g_classTransform, "get_position", 0) : nullptr;
        if (!mp) continue;
        Il2CppException* e = nullptr;
        void* boxed = p_il2cpp_runtime_invoke(mp, tr, nullptr, &e);
        if (!boxed || e || !p_il2cpp_object_unbox) continue;
        float* v = (float*)p_il2cpp_object_unbox(boxed);
        if (!v) continue;
        items.push_back(std::make_pair((int)v[0], btn));
    }
    if (items.empty()) return false;
    std::sort(items.begin(), items.end(),
              [](const std::pair<int, void*>& a, const std::pair<int, void*>& b) { return a.first < b.first; });
    if (index < 0 || index >= (int)items.size()) return false;
    void* btn = items[index].second;
    void* go = GetGameObjectOf(btn);
    void* tr = GetTransformOf(go);
    const MethodInfo* mp = p_il2cpp_class_get_method_from_name((Il2CppClass*)g_classTransform, "get_position", 0);
    if (!tr || !mp) return false;
    Il2CppException* e = nullptr;
    void* boxed = p_il2cpp_runtime_invoke(mp, tr, nullptr, &e);
    if (!boxed || e || !p_il2cpp_object_unbox) return false;
    float* v = (float*)p_il2cpp_object_unbox(boxed);
    if (!v) return false;
    HWND hwnd = FindOwnMainWindow();
    if (!hwnd) return false;
    RECT cr;
    GetClientRect(hwnd, &cr);
    POINT origin = { 0, 0 };
    ClientToScreen(hwnd, &origin);
    int clientH = cr.bottom - cr.top;
    *outX = origin.x + (int)v[0];
    *outY = origin.y + (clientH - (int)v[1]);
    return true;
}
// ---- 阶段判断（不依赖猜名字）：商店界面是否在、倒计时是否在 ----
// 实测教训：原先判"战斗阶段"靠一个猜出来的对象名 battlePage，游戏里并不存在
// → 阶段永远到不了 2 → 自动跳过永不触发。改用行为判断：
//   商店界面消失（且倒计时仍在）＝ 已从准备阶段进入战斗。
bool Il2CppUiShopActive() {
    if (!Il2CppReady()) return false;
    void* shop = UiFindGameObject("Shop");
    return shop && GetActiveOf(shop);
}

bool Il2CppUiCountdownPresent() {
    if (!Il2CppReady()) return false;
    static const char* kCdNames[] = { "countDown_text", "CountdownText", "remainingTime_text" };
    for (int i = 0; i < 3; i++) {
        std::string t = UiReadTmpTextByName(kCdNames[i]);
        if (!t.empty()) return true;
    }
    for (int i = 0; i < 4; i++) {
        if (!g_watchNames[i][0]) continue;
        std::string t = UiReadTmpTextByName(g_watchNames[i]);
        if (!t.empty()) return true;
    }
    return false;
}
// ---- 读取当前回合数（用于"回合推进 = 准备结束进入战斗"这一最可靠信号）----
// 实测教训：靠"倒计时归零"判定会漏 —— 轮询间隔内 0 可能采样不到（43 直接跳到 69）。
// 回合数增加是稳定事件，用它触发跳过最可靠。
int Il2CppUiRoundNum() {
    if (!Il2CppReady()) return -1;
    static const char* kNames[] = { "round_text", "title_text", "roundText" };
    for (int i = 0; i < 3; i++) {
        std::string t = UiReadTmpTextByName(kNames[i]);
        if (t.empty()) continue;
        int v = ParseFirstInt(t);
        if (v >= 0) return v;
    }
    return -1;
}
// ---- 实时探针：一次性把"对局相关的关键对象"全部探一遍（用于定位战斗/准备阶段特征）----
// 输出形如: shop=1 battle=0 cd=1 round=3 ready=1 ...
int Il2CppUiProbe() {
    if (!Il2CppReady()) return -1;
    static const char* kNames[] = {
        "Shop", "shop", "ShopPanel", "battlePage", "BattlePage", "BattlePanel",
        "countDown_text", "CountdownText", "round_text", "title_text", "ready_text",
        "Refresh_btn", "Ready_btn", "clickPanel", "FoughtPanel", "PVPanel"
    };
    std::string out;
    for (int i = 0; i < 15; i++) {
        void* go = UiFindGameObject(kNames[i]);
        bool found = (go != nullptr);
        if (found) {
            found = GetActiveOf(go);      // 同时报告"存在且激活"
        }
        out += found ? "1" : "0";
    }
    PipeSendEventFmt("{\"ev\":\"probe\",\"bits\":\"%s\"}", out.c_str());
    return (int)out.size();
}
// ---- 元素存在性判定（不再依赖倒计时数值）----
// 用户反馈：倒计时不可靠（有人提前点准备会直接进入战斗，倒计时会跳变）。
// 改为只看"界面元素是否出现/消失"：
//   准备阶段特征元素：ready_text（准备按钮文字）、Refresh_btn（刷新按钮）
//   进入战斗时：这些准备阶段元素消失
// 返回 bit0=准备阶段元素在, bit1=商店面板在, bit2=倒计时元素在
int Il2CppUiElementState() {
    if (!Il2CppReady()) return -1;
    auto existsActive = [](const char* n) -> bool {
        void* go = UiFindGameObject(n);
        return go && GetActiveOf(go);
    };
    bool ready = existsActive("ready_text") || existsActive("Ready_btn");
    bool shop = existsActive("Shop") || existsActive("clickPanel") || existsActive("ShopCardArea");
    bool cd = existsActive("countDown_text") || existsActive("CountdownText");
    return (ready ? 1 : 0) | (shop ? 2 : 0) | (cd ? 4 : 0);
}
// ---- 按「文字内容」检测战斗开始（用户需求：显示"开始战斗"字样时断网）----
// 做法：遍历所有激活的 TMP 文本，检查内容是否包含关键字（如"开始战斗"/"战斗开始"）。
// 优点：不依赖任何对象名猜测 —— 文字内容是明确信号。
// 返回命中的对象名（写入 outName），未命中返回空串。
static std::string Il2CppUiFindTextByContent(const char* keywords) {
    std::string out;
    if (!Il2CppReady() || !g_classTMP || !g_offTMP_text || !keywords || !*keywords) return out;
    void* arr = UiFindObjectsOfType((Il2CppClass*)g_classTMP);
    int n = UiArrayLength(arr);
    for (int i = 0; i < n; i++) {
        void* tmp = UiArrayAt(arr, i);
        if (!tmp) continue;
        void* s = ReadFieldPtr(tmp, g_offTMP_text);
        if (!s) continue;
        std::string txt = ReadStringObj((Il2CppString*)s);
        if (txt.empty()) continue;
        // 逗号分隔的多个关键字，任一命中即可
        const char* p = keywords;
        while (*p) {
            const char* comma = strchr(p, ',');
            size_t len = comma ? (size_t)(comma - p) : strlen(p);
            if (len > 0) {
                std::string key(p, len);
                if (txt.find(key) != std::string::npos) {
                    void* go = GetGameObjectOf(tmp);
                    out = go ? GameObjectName(go) : std::string("(未知)");
                    return out;
                }
            }
            if (!comma) break;
            p = comma + 1;
        }
    }
    return out;
}
// ================= 全量快照：抓取游戏里所有 GameObject + 文本内容 =================
// 目的：把"战斗开始那一刻"屏幕上到底有什么元素/文字，全部记录下来，
//       用于确定自动断网的可靠判据（不再靠猜对象名）。
// 输出：每行 "kind\tname\tactive\ttext"（kind: go / tmp）
int Il2CppUiSnapshotAll(int maxItems) {
    if (!Il2CppReady()) return 0;
    int count = 0;
    auto emit = [&](const char* kind, Il2CppClass* klass, int cap) {
        void* arr = UiFindObjectsOfType(klass);
        int n = UiArrayLength(arr);
        for (int i = 0; i < n && count < maxItems; i++) {
            void* obj = UiArrayAt(arr, i);
            if (!obj) continue;
            void* go = GetGameObjectOf(obj);
            if (!go) continue;
            std::string nm = GameObjectName(go);
            if (nm.empty()) continue;
            bool act = GetActiveOf(go);
            std::string txt;
            if (std::strcmp(kind, "tmp") == 0 && g_offTMP_text) {
                void* s = ReadFieldPtr(obj, g_offTMP_text);
                if (s) txt = ReadStringObj((Il2CppString*)s);
                for (auto& ch : txt) { if (ch == '\n' || ch == '\r' || ch == '\t') ch = ' '; }
            }
            char line[768];
            snprintf(line, sizeof(line), "%s\t%s\t%d\t%s", kind, nm.c_str(), act ? 1 : 0, txt.c_str());
            PipeSendEvent(line);          // 裸文本行（由 python 侧写入文件）
            count++;
        }
    };
    // 关键 UI 类型（先记录各类型数组长度 —— 快照抓到 0 个时用它定位）
    void* a1 = g_classTMP ? UiFindObjectsOfType((Il2CppClass*)g_classTMP) : nullptr;
    void* a2 = g_classButton ? UiFindObjectsOfType((Il2CppClass*)g_classButton) : nullptr;
    void* a3 = g_classRectTransform ? UiFindObjectsOfType((Il2CppClass*)g_classRectTransform) : nullptr;
    {
        char b[192];
        snprintf(b, sizeof(b), "snapshot: tmp=%d(cls=%d off=%d) btn=%d rt=%d ready=%d",
                 UiArrayLength(a1), g_classTMP ? 1 : 0, g_offTMP_text ? 1 : 0,
                 UiArrayLength(a2), UiArrayLength(a3), Il2CppReady() ? 1 : 0);
        InitLog(b);
    }
    if (g_classTMP && a1) emit("tmp", (Il2CppClass*)g_classTMP, 400);
    if (g_classButton && a2) emit("btn", (Il2CppClass*)g_classButton, 200);
    if (g_classRectTransform && a3) emit("rt", (Il2CppClass*)g_classRectTransform, 300);
    return count;
}