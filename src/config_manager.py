"""配置管理：TOML 读写 + 默认值 + 迁移 + 规则规范化"""
import os
import sys
import re
import tomlkit
from tomlkit import comment, nl, table, aot

import sys as _sys
if getattr(_sys, "frozen", False):
    # PyInstaller 打包后：配置跟着 exe 走，不在临时解压目录
    SCRIPT_DIR = os.path.dirname(_sys.executable)
else:
    SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(SCRIPT_DIR, "config")
CONFIG_TOML = os.path.join(CONFIG_DIR, "config.toml")
TEMPLATES_TOML = os.path.join(CONFIG_DIR, "templates.toml")
STATE_TOML = os.path.join(CONFIG_DIR, "state.toml")

MUTEX_NAME = "Global\\MoonlightBlockerTool"
DEFAULT_GAME_NAME = "Night of the Full Moon.exe"
DEFAULT_ID_REGEX = r"[\u4e00-\u9fa5A-Za-z0-9]{2,16}"

DEFAULT_CONFIG = {
    "block_time": 5,
    "sound_volume_view_path": "",
    "volume_enabled": True,
    "volume_mute_value": 0,
    "launch_app": "default",
    "block_targets": ["default"],
    "ping_target": "qq.com",
    "auto_exit_on_game_exit": True,
    "ui": {
        "window_width": 200, "window_height": 200,
        "bg_color": "#E0E0E0", "drag_color": "#D0D0D0",
        "transparent_color": "#00FF00",
        "long_press_ms": 2000, "toggle_click_delay_ms": 500,
        "exit_reload_long_press_ms": 3000,
        "log_window": {"width": 460, "height": 340},
        "md_window": {"width": 400, "height": 300,
                      "font_family": "微软雅黑", "font_size": 10,
                      "font_color": "#000000", "bg_color": "#FFFFFF"},
        "ocr_dialog": {"width": 560, "height": 600},
        "rule_dialog": {"width": 720, "height": 640},
        "hotkeys": {"enabled": False},
    },
    "timing": {
        "clock_interval_ms": 200, "animation_interval_ms": 1000,
        "ping_interval_s": 3, "game_monitor_interval_s": 3,
    },
    "img_watch": {
        "enabled": True, "interval": 1.0, "consecutive": 2, "cooldown": 10.0,
        "debug_log": True, "debug_overlay": True, "show_rule_name": False, "scan_all": False,
        "require_foreground": False,
        "auto_mute_when_hidden": False, "visibility_check_interval_s": 5.0,
    },
}

PRESET_WHITELIST = []
PRESET_BLACKLIST = []

# 引导规则：当某个分辨率下没有任何规则时，用它作为规则管理对话框的初始内容
PRESET_GUIDE_WHITELIST = [
    {"name": "主要规则",
     "x1": 0.4503, "y1": 0.0494, "x2": 0.5424, "y2": 0.0783,
     "ocr_text": r"[\u4e00-\u9fa5A-Za-z0-9]{2,16}",
     "match_mode": "regex",
     "note": "框选出对手的名字，位置在经验条附近"},
]

PRESET_GUIDE_BLACKLIST = [
    {"name": "准备",
     "x1": 0.6622, "y1": 0.3494, "x2": 0.7007, "y2": 0.4633,
     "ocr_text": "准备",
     "match_mode": "contains",
     "note": '画个框，框选中"准备"两字'},
    {"name": "选择",
     "x1": 0.4392, "y1": 0.0006, "x2": 0.5608, "y2": 0.0783,
     "ocr_text": r"(?:/|选择)",
     "match_mode": "regex",
     "note": '画个框，框选中"经验值"，商店第二张卡牌的名字'},
    {"name": "商店",
     "x1": 0.4684, "y1": 0.1256, "x2": 0.5295, "y2": 0.1572,
     "ocr_text": "商店",
     "match_mode": "contains",
     "note": '画个框，框选中"商店"两字，点击图鉴就能看到商店'},
    {"name": "卡牌介绍1",
     "x1": 0.3337, "y1": 0.2056, "x2": 0.424, "y2": 0.2572,
     "ocr_text": r'(?:[:：+"",，*\-()（）]+|歌声|咒术|友方|经验|伤害|护盾|随从|糖霜|遗言|入场|先手|绽放|疯狂|手牌|复制|成长)',
     "match_mode": "regex",
     "note": "画个框，框选中第一张卡牌介绍"},
    {"name": "卡牌介绍2",
     "x1": 0.4542, "y1": 0.2056, "x2": 0.5441, "y2": 0.2644,
     "ocr_text": r'(?:[:：+"",，*\-()（）]+|歌声|咒术|友方|经验|伤害|护盾|随从|糖霜|遗言|入场|先手|绽放|疯狂|手牌|复制|成长)',
     "match_mode": "regex",
     "note": "画个框，框选中第二张卡牌介绍"},
    {"name": "卡牌介绍3",
     "x1": 0.5736, "y1": 0.2072, "x2": 0.6667, "y2": 0.2622,
     "ocr_text": r'(?:[:：+"",，*\-()（）]+|歌声|咒术|友方|经验|伤害|护盾|随从|糖霜|遗言|入场|先手|绽放|疯狂|手牌|复制|成长)',
     "match_mode": "regex",
     "note": "画个框，框选中第三张卡牌介绍"},
    {"name": "重连气泡",
     "x1": 0.4045, "y1": 0.3017, "x2": 0.5972, "y2": 0.3622,
     "ocr_text": "重连",
     "match_mode": "contains",
     "note": "断网时，游戏会弹出重连气泡，捕捉它快速恢复网络"},
]


