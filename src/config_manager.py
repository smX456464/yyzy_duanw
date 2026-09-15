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
# 资源目录（只读）：打包后从 exe 内部读；源码模式从项目目录读
def _get_resource_dir():
    import sys as _sys
    if getattr(_sys, "frozen", False):
        return getattr(_sys, "_MEIPASS", os.path.dirname(_sys.executable))
    return SCRIPT_DIR


RESOURCE_DIR = _get_resource_dir()
RESOURCE_CONFIG_DIR = os.path.join(RESOURCE_DIR, "config")

# 用户可覆盖位置（放这里优先）
BUILTIN_TEMPLATES_TOML_PATH = os.path.join(CONFIG_DIR, "builtin_templates.toml")
# 内置资源位置（打包进 exe，读不到用户目录时用）
BUILTIN_TEMPLATES_TOML_BUILTIN = os.path.join(RESOURCE_CONFIG_DIR, "builtin_templates.toml")

MUTEX_NAME = "Global\\MoonlightBlockerTool"
DEFAULT_GAME_NAME = "Night of the Full Moon.exe"
DEFAULT_ID_REGEX = r"[\u4e00-\u9fa5A-Za-z0-9]{2,16}"

DEFAULT_CONFIG = {
    "block_time": 5,
    "ocr_block_time": 1,
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
        "debug_log": True, "debug_overlay": True, "highlight_on_hit": True,
        "show_rule_name": False, "scan_all": False,
        "adaptive_scan": False, "adaptive_skip_rounds": 3,
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
    "user_saved_resolutions": [],
}

_config_verbose_printed = False