def guide_rules():
    """返回一份引导用的初始规则（深拷贝），用于空白分辨率的初始填充"""
    return {
        "whitelist": deep_copy(PRESET_GUIDE_WHITELIST),
        "blacklist": deep_copy(PRESET_GUIDE_BLACKLIST),
    }


def build_effective_rules(templates, size_key):
    """只返回指定分辨率自己的规则。没有就返回空。

    不再有 default 兜底——每个分辨率一份独立数据。
    返回 (merged, stats)：
      merged = {'whitelist': [...], 'blacklist': [...]}
               每条规则带 '_source' = 'exact'
      stats  = {'exact': N, 'default': 0}
    """
    exact = templates.get(size_key, {}) if isinstance(templates, dict) else {}
    if not isinstance(exact, dict): exact = {}
    exact = migrate_old_template(exact)

    merged = {"whitelist": [], "blacklist": []}
    for kind in ("whitelist", "blacklist"):
        for r in (exact.get(kind, []) or []):
            if isinstance(r, dict):
                r2 = dict(r)
                r2["_source"] = "exact"
                merged[kind].append(r2)

    n_exact = sum(len(merged[k]) for k in ("whitelist", "blacklist"))
    return merged, {"exact": n_exact, "default": 0}


def apply_default_inheritance(templates):
    """把 default 的规则按名字继承到所有分辨率下。
    - 同名规则：保留 size_key 下用户自己的版本
    - 缺的规则：从 default 复制过来
    - default 本身不动
    """
    if not isinstance(templates, dict): return templates
    default_tpl = templates.get("default", {})
    if not isinstance(default_tpl, dict): return templates
    def_wl = default_tpl.get("whitelist", [])
    if not isinstance(def_wl, list): def_wl = []
    def_bl = default_tpl.get("blacklist", [])
    if not isinstance(def_bl, list): def_bl = []
    if not def_wl and not def_bl:
        return templates
    for size_key, tpl in templates.items():
        if size_key == "default": continue
        if not isinstance(tpl, dict): continue
        wl = tpl.get("whitelist", [])
        if not isinstance(wl, list): wl = []
        bl = tpl.get("blacklist", [])
        if not isinstance(bl, list): bl = []
        wl_names = set(r.get("name", "") for r in wl if isinstance(r, dict))
        bl_names = set(r.get("name", "") for r in bl if isinstance(r, dict))
        for r in def_wl:
            if not isinstance(r, dict): continue
            if r.get("name", "") not in wl_names:
                wl.append(deep_copy(r))
        for r in def_bl:
            if not isinstance(r, dict): continue
            if r.get("name", "") not in bl_names:
                bl.append(deep_copy(r))
        tpl["whitelist"] = wl
        tpl["blacklist"] = bl
    return templates

DEFAULT_STATE = {
    "window_x": None, "window_y": None,
    "md_window_x": None, "md_window_y": None,
    "md_window_width": None, "md_window_height": None,
    "md_scroll_pos": 0.0,
}

_config_verbose_printed = False


def deep_copy(d):
    if isinstance(d, dict): return {k: deep_copy(v) for k, v in d.items()}
    if isinstance(d, list): return [deep_copy(x) for x in d]
    return d