# 标记：本次进程内是否新生成过配置文件（用于"首次运行"检测）
JUST_CREATED_CONFIG = False
JUST_CREATED_TEMPLATES = False


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
    # block_time: 每规则独立断网秒数，留空则用全局
    bt = rule.get("block_time", None)
    if bt is not None:
        try:
            r["block_time"] = int(bt)
        except Exception:
            pass
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
    doc.add(comment("=" * 60))
    doc.add(comment("信号变频 · 月圆之夜断网工具 配置文件"))
    doc.add(comment("版本 1.0  |  项目主页：https://github.com/smX456464"))
    doc.add(comment("=" * 60))
    doc.add(comment(""))
    doc.add(comment("【修改后如何生效】长按 ✕ 3 秒重载配置，或重启工具"))
    doc.add(nl())

    # 一、断网参数
    doc.add(comment("=" * 60))
    doc.add(comment("一、断网参数"))
    doc.add(comment("=" * 60))
    doc.add(nl())
    _add_kv(doc, "block_time", cfg["block_time"], [
        "手动点击断网秒数（1-1000）",
        "  点主窗口中间大块 = 手动触发一次断网",
        "  这是断网的最短时间",
        "  之后每秒检查黑白名单，动态决定是否继续",
    ])
    _add_kv(doc, "ocr_block_time", cfg.get("ocr_block_time", 1), [
        "OCR 命中默认断网秒数（1-1000）",
        "  规则里断网秒数留空时，用这个值",
        "  规则里填了秒数，则优先用规则的",
    ])
    doc.add(nl())

    # 二、目标程序
    doc.add(comment("=" * 60))
    doc.add(comment("二、目标程序"))
    doc.add(comment("=" * 60))
    doc.add(nl())
    _add_kv(doc, "launch_app", cfg["launch_app"], [
        "同步启动的程序",
        '  "default"  → 同目录的 Night of the Full Moon.exe',
        "  绝对路径    → 指定的 exe",
        '  空字符串 "" → 不启动',
    ])
    _add_kv(doc, "block_targets", list(cfg["block_targets"]), [
        "断网目标程序列表",
        '  ["default"]               → 只拦同目录游戏',
        "  [绝对路径]                 → 拦指定程序",
        "  [多个绝对路径]             → 拦多个",
        '  [] 或 [""]                → 整机断网',
    ])
    _add_kv(doc, "ping_target", cfg["ping_target"], [
        "Ping 显示目标",
        '  留空 "" 则隐藏 ping',
    ])
    _add_kv(doc, "auto_exit_on_game_exit", cfg["auto_exit_on_game_exit"], [
        "游戏退出时是否自动退出工具",
        "  true  → 目标程序全部关闭时，工具自动退出",
        "  false → 保持工具运行",
    ])
    doc.add(nl())

    # 三、音量控制
    doc.add(comment("=" * 60))
    doc.add(comment("三、音量控制（需要 SoundVolumeView.exe）"))
    doc.add(comment("=" * 60))
    doc.add(nl())
    _add_kv(doc, "volume_enabled", cfg.get("volume_enabled", True), [
        "是否显示音量按钮",
        "  true  → 显示（需要配置 SoundVolumeView.exe）",
        "  false → 隐藏（向导里点关闭这个功能会设为 false）",
    ])
    _add_kv(doc, "sound_volume_view_path", cfg["sound_volume_view_path"], [
        "SoundVolumeView.exe 完整路径",
        '  ""  → 未配置（会弹出下载向导）',
        "  绝对路径 → 如 D:\\Tools\\SoundVolumeView.exe",
    ])
    _add_kv(doc, "volume_mute_value", cfg["volume_mute_value"], [
        "静音时音量设置值（0-100）",
        "  0 = 完全静音，50 = 音量调到一半",
    ])
    _add_kv(doc, "auto_mute_when_hidden",
            cfg.get("auto_mute_when_hidden", False), [
        "游戏窗口隐藏时自动静音",
        "  true  → 切出游戏自动静音，切回自动恢复",
        "  false → 不做这个动作",
    ])
    _add_kv(doc, "visibility_check_interval_s",
            cfg.get("visibility_check_interval_s", 5.0), [
        "游戏窗口可见性检查间隔（秒）",
        "  越小越灵敏，CPU 占用略高",
    ])
    doc.add(nl())

    # 四、首次运行
    doc.add(comment("=" * 60))
    doc.add(comment("四、首次运行 / 游戏路径向导"))
    doc.add(comment("=" * 60))
    doc.add(nl())
    _add_kv(doc, "game_path_check_enabled",
            cfg.get("game_path_check_enabled", True), [
        "打包运行时，找不到游戏 exe 是否弹向导",
        "  true  → 弹（让用户手动填或选整机断网）",
        "  false → 不弹",
        "  源码模式（python main.pyw）默认跳过",
    ])
    _add_kv(doc, "game_path_draft", cfg.get("game_path_draft", ""), [
        "游戏路径草稿（用户点向导退出时暂存）",
        "  下次打开向导时预填",
    ])
    _add_kv(doc, "game_path_draft_sync",
            cfg.get("game_path_draft_sync", True), [
        "草稿里的同步启动勾选状态",
    ])
    doc.add(nl())

    # 五、UI
    doc.add(comment("=" * 60))
    doc.add(comment("五、界面 UI"))
    doc.add(comment("=" * 60))
    doc.add(nl())
    ui = table()
    _add_kv(ui, "window_width", cfg["ui"]["window_width"], [
        "主窗口宽度（像素）"])
    _add_kv(ui, "window_height", cfg["ui"]["window_height"], [
        "主窗口高度（像素）"])
    _add_kv(ui, "bg_color", cfg["ui"]["bg_color"], [
        "主背景色（大块区域颜色）"])
    _add_kv(ui, "drag_color", cfg["ui"]["drag_color"], [
        "顶部拖动条颜色"])
    _add_kv(ui, "transparent_color", cfg["ui"]["transparent_color"], [
        "透明色（抠图用，不要和 UI 其他颜色重合）",
    ])
    _add_kv(ui, "long_press_ms", cfg["ui"]["long_press_ms"], [
        "长按判定时间（毫秒）",
        "  按住按钮超过这个时间 = 触发长按功能",
    ])
    _add_kv(ui, "toggle_click_delay_ms", cfg["ui"]["toggle_click_delay_ms"], [
        "短按延迟执行（毫秒）",
        "  防止误触",
    ])
    _add_kv(ui, "exit_reload_long_press_ms",
            cfg["ui"]["exit_reload_long_press_ms"], [
        "长按 X 重载配置时间（毫秒）",
    ])
    lw = table()
    _add_kv(lw, "width", cfg["ui"]["log_window"]["width"], [
        "日志窗口宽度（像素）"])
    _add_kv(lw, "height", cfg["ui"]["log_window"]["height"], [
        "日志窗口高度（像素）"])
    ui["log_window"] = lw
    mw = table()
    _add_kv(mw, "width", cfg["ui"]["md_window"]["width"], [
        "默认宽度（首次打开）"])
    _add_kv(mw, "height", cfg["ui"]["md_window"]["height"], [
        "默认高度（首次打开）"])
    _add_kv(mw, "font_family", cfg["ui"]["md_window"]["font_family"], [
        "字体"])
    _add_kv(mw, "font_size", cfg["ui"]["md_window"]["font_size"], [
        "字号"])
    _add_kv(mw, "font_color", cfg["ui"]["md_window"]["font_color"], [
        "文字颜色"])
    _add_kv(mw, "bg_color", cfg["ui"]["md_window"]["bg_color"], [
        "背景颜色"])
    ui["md_window"] = mw
    od = table()
    _add_kv(od, "width", cfg["ui"]["ocr_dialog"]["width"], [
        "OCR 确认对话框宽度"])
    _add_kv(od, "height", cfg["ui"]["ocr_dialog"]["height"], [
        "OCR 确认对话框高度"])
    ui["ocr_dialog"] = od
    rd = table()
    _add_kv(rd, "width", cfg["ui"]["rule_dialog"]["width"], [
        "规则管理对话框宽度"])
    _add_kv(rd, "height", cfg["ui"]["rule_dialog"]["height"], [
        "规则管理对话框高度"])
    ui["rule_dialog"] = rd
    hk = table()
    _add_kv(hk, "enabled",
            cfg["ui"].get("hotkeys", {}).get("enabled", False), [
        "是否启用快捷键（默认关）",
        "  Ctrl+R 重载配置 / Ctrl+L 打开日志 / Ctrl+Q 退出",
    ])
    ui["hotkeys"] = hk
    doc["ui"] = ui

    # 六、时序
    doc.add(nl())
    doc.add(comment("=" * 60))
    doc.add(comment("六、时序"))
    doc.add(comment("=" * 60))
    doc.add(nl())
    tm = table()
    _add_kv(tm, "clock_interval_ms", cfg["timing"]["clock_interval_ms"], [
        "时钟刷新间隔（毫秒）",
    ])
    _add_kv(tm, "animation_interval_ms", cfg["timing"]["animation_interval_ms"], [
        "心跳动画刷新间隔（毫秒）",
    ])
    _add_kv(tm, "ping_interval_s", cfg["timing"]["ping_interval_s"], [
        "Ping 检测间隔（秒）",
    ])
    _add_kv(tm, "game_monitor_interval_s",
            cfg["timing"]["game_monitor_interval_s"], [
        "游戏进程监控间隔（秒）",
        "  用于判断游戏是否退出",
    ])
    doc["timing"] = tm

    # 七、OCR 监控
    doc.add(nl())
    doc.add(comment("=" * 60))
    doc.add(comment("七、OCR 监控（核心）"))
    doc.add(comment("=" * 60))
    doc.add(nl())
    iw = table()
    _add_kv(iw, "enabled", cfg["img_watch"]["enabled"], [
        "启动时是否自动启用 OCR 监控",
    ])
    _add_kv(iw, "interval", cfg["img_watch"]["interval"], [
        "检测间隔（秒）",
        "  0.5 = 每 0.5 秒扫一次",
        "  越小越快，CPU 占用高",
    ])
    _add_kv(iw, "consecutive", cfg["img_watch"]["consecutive"], [
        "连续命中帧数（防抖）",
        "  连续 N 帧命中才算触发",
    ])
    _add_kv(iw, "cooldown", cfg["img_watch"]["cooldown"], [
        "触发后冷却（秒）",
        "  触发后 N 秒内不重复触发",
    ])
    _add_kv(iw, "debug_log", cfg["img_watch"]["debug_log"], [
        "打印每帧检测日志",
        "  true  → 显示每帧 OCR 结果",
        "  false → 只显示命中/触发",
    ])
    _add_kv(iw, "debug_overlay", cfg["img_watch"]["debug_overlay"], [
        "显示调试框（常亮 ROI 边框）",
    ])
    _add_kv(iw, "highlight_on_hit",
            cfg["img_watch"].get("highlight_on_hit", True), [
        "命中时闪烁提示",
        "  独立于调试框",
    ])
    _add_kv(iw, "show_rule_name",
            cfg["img_watch"].get("show_rule_name", False), [
        "显示规则名字（调试用）",
    ])
    _add_kv(iw, "scan_all", cfg["img_watch"].get("scan_all", False), [
        "全量扫描（测试模式）",
        "  无论是否命中都扫完全部规则（慢）",
    ])
    _add_kv(iw, "adaptive_scan",
            cfg["img_watch"].get("adaptive_scan", False), [
        "自适应扫描",
        "  长期没出文字的规则降频扫描",
    ])
    _add_kv(iw, "adaptive_skip_rounds",
            cfg["img_watch"].get("adaptive_skip_rounds", 3), [
        "自适应扫描的跳轮数",
        "  从未出文字的规则每 N 轮扫一次",
    ])
    _add_kv(iw, "require_foreground", cfg["img_watch"]["require_foreground"], [
        "要求目标窗口在前台才检测",
    ])
    doc["img_watch"] = iw

    doc.add(nl())
    doc.add(comment("=" * 60))
    doc.add(comment("版本 1.0  |  https://github.com/smX456464"))
    doc.add(comment("=" * 60))
    return doc