def merge_defaults(data, defaults):
    if not isinstance(data, dict): return deep_copy(defaults)
    out = {}
    for k, v in defaults.items():
        if k in data:
            if isinstance(v, dict) and isinstance(data[k], dict):
                out[k] = merge_defaults(data[k], v)
            else:
                out[k] = data[k]
        else:
            out[k] = deep_copy(v)
    for k, v in data.items():
        if k not in out: out[k] = v
    return out


def doc_to_dict(obj):
    if isinstance(obj, dict): return {k: doc_to_dict(v) for k, v in obj.items()}
    if isinstance(obj, list): return [doc_to_dict(x) for x in obj]
    return obj


def rule_has_roi(rule):
    if not isinstance(rule, dict): return False
    try:
        return all(rule.get(k) is not None for k in ("x1", "y1", "x2", "y2"))
    except:
        return False


def rule_roi(rule):
    return (float(rule["x1"]), float(rule["y1"]),
            float(rule["x2"]), float(rule["y2"]))


def normalize_rule(rule, default_name="未命名"):
    r = {
        "name": rule.get("name", default_name),
        "ocr_text": rule.get("ocr_text", ""),
        "match_mode": rule.get("match_mode", "contains"),
        "note": rule.get("note", ""),
        "exclude_text": rule.get("exclude_text", ""),
    }
    for k in ("x1", "y1", "x2", "y2"):
        v = rule.get(k, None)
        r[k] = float(v) if v is not None else None
    return r


def migrate_old_template(tpl):
    if not isinstance(tpl, dict):
        return {"whitelist": [], "blacklist": []}
    if "whitelist" in tpl or "blacklist" in tpl:
        wl = tpl.get("whitelist", [])
        if not isinstance(wl, list): wl = []
        bl = tpl.get("blacklist", [])
        if isinstance(bl, dict):
            bl = [bl] if (rule_has_roi(bl) or bl.get("words")) else []
        if not isinstance(bl, list): bl = []
        return {
            "whitelist": [normalize_rule(r) for r in wl if isinstance(r, dict)],
            "blacklist": [normalize_rule(r) for r in bl if isinstance(r, dict)],
        }
    new = {"whitelist": [], "blacklist": []}
    if rule_has_roi(tpl):
        new["whitelist"].append(normalize_rule(tpl, default_name="主要规则"))
    return new


def ensure_preset_rules(tpl):
    if not isinstance(tpl, dict): tpl = {}
    wl = tpl.get("whitelist", [])
    if not isinstance(wl, list): wl = []
    bl = tpl.get("blacklist", [])
    if not isinstance(bl, list): bl = []
    existing_wl = set(r.get("name", "") for r in wl if isinstance(r, dict))
    existing_bl = set(r.get("name", "") for r in bl if isinstance(r, dict))
    for p in PRESET_WHITELIST:
        if p["name"] not in existing_wl:
            wl.append({"name": p["name"], "x1": None, "y1": None,
                       "x2": None, "y2": None,
                       "ocr_text": p["ocr_text"], "match_mode": p["match_mode"]})
    for p in PRESET_BLACKLIST:
        if p["name"] not in existing_bl:
            bl.append({"name": p["name"], "x1": None, "y1": None,
                       "x2": None, "y2": None,
                       "ocr_text": p["ocr_text"], "match_mode": p["match_mode"]})
    tpl["whitelist"] = wl
    tpl["blacklist"] = bl
    return tpl


def _add_kv(node, key, value, comments=None):
    if comments:
        for c in comments: node.add(comment(c))
    node[key] = value
    node.add(nl())