def _build_rule_table(rule, allow_roi=True):
    t = table()
    _add_kv(t, "name", rule.get("name", ""))
    note = (rule.get("note") or "").strip()
    if note:
        _add_kv(t, "note", note, ["备注（帮助记忆规则作用）"])
    if allow_roi and rule_has_roi(rule):
        _add_kv(t, "x1", float(rule["x1"]), ["ROI 左（0~1 相对客户区）"])
        _add_kv(t, "y1", float(rule["y1"]), ["ROI 上"])
        _add_kv(t, "x2", float(rule["x2"]), ["ROI 右"])
        _add_kv(t, "y2", float(rule["y2"]), ["ROI 下"])
    else:
        if allow_roi:
            t.add(comment("未画框（无 ROI）"))
        else:
            t.add(comment("通用规则：无需 ROI"))
    _add_kv(t, "ocr_text", rule.get("ocr_text", ""), ["期望文字或正则"])
    bt = rule.get("block_time", None)
    if bt is not None:
        try:
            _add_kv(t, "block_time", int(bt),
                    ["本条规则的断网秒数（留空/删除则用全局 block_time）"])
        except Exception:
            pass
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

    # 先写 universal（通用规则）
    if "universal" in templates:
        uni = templates["universal"]
        if isinstance(uni, dict):
            doc.add(comment("-" * 52))
            doc.add(comment("通用规则（所有分辨率生效）"))
            doc.add(comment("-" * 52))
            root = table()
            wl = uni.get("whitelist", [])
            if isinstance(wl, list) and wl:
                wl_aot = aot()
                for r in wl:
                    if isinstance(r, dict):
                        wl_aot.append(_build_rule_table(r, allow_roi=False))
                root["whitelist"] = wl_aot
            else:
                root.add(comment("通用白名单：（空）"))
                root.add(nl())
            bl = uni.get("blacklist", [])
            if isinstance(bl, list) and bl:
                bl_aot = aot()
                for r in bl:
                    if isinstance(r, dict):
                        bl_aot.append(_build_rule_table(r, allow_roi=False))
                root["blacklist"] = bl_aot
            else:
                root.add(comment("通用黑名单：（空）"))
                root.add(nl())
            doc["universal"] = root
            doc.add(nl())

    for size_key, tpl in templates.items():
        if size_key == "universal":
            continue
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
    usr = state.get("user_saved_resolutions", [])
    if isinstance(usr, list) and usr:
        _add_kv(doc, "user_saved_resolutions", list(usr),
                ["用户手动保存过规则的分辨率列表（程序维护）"])
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
            if first_call:
                print("⚙️ config.toml 已加载", flush=True)
        except Exception as e:
            print(f"❌ config.toml 解析失败: {e}", flush=True)
            cfg = deep_copy(DEFAULT_CONFIG)
    else:
        cfg = deep_copy(DEFAULT_CONFIG)
        with open(CONFIG_TOML, "w", encoding="utf-8") as f:
            tomlkit.dump(build_config_doc(cfg), f)
        global JUST_CREATED_CONFIG
        JUST_CREATED_CONFIG = True
        if first_call:
            print("⚙️ 未找到 config.toml，已生成默认配置（首次运行）",
                  flush=True)
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
                _n_res = 0
                _n_res_rules = 0
                _n_uni = 0
                for _k, _t in tpl.items():
                    if not isinstance(_t, dict):
                        continue
                    _n = (len(_t.get("whitelist", []) or []) +
                          len(_t.get("blacklist", []) or []))
                    if _k == "universal":
                        _n_uni = _n
                    else:
                        _n_res += 1
                        _n_res_rules += _n
                _uni_txt = (f" · 通用 {_n_uni} 条" if _n_uni > 0 else "")
                print(f"📋 templates.toml 已加载：{_n_res} 个分辨率，"
                      f"共 {_n_res_rules} 条规则{_uni_txt}", flush=True)
                if migrated:
                    print("   ℹ️ 已从旧格式自动迁移", flush=True)
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
        _ov = "开" if iw.get("debug_overlay", True) else "关"
        _hl = "开" if iw.get("highlight_on_hit", True) else "关"
        _iv = iw.get("interval", 1.0)
        _cons = iw.get("consecutive", 2)
        _cd = iw.get("cooldown", 10.0)
        print(f"📷 OCR 监控参数：调试框 {_ov} · 命中闪烁 {_hl} · "
              f"间隔 {_iv}s · 连续 {_cons} 帧 · 冷却 {_cd}s", flush=True)
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


# ============================================================
# 内置模板（从 config/builtin_templates.toml 读）
# 用户 templates.toml 没有的分辨率，用这份兜底
# ============================================================

def _load_builtin_templates():
    """读内置模板。

    优先顺序：
      1. 用户 config/builtin_templates.toml（用户可覆盖）
      2. exe 内打包的 config/builtin_templates.toml（内置兜底）
    """
    for path, tag in [
        (BUILTIN_TEMPLATES_TOML_PATH, "\u7528\u6237"),
        (BUILTIN_TEMPLATES_TOML_BUILTIN, "\u5185\u7f6e"),
    ]:
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                doc = tomlkit.load(f)
            result = {}
            for k, v in doc.items():
                if not isinstance(v, dict):
                    continue
                result[k] = doc_to_dict(v)
            if result:
                print(f"\U0001f4e6 \u5185\u7f6e\u6a21\u677f\u5df2\u52a0\u8f7d\uff08{tag}\uff09\uff1a"
                      f"{len(result)} \u4e2a\u5206\u8fa8\u7387", flush=True)
                return result
        except Exception as e:
            print(f"\u26a0 {tag}\u5185\u7f6e\u6a21\u677f\u89e3\u6790\u5931\u8d25: {e}", flush=True)
    return {}


_BUILTIN_TEMPLATES_CACHE = None


def get_builtin_templates():
    """获取内置模板（带缓存）"""
    global _BUILTIN_TEMPLATES_CACHE
    if _BUILTIN_TEMPLATES_CACHE is None:
        _BUILTIN_TEMPLATES_CACHE = _load_builtin_templates()
    return _BUILTIN_TEMPLATES_CACHE


def reload_builtin_templates():
    """强制重新加载（用户手动改了 builtin_templates.toml 时用）"""
    global _BUILTIN_TEMPLATES_CACHE
    _BUILTIN_TEMPLATES_CACHE = None
    return get_builtin_templates()