def build_config_doc(cfg):
    doc = tomlkit.document()
    doc.add(comment("版本：1.0  |  项目主页：https://github.com/smX456464"))
    doc.add(comment("=" * 52))
    doc.add(comment("月圆之夜断网工具 配置文件"))
    doc.add(comment("修改后重启工具，或长按 ✕ 3 秒重载生效"))
    doc.add(comment("=" * 52))
    doc.add(nl())

    _add_kv(doc, "block_time", cfg["block_time"], ["断网持续秒数（1-3600）"])
    _add_kv(doc, "volume_enabled", cfg.get("volume_enabled", True),
            ["是否显示 🔊 音量按钮（设为 false 后按钮消失，需改回 true 才恢复）"])
    _add_kv(doc, "sound_volume_view_path", cfg["sound_volume_view_path"],
            ["SoundVolumeView.exe 路径（下载后自动填，也可手动填）"])
    _add_kv(doc, "volume_mute_value", cfg["volume_mute_value"], ["静音值（0-100）"])
    _add_kv(doc, "launch_app", cfg["launch_app"],
            ['连带启动程序，"default" 表示同目录游戏'])
    _add_kv(doc, "block_targets", list(cfg["block_targets"]), ["断网目标程序列表"])
    _add_kv(doc, "ping_target", cfg["ping_target"], ['Ping 目标，留空禁用'])
    _add_kv(doc, "auto_exit_on_game_exit", cfg["auto_exit_on_game_exit"],
            ["游戏退出时自动退出"])

    ui = table()
    _add_kv(ui, "window_width", cfg["ui"]["window_width"])
    _add_kv(ui, "window_height", cfg["ui"]["window_height"])
    _add_kv(ui, "bg_color", cfg["ui"]["bg_color"])
    _add_kv(ui, "drag_color", cfg["ui"]["drag_color"])
    _add_kv(ui, "transparent_color", cfg["ui"]["transparent_color"])
    _add_kv(ui, "long_press_ms", cfg["ui"]["long_press_ms"], ["长按 👁 打开规则管理"])
    _add_kv(ui, "toggle_click_delay_ms", cfg["ui"]["toggle_click_delay_ms"])
    _add_kv(ui, "exit_reload_long_press_ms", cfg["ui"]["exit_reload_long_press_ms"],
            ["长按 ✕ 重载配置时间"])
    lw = table()
    _add_kv(lw, "width", cfg["ui"]["log_window"]["width"])
    _add_kv(lw, "height", cfg["ui"]["log_window"]["height"])
    ui["log_window"] = lw
    mw = table()
    _add_kv(mw, "width", cfg["ui"]["md_window"]["width"])
    _add_kv(mw, "height", cfg["ui"]["md_window"]["height"])
    _add_kv(mw, "font_family", cfg["ui"]["md_window"]["font_family"])
    _add_kv(mw, "font_size", cfg["ui"]["md_window"]["font_size"])
    _add_kv(mw, "font_color", cfg["ui"]["md_window"]["font_color"])
    _add_kv(mw, "bg_color", cfg["ui"]["md_window"]["bg_color"])
    ui["md_window"] = mw
    od = table()
    _add_kv(od, "width", cfg["ui"]["ocr_dialog"]["width"])
    _add_kv(od, "height", cfg["ui"]["ocr_dialog"]["height"])
    ui["ocr_dialog"] = od
    rd = table()
    _add_kv(rd, "width", cfg["ui"]["rule_dialog"]["width"])
    _add_kv(rd, "height", cfg["ui"]["rule_dialog"]["height"])
    ui["rule_dialog"] = rd
    hk = table()
    _add_kv(hk, "enabled", cfg["ui"].get("hotkeys", {}).get("enabled", False),
            ["启用快捷键（默认关）：Ctrl+R 重载 / Ctrl+L 日志 / Ctrl+Q 退出"])
    ui["hotkeys"] = hk
    doc["ui"] = ui

    tm = table()
    _add_kv(tm, "clock_interval_ms", cfg["timing"]["clock_interval_ms"])
    _add_kv(tm, "animation_interval_ms", cfg["timing"]["animation_interval_ms"])
    _add_kv(tm, "ping_interval_s", cfg["timing"]["ping_interval_s"])
    _add_kv(tm, "game_monitor_interval_s", cfg["timing"]["game_monitor_interval_s"])
    doc["timing"] = tm

    iw = table()
    _add_kv(iw, "enabled", cfg["img_watch"]["enabled"], ["启动时是否自动启用"])
    _add_kv(iw, "interval", cfg["img_watch"]["interval"], ["检测间隔（秒）"])
    _add_kv(iw, "consecutive", cfg["img_watch"]["consecutive"])
    _add_kv(iw, "cooldown", cfg["img_watch"]["cooldown"])
    _add_kv(iw, "debug_log", cfg["img_watch"]["debug_log"])
    _add_kv(iw, "debug_overlay", cfg["img_watch"]["debug_overlay"], ["显示白绿黑蓝框"])
    _add_kv(iw, "show_rule_name", cfg["img_watch"].get("show_rule_name", False), ["显示黑白名单规则名字（调试用）"])
    _add_kv(iw, "scan_all", cfg["img_watch"].get("scan_all", False), ["全量扫描（测试模式）：无论是否命中都扫完全部规则"])
    _add_kv(iw, "require_foreground", cfg["img_watch"]["require_foreground"])
    _add_kv(iw, "auto_mute_when_hidden", cfg["img_watch"]["auto_mute_when_hidden"],
            ["窗口隐藏时自动静音（默认关；在 🔊 长按设置里开关）"])
    _add_kv(iw, "visibility_check_interval_s",
            cfg["img_watch"]["visibility_check_interval_s"])
    doc["img_watch"] = iw
    doc.add(nl())
    doc.add(comment("=" * 52))
    doc.add(comment("版本 1.0  |  https://github.com/smX456464"))
    doc.add(comment("=" * 52))
    return doc


def _build_rule_table(rule):
    t = table()
    _add_kv(t, "name", rule.get("name", ""))
    note = (rule.get("note") or "").strip()
    if note:
        _add_kv(t, "note", note, ["备注（帮助记忆规则作用）"])
    if rule_has_roi(rule):
        _add_kv(t, "x1", float(rule["x1"]), ["ROI 左（0~1 相对客户区）"])
        _add_kv(t, "y1", float(rule["y1"]), ["ROI 上"])
        _add_kv(t, "x2", float(rule["x2"]), ["ROI 右"])
        _add_kv(t, "y2", float(rule["y2"]), ["ROI 下"])
    else:
        t.add(comment("未画框（无 ROI）"))
    _add_kv(t, "ocr_text", rule.get("ocr_text", ""), ["期望文字或正则"])
    excl = (rule.get("exclude_text") or "").strip()
    if excl:
        _add_kv(t, "exclude_text", excl,
                ["否定词（正则或纯文本）：OCR 文字里出现则跳过本规则"])
    _add_kv(t, "match_mode", rule.get("match_mode", "contains"),
            ["匹配模式：contains / equals / regex"])
    return t


def build_templates_doc(templates):
    doc = tomlkit.document()
    doc.add(comment("版本：1.0  |  项目主页：https://github.com/smX456464"))
    doc.add(comment("=" * 52))
    doc.add(comment("OCR 规则：白名单 + 黑名单"))
    doc.add(comment(""))
    doc.add(comment("白名单：任一命中 → 触发断网（例如：对手 ID）"))
    doc.add(comment("黑名单：任一命中 → 抑制断网（例如：准备 / 选择 / 商店）"))
    doc.add(comment("最终触发 = 白名单命中 AND 黑名单全部未命中"))
    doc.add(comment(""))
    doc.add(comment("想编辑规则：长按 👁 打开规则管理对话框"))
    doc.add(comment("=" * 52))
    doc.add(nl())
    if not isinstance(templates, dict) or not templates:
        doc.add(comment("（暂无规则）"))
        return doc
    for size_key, tpl in templates.items():
        if not isinstance(tpl, dict): continue
        doc.add(comment("-" * 52))
        doc.add(comment(f"分辨率 {size_key}"))
        doc.add(comment("-" * 52))
        root = table()
        wl = tpl.get("whitelist", [])
        if isinstance(wl, list) and wl:
            wl_aot = aot()
            for r in wl:
                if isinstance(r, dict): wl_aot.append(_build_rule_table(r))
            root["whitelist"] = wl_aot
        else:
            root.add(comment("白名单：（空）")); root.add(nl())
        bl = tpl.get("blacklist", [])
        if isinstance(bl, list) and bl:
            bl_aot = aot()
            for r in bl:
                if isinstance(r, dict): bl_aot.append(_build_rule_table(r))
            root["blacklist"] = bl_aot
        else:
            root.add(comment("黑名单：（空）")); root.add(nl())
        doc[size_key] = root
        doc.add(nl())
    doc.add(comment("=" * 52))
    doc.add(comment("版本 1.0  |  https://github.com/smX456464"))
    doc.add(comment("=" * 52))
    return doc


def build_state_doc(state):
    doc = tomlkit.document()
    doc.add(comment("运行时状态（程序自动维护）"))
    doc.add(nl())
    for k in ("window_x", "window_y"):
        v = state.get(k)
        if v is not None: _add_kv(doc, k, v)
    for k in ("md_window_x", "md_window_y", "md_window_width", "md_window_height"):
        v = state.get(k)
        if v is not None: _add_kv(doc, k, v)
    v = state.get("md_scroll_pos", 0.0)
    if v is not None: _add_kv(doc, "md_scroll_pos", v)
    return doc


def load_config():
    global _config_verbose_printed
    first_call = not _config_verbose_printed
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
    except Exception as e:
        print(f"❌ 创建配置目录失败: {e}", flush=True)

    if os.path.exists(CONFIG_TOML):
        try:
            with open(CONFIG_TOML, "r", encoding="utf-8") as f:
                cfg = doc_to_dict(tomlkit.load(f))
            if first_call: print("✅ config.toml 解析成功", flush=True)
        except Exception as e:
            print(f"❌ config.toml 解析失败: {e}", flush=True)
            cfg = deep_copy(DEFAULT_CONFIG)
    else:
        cfg = deep_copy(DEFAULT_CONFIG)
        with open(CONFIG_TOML, "w", encoding="utf-8") as f:
            tomlkit.dump(build_config_doc(cfg), f)
        if first_call: print("ℹ️ 已生成默认 config.toml", flush=True)
    cfg = merge_defaults(cfg, DEFAULT_CONFIG)

    tpl = None
    migrated = False
    if os.path.exists(TEMPLATES_TOML):
        try:
            with open(TEMPLATES_TOML, "r", encoding="utf-8") as f:
                raw = doc_to_dict(tomlkit.load(f))
            tpl = {}
            for size_key, t in raw.items():
                if not isinstance(t, dict): continue
                if "whitelist" not in t and "blacklist" not in t:
                    migrated = True
                if "blacklist" in t and isinstance(t["blacklist"], dict):
                    migrated = True
                tpl[size_key] = migrate_old_template(t)
            if first_call:
                print(f"✅ templates.toml 解析成功，共 {len(tpl)} 套规则", flush=True)
                if migrated: print("   已从旧格式自动迁移", flush=True)
        except Exception as e:
            print(f"❌ templates.toml 解析失败: {e}", flush=True)
    if tpl is None: tpl = {}
    # 用户明确不要 default 兜底：读到 default 就丢弃
    if "default" in tpl:
        del tpl["default"]
        migrated = True
        print("ℹ️ 已忽略 templates.toml 里的 [default] 段（当前版本不使用通用兜底）",
              flush=True)
    if migrated or not os.path.exists(TEMPLATES_TOML):
        with open(TEMPLATES_TOML, "w", encoding="utf-8") as f:
            tomlkit.dump(build_templates_doc(tpl), f)

    st = None
    if os.path.exists(STATE_TOML):
        try:
            with open(STATE_TOML, "r", encoding="utf-8") as f:
                st = doc_to_dict(tomlkit.load(f))
        except Exception as e:
            print(f"⚠️ state.toml 解析失败: {e}", flush=True)
    if st is None: st = deep_copy(DEFAULT_STATE)

    if first_call:
        iw = cfg.get("img_watch", {})
        print(f"📷 边框：{'开' if iw.get('debug_overlay', True) else '关'}  "
              f"间隔：{iw.get('interval', 1.0)}s", flush=True)
    _config_verbose_printed = True
    return cfg, tpl, st


def update_config_field(key_path, value):
    try:
        try:
            with open(CONFIG_TOML, "r", encoding="utf-8") as f:
                doc = tomlkit.load(f)
        except Exception as e:
            # 原文件损坏：报错提示，绝不覆写用户文件（保数据安全）
            print(f"❌ 更新失败：config.toml 已损坏，请手动修复后重试：{e}",
                  flush=True)
            return False
        node = doc
        for k in key_path[:-1]:
            if k not in node:
                node[k] = table()
            node = node[k]
        node[key_path[-1]] = value
        with open(CONFIG_TOML, "w", encoding="utf-8") as f:
            tomlkit.dump(doc, f)
        return True
    except Exception as e:
        print(f"❌ 更新 config.toml 失败: {e}", flush=True)
        return False


def save_templates(tpl):
    try:
        with open(TEMPLATES_TOML, "w", encoding="utf-8") as f:
            tomlkit.dump(build_templates_doc(tpl), f)
        return True
    except Exception as e:
        print(f"❌ 保存 templates.toml 失败: {e}", flush=True)
        return False


def save_state(st):
    try:
        with open(STATE_TOML, "w", encoding="utf-8") as f:
            tomlkit.dump(build_state_doc(st), f)
        return True
    except Exception as e:
        print(f"❌ 保存 state.toml 失败: {e}", flush=True)
        return False


def resolve_exe_path(value):
    if value == "default":
        return os.path.join(SCRIPT_DIR, DEFAULT_GAME_NAME)
    return value
