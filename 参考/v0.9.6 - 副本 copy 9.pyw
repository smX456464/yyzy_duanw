"""
月圆之夜断网工具 v4.3.0
改动：
- 全面用 tomlkit：读、写都保留注释，程序改字段不丢手改内容
- 去掉 JSON → TOML 迁移功能（不再读 config.json）
- 模板去掉 sample_ocr 字段
- 所有硬编码项变成可配置：
  UI 尺寸/颜色、长按/连击参数、日志/MD/OCR 弹窗尺寸、
  时钟/动画/Ping/游戏监控间隔
"""
import ctypes
from ctypes import windll, wintypes
import io
import os
import subprocess
import sys
import time
import math
import re
import tkinter as tk
from tkinter import messagebox
from threading import Thread, Event
from collections import deque
from datetime import datetime

import tomlkit
from tomlkit import comment, nl, table

# ---- 截图 ----
try:
    import mss
    import numpy as np
    _IMGWATCH_AVAILABLE = True
    try:
        _mss_factory = mss.MSS
    except AttributeError:
        _mss_factory = mss.mss
except ImportError:
    _IMGWATCH_AVAILABLE = False
    _mss_factory = None
    np = None

# ---- OCR ----
try:
    from rapidocr_onnxruntime import RapidOCR as _RapidOCR
    _OCR_AVAILABLE = True
except ImportError:
    _RapidOCR = None
    _OCR_AVAILABLE = False

_ocr_engine = None


def _get_ocr_engine():
    global _ocr_engine
    if _ocr_engine is None:
        if not _OCR_AVAILABLE:
            _ocr_engine = False
            return False
        try:
            print("🔤 正在初始化 OCR 引擎（首次约 1~3 秒）...", flush=True)
            _ocr_engine = _RapidOCR()
            print("🔤 OCR 引擎就绪", flush=True)
        except Exception as e:
            print(f"❌ OCR 引擎初始化失败: {e}", flush=True)
            _ocr_engine = False
    return _ocr_engine


def ocr_recognize(bgra):
    engine = _get_ocr_engine()
    if not engine:
        return None
    try:
        rgb = bgra[:, :, [2, 1, 0]].copy()
        result, _ = engine(rgb)
        if result:
            texts = []
            for item in result:
                try:
                    texts.append(str(item[1]))
                except:
                    pass
            return " ".join(texts)
        return ""
    except Exception as e:
        print(f"❌ OCR 识别失败: {e}", flush=True)
        return None


def ocr_text_matches(text_now, expected, mode="contains"):
    if text_now is None or expected is None:
        return False
    expected = expected.strip()
    if not expected:
        return False
    if mode == "equals":
        return text_now.strip() == expected
    if mode == "regex":
        try:
            return bool(re.search(expected, text_now))
        except:
            return False
    return expected in text_now


# ============================================================
#                    日志系统
# ============================================================
_REPLACEABLE_PREFIXES = [("👁 ROI=", "roi_per_frame")]


def _auto_tag(text):
    for prefix, tag in _REPLACEABLE_PREFIXES:
        if text.startswith(prefix):
            return tag
    return None


class LogBuffer:
    def __init__(self, maxlen=3000):
        self.buffer = deque(maxlen=maxlen)
        self.listeners = []

    def append(self, text, tag=None):
        if tag is None:
            tag = _auto_tag(text)
        if tag is not None and self.buffer and self.buffer[-1][0] == tag:
            self.buffer[-1] = (tag, text)
            for cb in list(self.listeners):
                try:
                    cb("REPLACE", text)
                except:
                    pass
        else:
            self.buffer.append((tag, text))
            for cb in list(self.listeners):
                try:
                    cb("APPEND", text)
                except:
                    pass

    def add_listener(self, cb):
        if cb not in self.listeners:
            self.listeners.append(cb)

    def remove_listener(self, cb):
        try:
            self.listeners.remove(cb)
        except ValueError:
            pass

    def snapshot(self):
        return "".join(t for _, t in self.buffer)

    def clear(self):
        self.buffer.clear()


LOG_BUFFER = LogBuffer()


class BufferedWriter:
    def __init__(self, original, buffer):
        self.original = original
        self.buffer = buffer
        self._partial = ""

    def write(self, s):
        if not s:
            return
        self._partial += s
        while "\n" in self._partial:
            line, self._partial = self._partial.split("\n", 1)
            full = line + "\n"
            self.buffer.append(full, tag=_auto_tag(full))
        if self.original:
            try:
                self.original.write(s)
            except:
                pass

    def flush(self):
        if self._partial:
            self.buffer.append(self._partial, tag=_auto_tag(self._partial))
            self._partial = ""
        if self.original:
            try:
                self.original.flush()
            except:
                pass


class SafeWriter:
    def write(self, s):
        if s:
            LOG_BUFFER.append(s, tag=_auto_tag(s))
    def flush(self):
        pass


def _setup_stdout():
    original = None
    try:
        if sys.stdout is not None and getattr(sys.stdout, 'buffer', None) is not None:
            original = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    except:
        original = None
    sys.stdout = BufferedWriter(original, LOG_BUFFER)


_setup_stdout()


# ============================================================
#                    管理员权限与单实例
# ============================================================
def is_admin():
    try:
        return windll.shell32.IsUserAnAdmin()
    except:
        return False


def run_as_admin():
    windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, ' '.join([f'"{sys.argv[0]}"'] + sys.argv[1:]),
        None, 1
    )


MUTEX_NAME = "Global\\MoonlightBlockerTool_V4.3.0"


def check_single_instance():
    mutex = windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)
    last_error = windll.kernel32.GetLastError()
    if last_error == 183:
        windll.kernel32.CloseHandle(mutex)
        return None, True
    return mutex, False


def resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)


SCRIPT_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))
CONFIG_TOML = os.path.join(SCRIPT_DIR, "config.toml")
TEMPLATES_TOML = os.path.join(SCRIPT_DIR, "templates.toml")
STATE_TOML = os.path.join(SCRIPT_DIR, "state.toml")
DEFAULT_GAME_NAME = "Night of the Full Moon.exe"
DEFAULT_ID_REGEX = r"[\u4e00-\u9fa5A-Za-z0-9]{2,16}"

_config_verbose_printed = False


# ============================================================
#                    默认值
# ============================================================
DEFAULT_CONFIG = {
    "block_time": 5,
    "sound_volume_view_path": "",
    "volume_mute_value": 0,
    "launch_app": "default",
    "block_targets": ["default"],
    "ping_target": "qq.com",
    "auto_exit_on_game_exit": True,
    "ui": {
        "window_width": 200,
        "window_height": 200,
        "bg_color": "#E0E0E0",
        "drag_color": "#D0D0D0",
        "transparent_color": "#00FF00",
        "long_press_ms": 2000,
        "multi_click_count": 6,
        "multi_click_window_s": 2.0,
        "toggle_click_delay_ms": 500,
        "log_window": {"width": 460, "height": 340},
        "md_window": {
            "width": 400, "height": 300,
            "font_family": "微软雅黑", "font_size": 10,
            "font_color": "#000000", "bg_color": "#FFFFFF",
        },
        "ocr_dialog": {"width": 560, "height": 560},
    },
    "timing": {
        "clock_interval_ms": 200,
        "animation_interval_ms": 1000,
        "ping_interval_s": 3,
        "game_monitor_interval_s": 3,
    },
    "img_watch": {
        "enabled": True,
        "interval": 0.5,
        "consecutive": 2,
        "cooldown": 10.0,
        "debug_log": True,
        "debug_overlay": True,
        "trigger_mode": "appear",
        "require_foreground": False,
    },
}


DEFAULT_TEMPLATES = {
    "2880x1800": {
        "x1": 0.4424, "y1": 0.045, "x2": 0.5503, "y2": 0.0856,
        "ocr_text": DEFAULT_ID_REGEX,
        "match_mode": "regex",
        "created_at": "2026-09-13 10:53:45",
        "frame_px": [311, 73],
        "client_size": [2880, 1800],
    },
    "2560x1440": {
        "x1": 0.4594, "y1": 0.0021, "x2": 0.5434, "y2": 0.0333,
        "ocr_text": DEFAULT_ID_REGEX,
        "match_mode": "regex",
        "created_at": "2026-09-13 10:56:10",
        "frame_px": [215, 45],
        "client_size": [2560, 1440],
    },
}


DEFAULT_STATE = {
    "window_x": None,
    "window_y": None,
    "md_window_x": None,
    "md_window_y": None,
    "md_window_width": None,
    "md_window_height": None,
    "md_scroll_pos": 0.0,
}


def _deep_copy(d):
    if isinstance(d, dict):
        return {k: _deep_copy(v) for k, v in d.items()}
    if isinstance(d, list):
        return [_deep_copy(x) for x in d]
    return d


def _merge_defaults(data, defaults):
    if not isinstance(data, dict):
        return _deep_copy(defaults)
    out = {}
    for k, v in defaults.items():
        if k in data:
            if isinstance(v, dict) and isinstance(data[k], dict):
                out[k] = _merge_defaults(data[k], v)
            else:
                out[k] = data[k]
        else:
            out[k] = _deep_copy(v)
    for k, v in data.items():
        if k not in out:
            out[k] = v
    return out


def _doc_to_dict(obj):
    if isinstance(obj, dict):
        return {k: _doc_to_dict(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_doc_to_dict(x) for x in obj]
    return obj


# ============================================================
#                    config.toml 生成（带注释）
# ============================================================
def _add_kv(node, key, value, comments=None):
    if comments:
        for c in comments:
            node.add(comment(c))
    node[key] = value
    node.add(nl())


def build_config_doc(cfg):
    doc = tomlkit.document()

    doc.add(comment("=" * 52))
    doc.add(comment("月圆之夜断网工具 配置文件"))
    doc.add(comment("修改后重启工具生效；程序不会覆盖本文件"))
    doc.add(comment("=" * 52))
    doc.add(nl())

    # ---- 顶层 ----
    _add_kv(doc, "block_time", cfg["block_time"],
            ["断网持续秒数（1-3600）"])
    _add_kv(doc, "sound_volume_view_path", cfg["sound_volume_view_path"],
            ["SoundVolumeView.exe 的完整路径，留空则禁用音量功能"])
    _add_kv(doc, "volume_mute_value", cfg["volume_mute_value"],
            ["静音时把音量调到多少（0-100）"])
    _add_kv(doc, "launch_app", cfg["launch_app"],
            ["启动工具时连带启动的程序",
             '  "default" = 同目录的 Night of the Full Moon.exe',
             '  也可以填绝对路径，留空 "" 表示不启动'])
    _add_kv(doc, "block_targets", list(cfg["block_targets"]),
            ["断网的目标程序列表",
             '  "default" = 同目录的 Night of the Full Moon.exe',
             '  也可以填多个绝对路径'])
    _add_kv(doc, "ping_target", cfg["ping_target"],
            ['Ping 显示目标，留空 "" 表示禁用'])
    _add_kv(doc, "auto_exit_on_game_exit", cfg["auto_exit_on_game_exit"],
            ["目标游戏退出时是否自动退出本工具"])

    # ---- UI ----
    doc.add(comment("=" * 52))
    doc.add(comment("界面设置"))
    doc.add(comment("=" * 52))
    doc.add(nl())

    ui = table()
    _add_kv(ui, "window_width", cfg["ui"]["window_width"],
            ["主窗口宽度（像素）"])
    _add_kv(ui, "window_height", cfg["ui"]["window_height"],
            ["主窗口高度（像素）"])
    _add_kv(ui, "bg_color", cfg["ui"]["bg_color"],
            ["主背景色（#RRGGBB）"])
    _add_kv(ui, "drag_color", cfg["ui"]["drag_color"],
            ["顶部拖动条颜色"])
    _add_kv(ui, "transparent_color", cfg["ui"]["transparent_color"],
            ["透明色（不要和 UI 其他颜色重合）"])
    _add_kv(ui, "long_press_ms", cfg["ui"]["long_press_ms"],
            ["长按 👁 进入框选的判定时间（毫秒）"])
    _add_kv(ui, "multi_click_count", cfg["ui"]["multi_click_count"],
            ["连击 👁 切换调试边框的次数"])
    _add_kv(ui, "multi_click_window_s", cfg["ui"]["multi_click_window_s"],
            ["连击判定窗口（秒）"])
    _add_kv(ui, "toggle_click_delay_ms", cfg["ui"]["toggle_click_delay_ms"],
            ["短按 👁 延迟执行 toggle 的毫秒数（避免和长按冲突）"])

    ui.add(comment("-" * 52))
    ui.add(comment("日志窗口"))
    ui.add(nl())
    lw = table()
    _add_kv(lw, "width", cfg["ui"]["log_window"]["width"], ["宽度（像素）"])
    _add_kv(lw, "height", cfg["ui"]["log_window"]["height"], ["高度（像素）"])
    ui["log_window"] = lw

    ui.add(comment("-" * 52))
    ui.add(comment("文本查看窗口（📄 按钮）"))
    ui.add(nl())
    mw = table()
    _add_kv(mw, "width", cfg["ui"]["md_window"]["width"],
            ["宽度（像素，作为首次打开的默认值）"])
    _add_kv(mw, "height", cfg["ui"]["md_window"]["height"],
            ["高度（像素，作为首次打开的默认值）"])
    _add_kv(mw, "font_family", cfg["ui"]["md_window"]["font_family"], ["字体"])
    _add_kv(mw, "font_size", cfg["ui"]["md_window"]["font_size"], ["字号"])
    _add_kv(mw, "font_color", cfg["ui"]["md_window"]["font_color"], ["文字颜色"])
    _add_kv(mw, "bg_color", cfg["ui"]["md_window"]["bg_color"], ["背景色"])
    ui["md_window"] = mw

    ui.add(comment("-" * 52))
    ui.add(comment("OCR 确认对话框"))
    ui.add(nl())
    od = table()
    _add_kv(od, "width", cfg["ui"]["ocr_dialog"]["width"], ["宽度（像素）"])
    _add_kv(od, "height", cfg["ui"]["ocr_dialog"]["height"], ["高度（像素）"])
    ui["ocr_dialog"] = od

    doc["ui"] = ui

    # ---- timing ----
    doc.add(comment("=" * 52))
    doc.add(comment("时间间隔"))
    doc.add(comment("=" * 52))
    doc.add(nl())

    tm = table()
    _add_kv(tm, "clock_interval_ms", cfg["timing"]["clock_interval_ms"],
            ["时钟刷新间隔（毫秒）"])
    _add_kv(tm, "animation_interval_ms", cfg["timing"]["animation_interval_ms"],
            ["心跳动画刷新间隔（毫秒）"])
    _add_kv(tm, "ping_interval_s", cfg["timing"]["ping_interval_s"],
            ["Ping 检测间隔（秒）"])
    _add_kv(tm, "game_monitor_interval_s", cfg["timing"]["game_monitor_interval_s"],
            ["游戏进程监控间隔（秒），用于判断游戏是否退出"])
    doc["timing"] = tm

    # ---- img_watch ----
    doc.add(comment("=" * 52))
    doc.add(comment("OCR 监控"))
    doc.add(comment("=" * 52))
    doc.add(nl())

    iw = table()
    _add_kv(iw, "enabled", cfg["img_watch"]["enabled"],
            ["启动时是否自动启用"])
    _add_kv(iw, "interval", cfg["img_watch"]["interval"],
            ["检测间隔（秒），越小越快但 CPU 占用越高"])
    _add_kv(iw, "consecutive", cfg["img_watch"]["consecutive"],
            ["连续 N 帧命中才算触发（防抖）"])
    _add_kv(iw, "cooldown", cfg["img_watch"]["cooldown"],
            ["触发后冷却时间（秒），期间不重复触发"])
    _add_kv(iw, "debug_log", cfg["img_watch"]["debug_log"],
            ["在日志窗口打印每帧详情"])
    _add_kv(iw, "debug_overlay", cfg["img_watch"]["debug_overlay"],
            ["显示红色边框叠加层（也可连击 👁 切换）"])
    _add_kv(iw, "trigger_mode", cfg["img_watch"]["trigger_mode"],
            ['触发模式：',
             '  "appear"    - 文字出现就断网（默认）',
             '  "disappear" - 文字消失才断网'])
    _add_kv(iw, "require_foreground", cfg["img_watch"]["require_foreground"],
            ["要求目标窗口在前台才检测"])
    doc["img_watch"] = iw

    return doc


# ============================================================
#                    templates.toml 生成（带注释）
# ============================================================
def build_templates_doc(templates):
    doc = tomlkit.document()

    doc.add(comment("=" * 52))
    doc.add(comment("OCR 模板数据"))
    doc.add(comment("每个客户区分辨率一份，程序自动维护"))
    doc.add(comment("想重新采集，长按 👁 进入框选"))
    doc.add(comment("=" * 52))
    doc.add(nl())

    if not isinstance(templates, dict) or not templates:
        doc.add(comment("（暂无模板）"))
        return doc

    for size_key, tpl in templates.items():
        if not isinstance(tpl, dict):
            continue
        doc.add(comment("-" * 52))
        doc.add(comment(f"分辨率 {size_key}"))
        doc.add(comment("-" * 52))
        t = table()
        _add_kv(t, "x1", tpl.get("x1", 0.4), ["ROI 左（0~1 相对客户区）"])
        _add_kv(t, "y1", tpl.get("y1", 0.05), ["ROI 上"])
        _add_kv(t, "x2", tpl.get("x2", 0.6), ["ROI 右"])
        _add_kv(t, "y2", tpl.get("y2", 0.1), ["ROI 下"])
        _add_kv(t, "ocr_text", tpl.get("ocr_text", ""),
                ["期望文字或正则表达式"])
        _add_kv(t, "match_mode", tpl.get("match_mode", "regex"),
                ["匹配模式：contains / equals / regex"])
        created = tpl.get("created_at", "")
        if created:
            _add_kv(t, "created_at", created, ["创建时间"])
        doc[size_key] = t
        doc.add(nl())

    return doc


# ============================================================
#                    state.toml 生成
# ============================================================
def build_state_doc(state):
    doc = tomlkit.document()
    doc.add(comment("运行时状态（程序自动维护，无需手改）"))
    doc.add(nl())

    for k in ("window_x", "window_y"):
        v = state.get(k)
        if v is not None:
            _add_kv(doc, k, v)
    for k in ("md_window_x", "md_window_y",
              "md_window_width", "md_window_height"):
        v = state.get(k)
        if v is not None:
            _add_kv(doc, k, v)
    v = state.get("md_scroll_pos", 0.0)
    if v is not None:
        _add_kv(doc, "md_scroll_pos", v)
    return doc


# ============================================================
#                    读写配置
# ============================================================
def load_config():
    global _config_verbose_printed
    first_call = not _config_verbose_printed

    # ---- config ----
    if os.path.exists(CONFIG_TOML):
        try:
            with open(CONFIG_TOML, "r", encoding="utf-8") as f:
                doc = tomlkit.load(f)
            cfg = _doc_to_dict(doc)
            if first_call:
                print("✅ config.toml 解析成功。", flush=True)
        except Exception as e:
            print(f"❌ config.toml 解析失败: {e}，使用默认配置。", flush=True)
            cfg = _deep_copy(DEFAULT_CONFIG)
    else:
        cfg = _deep_copy(DEFAULT_CONFIG)
        if first_call:
            print("ℹ️ 未找到 config.toml，生成默认配置。", flush=True)
        with open(CONFIG_TOML, "w", encoding="utf-8") as f:
            tomlkit.dump(build_config_doc(cfg), f)

    cfg = _merge_defaults(cfg, DEFAULT_CONFIG)

    # ---- templates ----
    tpl = None
    if os.path.exists(TEMPLATES_TOML):
        try:
            with open(TEMPLATES_TOML, "r", encoding="utf-8") as f:
                tpl_doc = tomlkit.load(f)
            tpl = _doc_to_dict(tpl_doc)
            if first_call:
                print(f"✅ templates.toml 解析成功，共 {len(tpl)} 份模板。", flush=True)
        except Exception as e:
            print(f"❌ templates.toml 解析失败: {e}", flush=True)
    if tpl is None:
        tpl = _deep_copy(DEFAULT_TEMPLATES)
        with open(TEMPLATES_TOML, "w", encoding="utf-8") as f:
            tomlkit.dump(build_templates_doc(tpl), f)

    # ---- state ----
    st = None
    if os.path.exists(STATE_TOML):
        try:
            with open(STATE_TOML, "r", encoding="utf-8") as f:
                st_doc = tomlkit.load(f)
            st = _doc_to_dict(st_doc)
        except Exception as e:
            print(f"⚠️ state.toml 解析失败: {e}", flush=True)
    if st is None:
        st = _deep_copy(DEFAULT_STATE)

    # 校验 trigger_mode
    iw = cfg.get("img_watch", {})
    if iw.get("trigger_mode") not in ("appear", "disappear"):
        iw["trigger_mode"] = "appear"

    if first_call:
        sv = cfg.get("sound_volume_view_path", "")
        if sv:
            print(f"🔊 SoundVolumeView 路径：{sv}", flush=True)
        else:
            print("🔇 未配置 SoundVolumeView 路径（音量控制禁用）。", flush=True)
        print(f"📷 触发模式：{iw.get('trigger_mode', 'appear')}  "
              f"前台要求：{iw.get('require_foreground', False)}  "
              f"边框：{'开' if iw.get('debug_overlay', True) else '关'}", flush=True)
        print(f"🔤 OCR：{'可用' if _OCR_AVAILABLE else '未安装 rapidocr-onnxruntime'}",
              flush=True)

    _config_verbose_printed = True
    return cfg, tpl, st


def update_config_field(key_path, value):
    """只更新 config.toml 中某个字段，保留其他内容和注释"""
    try:
        with open(CONFIG_TOML, "r", encoding="utf-8") as f:
            doc = tomlkit.load(f)
        node = doc
        for k in key_path[:-1]:
            node = node[k]
        node[key_path[-1]] = value
        with open(CONFIG_TOML, "w", encoding="utf-8") as f:
            tomlkit.dump(doc, f)
        return True
    except Exception as e:
        print(f"❌ 更新 config.toml 失败（{key_path}）: {e}", flush=True)
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


def get_dpi_scale():
    try:
        hdc = windll.user32.GetDC(0)
        dpi_x = windll.gdi32.GetDeviceCaps(hdc, 88)
        windll.user32.ReleaseDC(0, hdc)
        return max(1.0, dpi_x / 96.0)
    except:
        return 1.0


def resolve_exe_path(value):
    if value == "default":
        return os.path.join(SCRIPT_DIR, DEFAULT_GAME_NAME)
    return value


def is_process_running(exe_path):
    if not exe_path:
        return False
    exe_name = os.path.basename(exe_path)
    try:
        cmd = f'tasklist /fi "imagename eq {exe_name}" /fo csv /nh'
        output = subprocess.check_output(cmd, shell=True, encoding='gbk')
        return exe_name in output
    except:
        return False


# ============================================================
#                    窗口工具
# ============================================================
_user32 = ctypes.windll.user32
_dwmapi = ctypes.windll.dwmapi
DWMWA_CLOAKED = 14
GA_ROOT = 2
GWL_STYLE = -16
GWL_EXSTYLE = -20
WS_CHILD = 0x40000000
WS_EX_TRANSPARENT = 0x20
GW_OWNER = 4


def set_click_through(hwnd):
    try:
        ex = _user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        _user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex | WS_EX_TRANSPARENT)
    except:
        pass


def get_hwnd_by_pid(pid):
    if not pid:
        return None
    result = []
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, _):
        if not _user32.IsWindowVisible(hwnd):
            return True
        wpid = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
        if wpid.value != pid:
            return True
        style = _user32.GetWindowLongW(hwnd, GWL_STYLE)
        if style & WS_CHILD:
            return True
        if _user32.GetWindow(hwnd, GW_OWNER):
            return True
        r = wintypes.RECT()
        _user32.GetWindowRect(hwnd, ctypes.byref(r))
        if r.right - r.left <= 0 or r.bottom - r.top <= 0:
            return True
        result.append(hwnd)
        return True

    _user32.EnumWindows(WNDENUMPROC(cb), 0)
    return result[0] if result else None


def get_pid_by_exe_name(exe_name):
    if not exe_name:
        return None
    try:
        out = subprocess.check_output(
            f'tasklist /fi "imagename eq {exe_name}" /fo csv /nh',
            shell=True, encoding='gbk', errors='ignore'
        )
        for line in out.splitlines():
            parts = [p.strip('"') for p in line.split('","')]
            if len(parts) >= 2 and parts[0].lower() == exe_name.lower():
                try:
                    return int(parts[1])
                except:
                    pass
    except:
        pass
    return None


def get_window_rect(hwnd):
    r = wintypes.RECT()
    _user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def get_client_rect_screen(hwnd):
    r = wintypes.RECT()
    _user32.GetClientRect(hwnd, ctypes.byref(r))
    pt = wintypes.POINT(0, 0)
    _user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return pt.x, pt.y, pt.x + (r.right - r.left), pt.y + (r.bottom - r.top)


def is_window_alive(hwnd):
    return bool(hwnd) and bool(_user32.IsWindow(hwnd))


def is_window_visible(hwnd):
    return bool(_user32.IsWindowVisible(hwnd))


def is_window_minimized(hwnd):
    return bool(_user32.IsIconic(hwnd))


def is_window_cloaked(hwnd):
    val = ctypes.c_int(0)
    try:
        _dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED,
                                      ctypes.byref(val), ctypes.sizeof(val))
    except:
        return False
    return val.value != 0


def has_valid_rect(hwnd):
    l, t, r, b = get_window_rect(hwnd)
    if r - l <= 0 or b - t <= 0:
        return False
    if l < -10000 or t < -10000:
        return False
    return True


def is_window_foreground(hwnd):
    if not hwnd:
        return False
    try:
        fg = _user32.GetForegroundWindow()
        if not fg:
            return False
        if fg == hwnd:
            return True
        root = _user32.GetAncestor(fg, GA_ROOT)
        return root == hwnd
    except:
        return False


def _is_ancestor_of_any(hwnd, candidates):
    if not hwnd or not candidates:
        return False
    cand = set(c for c in candidates if c)
    root = _user32.GetAncestor(hwnd, GA_ROOT)
    if root in cand:
        return True
    cur = hwnd
    for _ in range(8):
        if cur in cand:
            return True
        cur = _user32.GetAncestor(cur, GA_ROOT)
        if not cur:
            break
    return False


def is_window_covered(hwnd, exclude_hwnds=(), samples=None):
    if samples is None:
        samples = [(0.5, 0.5), (0.2, 0.2), (0.8, 0.2), (0.2, 0.8), (0.8, 0.8)]

    l, t, r, b = get_client_rect_screen(hwnd)
    w, h = r - l, b - t
    if w <= 0 or h <= 0:
        return True

    for fx, fy in samples:
        px = l + int(w * fx)
        py = t + int(h * fy)
        pt = wintypes.POINT(px, py)
        top = _user32.WindowFromPoint(pt)
        if not top:
            return True
        root = _user32.GetAncestor(top, GA_ROOT)
        if root == hwnd:
            continue
        if _is_ancestor_of_any(top, exclude_hwnds):
            continue
        return True
    return False


# ============================================================
#               截图
# ============================================================
def capture_roi_bgra(hwnd, roi_ratio):
    if not _IMGWATCH_AVAILABLE:
        return None, None

    l, t, r, b = get_client_rect_screen(hwnd)
    cw, ch = r - l, b - t
    if cw <= 0 or ch <= 0:
        return None, None

    x1, y1, x2, y2 = roi_ratio
    rl = l + int(cw * x1)
    rt = t + int(ch * y1)
    rw = max(1, int(cw * (x2 - x1)))
    rh = max(1, int(ch * (y2 - y1)))

    region = {"left": rl, "top": rt, "width": rw, "height": rh}
    try:
        with _mss_factory() as sct:
            img = np.array(sct.grab(region), dtype=np.uint8)
    except Exception as e:
        print(f"截图失败: {e}", flush=True)
        return None, None

    return img, (rl, rt, rw, rh)


# ============================================================
#                    鼠标框选器
# ============================================================
class RegionSelector:
    TRANSPARENT = "#FE01FE"
    HANDLE_SIZE = 8
    HANDLE_HIT = 14
    BTN_W = 70
    BTN_H = 34
    BTN_GAP = 12
    BTN_OFFSET = 20
    SCREEN_MARGIN = 10

    def __init__(self, root, hint_text, on_done, on_cancel=None, scale=1.0):
        self.root = root
        self.hint_text = hint_text
        self.on_done = on_done
        self.on_cancel = on_cancel
        self.scale = scale

        self.mask_top = None
        self.ui_top = None
        self.mask_canvas = None
        self.ui_canvas = None

        self.hint_id = None
        self.rect_id = None
        self.size_text_id = None
        self.handle_ids = []
        self.btn_confirm_bg = None
        self.btn_confirm_txt = None
        self.btn_cancel_bg = None
        self.btn_cancel_txt = None
        self._btn_rects = {}

        self.rect_x0 = None
        self.rect_y0 = None
        self.rect_x1 = None
        self.rect_y1 = None

        self.mode = None
        self.drag_anchor = None
        self.resize_corner = None
        self.corners_visible = False

        self.sw = 0
        self.sh = 0
        self.active = False

    def show(self):
        if self.mask_top is not None and self.mask_top.winfo_exists():
            return

        mask_top = tk.Toplevel(self.root)
        mask_top.overrideredirect(True)
        mask_top.attributes('-topmost', True)
        try:
            mask_top.attributes('-alpha', 0.15)
        except Exception as e:
            print(f"⚠️ 设置遮罩透明度失败: {e}", flush=True)
        mask_top.configure(bg='#000000')
        self.sw = mask_top.winfo_screenwidth()
        self.sh = mask_top.winfo_screenheight()
        mask_top.geometry(f"{self.sw}x{self.sh}+0+0")

        self.mask_canvas = tk.Canvas(mask_top, bg='#000000', highlightthickness=0, bd=0)
        self.mask_canvas.pack(fill=tk.BOTH, expand=True)

        ui_top = tk.Toplevel(self.root)
        ui_top.overrideredirect(True)
        ui_top.attributes('-topmost', True)
        ui_top.configure(bg=self.TRANSPARENT)
        try:
            ui_top.attributes('-transparentcolor', self.TRANSPARENT)
        except Exception as e:
            print(f"⚠️ 设置 UI 层透明色失败: {e}", flush=True)
        ui_top.geometry(f"{self.sw}x{self.sh}+0+0")

        self.ui_canvas = tk.Canvas(ui_top, bg=self.TRANSPARENT, highlightthickness=0, bd=0)
        self.ui_canvas.pack(fill=tk.BOTH, expand=True)

        try:
            ui_top.update_idletasks()
            raw = ui_top.winfo_id()
            top_hwnd = _user32.GetAncestor(raw, GA_ROOT) or raw
            set_click_through(top_hwnd)
        except Exception as e:
            print(f"⚠️ 设置 UI 层穿透失败: {e}", flush=True)

        hint_size = -max(14, int(22 * self.scale))
        self.hint_id = self.ui_canvas.create_text(
            self.sw // 2, self.sh // 2,
            text=self.hint_text, fill='#FFFFFF',
            font=("微软雅黑", hint_size, "bold")
        )

        self.mask_canvas.bind("<ButtonPress-1>", self._on_press)
        self.mask_canvas.bind("<B1-Motion>", self._on_drag)
        self.mask_canvas.bind("<ButtonRelease-1>", self._on_release)
        self.mask_canvas.bind("<Motion>", self._on_motion)
        mask_top.bind("<Escape>", lambda e: self._cancel())
        mask_top.focus_force()

        self.mask_top = mask_top
        self.ui_top = ui_top
        self.active = True
        print("🔲 已进入框选模式", flush=True)

    def _inside_rect(self, x, y):
        if None in (self.rect_x0, self.rect_y0, self.rect_x1, self.rect_y1):
            return False
        x0 = min(self.rect_x0, self.rect_x1)
        x1 = max(self.rect_x0, self.rect_x1)
        y0 = min(self.rect_y0, self.rect_y1)
        y1 = max(self.rect_y0, self.rect_y1)
        return (x0 <= x <= x1) and (y0 <= y <= y1)

    def _hit_corner(self, x, y):
        if None in (self.rect_x0, self.rect_y0, self.rect_x1, self.rect_y1):
            return None
        x0 = min(self.rect_x0, self.rect_x1)
        x1 = max(self.rect_x0, self.rect_x1)
        y0 = min(self.rect_y0, self.rect_y1)
        y1 = max(self.rect_y0, self.rect_y1)
        r = self.HANDLE_HIT * self.scale
        corners = {'nw': (x0, y0), 'ne': (x1, y0), 'sw': (x0, y1), 'se': (x1, y1)}
        for name, (cx, cy) in corners.items():
            if abs(x - cx) <= r and abs(y - cy) <= r:
                return name
        return None

    def _hit_button(self, x, y):
        if not self._btn_rects:
            return None
        for name, (bx0, by0, bx1, by1) in self._btn_rects.items():
            if bx0 <= x <= bx1 and by0 <= y <= by1:
                return name
        return None

    def _on_press(self, event):
        if not self.active:
            return
        x, y = event.x, event.y

        btn = self._hit_button(x, y)
        if btn == "confirm":
            self._confirm()
            return
        elif btn == "cancel":
            self._cancel()
            return

        corner = self._hit_corner(x, y)
        if corner is not None:
            self.mode = "resize"
            self.resize_corner = corner
            self.drag_anchor = (x, y)
            return

        if self._inside_rect(x, y):
            self.mode = "move"
            self.drag_anchor = (x, y)
            return

        self.mode = "draw"
        self.rect_x0 = x
        self.rect_y0 = y
        self.rect_x1 = x
        self.rect_y1 = y
        self.drag_anchor = (x, y)
        self._clear_buttons()
        self._set_corners_visible(False)

    def _on_drag(self, event):
        if not self.active:
            return
        x, y = event.x, event.y
        if self.mode == "draw":
            self.rect_x1 = x
            self.rect_y1 = y
        elif self.mode == "move":
            if self.drag_anchor is None:
                return
            dx = x - self.drag_anchor[0]
            dy = y - self.drag_anchor[1]
            self.rect_x0 += dx
            self.rect_x1 += dx
            self.rect_y0 += dy
            self.rect_y1 += dy
            self.drag_anchor = (x, y)
        elif self.mode == "resize":
            if self.resize_corner == 'nw':
                self.rect_x0 = x; self.rect_y0 = y
            elif self.resize_corner == 'ne':
                self.rect_x1 = x; self.rect_y0 = y
            elif self.resize_corner == 'sw':
                self.rect_x0 = x; self.rect_y1 = y
            elif self.resize_corner == 'se':
                self.rect_x1 = x; self.rect_y1 = y
        self._redraw()

    def _on_release(self, event):
        if not self.active:
            return
        self.mode = None
        self.drag_anchor = None
        self.resize_corner = None
        self._redraw()
        if self._rect_valid():
            self._show_buttons()
            self._on_motion(event)

    def _on_motion(self, event):
        if not self.active:
            return
        x, y = event.x, event.y
        corner = self._hit_corner(x, y)
        new_vis = corner is not None
        if new_vis != self.corners_visible:
            self._set_corners_visible(new_vis)
        try:
            if corner in ('nw', 'se'):
                self.mask_canvas.config(cursor="size_nw_se")
            elif corner in ('ne', 'sw'):
                self.mask_canvas.config(cursor="size_ne_sw")
            elif self._inside_rect(x, y):
                self.mask_canvas.config(cursor="fleur")
            else:
                self.mask_canvas.config(cursor="crosshair")
        except:
            pass

    def _rect_valid(self):
        if None in (self.rect_x0, self.rect_y0, self.rect_x1, self.rect_y1):
            return False
        return abs(self.rect_x1 - self.rect_x0) >= 8 and abs(self.rect_y1 - self.rect_y0) >= 8

    def _redraw(self):
        if None in (self.rect_x0, self.rect_y0, self.rect_x1, self.rect_y1):
            return
        x0 = min(self.rect_x0, self.rect_x1)
        y0 = min(self.rect_y0, self.rect_y1)
        x1 = max(self.rect_x0, self.rect_x1)
        y1 = max(self.rect_y0, self.rect_y1)

        if self.rect_id is None:
            self.rect_id = self.ui_canvas.create_rectangle(
                x0, y0, x1, y1, outline='#FFEB3B', width=3, fill=''
            )
        else:
            self.ui_canvas.coords(self.rect_id, x0, y0, x1, y1)

        self._draw_handles(x0, y0, x1, y1)

        w = x1 - x0
        h = y1 - y0
        text = f"{w} x {h}"
        size_font = -max(12, int(14 * self.scale))
        tx = min(self.sw - 80, x1 + 10)
        ty = min(self.sh - 20, y1 + 10)
        if self.size_text_id is None:
            self.size_text_id = self.ui_canvas.create_text(
                tx, ty, anchor='nw', text=text,
                fill='#FFEB3B', font=("Consolas", size_font, "bold")
            )
        else:
            self.ui_canvas.coords(self.size_text_id, tx, ty)
            self.ui_canvas.itemconfig(self.size_text_id, text=text)

        if self.btn_confirm_bg is not None:
            self._show_buttons()

    def _draw_handles(self, x0, y0, x1, y1):
        hs = self.HANDLE_SIZE * self.scale
        positions = [(x0, y0), (x1, y0), (x0, y1), (x1, y1)]
        while len(self.handle_ids) < 4:
            self.handle_ids.append(
                self.ui_canvas.create_rectangle(
                    0, 0, 0, 0, fill='#FFEB3B', outline='#333', width=1,
                    state='hidden'
                )
            )
        for i, (cx, cy) in enumerate(positions):
            self.ui_canvas.coords(self.handle_ids[i],
                                  cx - hs, cy - hs, cx + hs, cy + hs)

    def _set_corners_visible(self, visible):
        self.corners_visible = visible
        state = 'normal' if visible else 'hidden'
        for item in self.handle_ids:
            try:
                self.ui_canvas.itemconfig(item, state=state)
            except:
                pass

    def _clear_buttons(self):
        for item in (self.btn_confirm_bg, self.btn_confirm_txt,
                     self.btn_cancel_bg, self.btn_cancel_txt):
            if item is not None:
                try:
                    self.ui_canvas.delete(item)
                except:
                    pass
        self.btn_confirm_bg = None
        self.btn_confirm_txt = None
        self.btn_cancel_bg = None
        self.btn_cancel_txt = None
        self._btn_rects = {}

    def _compute_button_position(self):
        if None in (self.rect_x0, self.rect_y0, self.rect_x1, self.rect_y1):
            return None
        x0 = min(self.rect_x0, self.rect_x1)
        x1 = max(self.rect_x0, self.rect_x1)
        y0 = min(self.rect_y0, self.rect_y1)
        y1 = max(self.rect_y0, self.rect_y1)
        S = self.scale
        bw = int(self.BTN_W * S)
        bh = int(self.BTN_H * S)
        gap = int(self.BTN_GAP * S)
        offset = int(self.BTN_OFFSET * S)
        total_w = bw * 2 + gap
        M = self.SCREEN_MARGIN
        cx_center = (x0 + x1) // 2
        cy_center = (y0 + y1) // 2

        if y1 + offset + bh <= self.sh - M:
            bx = max(M, min(self.sw - total_w - M, cx_center - total_w // 2))
            return bx, y1 + offset, 'bottom'
        if y0 - offset - bh >= M:
            bx = max(M, min(self.sw - total_w - M, cx_center - total_w // 2))
            return bx, y0 - offset - bh, 'top'
        if x1 + offset + total_w <= self.sw - M:
            by = max(M, min(self.sh - bh - M, cy_center - bh // 2))
            return x1 + offset, by, 'right'
        if x0 - offset - total_w >= M:
            by = max(M, min(self.sh - bh - M, cy_center - bh // 2))
            return x0 - offset - total_w, by, 'left'
        bx = (self.sw - total_w) // 2
        by = self.sh - bh - int(20 * S)
        return bx, by, 'fallback'

    def _show_buttons(self):
        self._clear_buttons()
        pos = self._compute_button_position()
        if pos is None:
            return
        bx, by, _ = pos
        S = self.scale
        bw = int(self.BTN_W * S)
        bh = int(self.BTN_H * S)
        gap = int(self.BTN_GAP * S)

        cx0 = bx; cx1 = bx + bw; cy0 = by; cy1 = by + bh
        self.btn_confirm_bg = self.ui_canvas.create_rectangle(
            cx0, cy0, cx1, cy1, fill='#4CAF50', outline='#2E7D32', width=2
        )
        self.btn_confirm_txt = self.ui_canvas.create_text(
            (cx0 + cx1) // 2, (cy0 + cy1) // 2, text="✓ 确认",
            fill='white', font=("微软雅黑", -max(12, int(13 * S)), "bold")
        )
        self._btn_rects['confirm'] = (cx0, cy0, cx1, cy1)

        dx0 = bx + bw + gap; dx1 = dx0 + bw; dy0 = by; dy1 = by + bh
        self.btn_cancel_bg = self.ui_canvas.create_rectangle(
            dx0, dy0, dx1, dy1, fill='#F44336', outline='#B71C1C', width=2
        )
        self.btn_cancel_txt = self.ui_canvas.create_text(
            (dx0 + dx1) // 2, (dy0 + dy1) // 2, text="✕ 取消",
            fill='white', font=("微软雅黑", -max(12, int(13 * S)), "bold")
        )
        self._btn_rects['cancel'] = (dx0, dy0, dx1, dy1)

    def _confirm(self):
        if not self._rect_valid():
            return
        x0 = int(min(self.rect_x0, self.rect_x1))
        y0 = int(min(self.rect_y0, self.rect_y1))
        x1 = int(max(self.rect_x0, self.rect_x1))
        y1 = int(max(self.rect_y0, self.rect_y1))
        self._close()
        if self.on_done:
            self.on_done(x0, y0, x1, y1)

    def _cancel(self):
        self._close()
        if self.on_cancel:
            self.on_cancel()

    def _close(self):
        self.active = False
        for w in (self.mask_top, self.ui_top):
            if w is not None and w.winfo_exists():
                try:
                    w.destroy()
                except:
                    pass
        self.mask_top = None
        self.ui_top = None


# ============================================================
#                    ROI 调试叠加框
# ============================================================
class RoiOverlay:
    TRANSPARENT = "#FE01FE"

    def __init__(self, root, exe_name, scale=1.0, color="#FF3B30", get_templates_cb=None):
        self.root = root
        self.exe_name = exe_name
        self.scale = scale
        self.color = color
        self.get_templates_cb = get_templates_cb
        self.top = None
        self.canvas = None
        self.rect_id = None
        self.hwnd = None
        self._job = None

    def show(self):
        if self.top is not None and self.top.winfo_exists():
            self.top.deiconify()
            self.top.lift()
            return

        top = tk.Toplevel(self.root)
        top.overrideredirect(True)
        top.attributes('-topmost', True)
        top.configure(bg=self.TRANSPARENT)
        try:
            top.attributes('-transparentcolor', self.TRANSPARENT)
        except Exception as e:
            print(f"⚠️ 叠加框透明色设置失败: {e}", flush=True)

        self.canvas = tk.Canvas(top, bg=self.TRANSPARENT, highlightthickness=0, bd=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        bw = max(1, int(2 * self.scale))
        self.rect_id = self.canvas.create_rectangle(
            bw, bw, bw + 2, bw + 2, outline=self.color, width=bw, fill=""
        )
        self.top = top
        try:
            raw = top.winfo_id()
            self.hwnd = _user32.GetAncestor(raw, GA_ROOT) or raw
        except:
            self.hwnd = None
        print(f"👁 调试叠加框已显示 hwnd={self.hwnd}", flush=True)
        self._tick_update()

    def hide(self):
        if self._job:
            try:
                self.root.after_cancel(self._job)
            except:
                pass
            self._job = None
        if self.top is not None and self.top.winfo_exists():
            try:
                self.top.destroy()
            except:
                pass
        self.top = None
        self.hwnd = None

    def _tick_update(self):
        if self.top is None or not self.top.winfo_exists():
            return

        pid = get_pid_by_exe_name(self.exe_name)
        hwnd = get_hwnd_by_pid(pid) if pid else None
        if hwnd and is_window_alive(hwnd):
            l, t, r, b = get_client_rect_screen(hwnd)
            cw, ch = r - l, b - t
            if cw > 0 and ch > 0:
                size_key = f"{cw}x{ch}"
                tpl = self._find_template_for_size(size_key)
                if tpl:
                    x1 = tpl["x1"]; y1 = tpl["y1"]; x2 = tpl["x2"]; y2 = tpl["y2"]
                    rl = l + int(cw * x1)
                    rt = t + int(ch * y1)
                    rw = max(4, int(cw * (x2 - x1)))
                    rh = max(4, int(ch * (y2 - y1)))
                    pad = max(3, int(4 * self.scale))
                    rl_o = rl - pad
                    rt_o = rt - pad
                    rw_o = rw + pad * 2
                    rh_o = rh + pad * 2
                    bw = max(1, int(2 * self.scale))
                    try:
                        self.top.geometry(f"{rw_o}x{rh_o}+{rl_o}+{rt_o}")
                        self.canvas.coords(self.rect_id, bw, bw, rw_o - bw, rh_o - bw)
                    except:
                        pass
                else:
                    try:
                        self.top.geometry("1x1+0+0")
                    except:
                        pass

        self._job = self.root.after(150, self._tick_update)

    def _find_template_for_size(self, size_key):
        if self.get_templates_cb is None:
            return None
        try:
            templates = self.get_templates_cb()
            if isinstance(templates, dict):
                return templates.get(size_key)
        except:
            pass
        return None


# ============================================================
#                    OCR 监控线程
# ============================================================
class TemplateWatcher:
    def __init__(self, exe_path, config, templates, overlay=None, on_match=None, own_hwnds_cb=None):
        self.exe_path = exe_path
        self.exe_name = os.path.basename(exe_path) if exe_path else ""
        self.cfg = config
        self.templates = templates if isinstance(templates, dict) else {}
        self.overlay = overlay
        self.on_match = on_match
        self.own_hwnds_cb = own_hwnds_cb
        self.stop_event = Event()
        self.hwnd = None
        self.pid = None

        self.current_template = None
        self.current_size_key = ""
        self.current_src = ""
        self._missing_warned = ""

    def start(self):
        Thread(target=self._run, daemon=True).start()

    def stop(self):
        self.stop_event.set()

    def _refresh_hwnd(self):
        pid = get_pid_by_exe_name(self.exe_name)
        if pid is None:
            self.hwnd = None
            self.pid = None
            return False
        if pid != self.pid or not is_window_alive(self.hwnd):
            self.pid = pid
            self.hwnd = get_hwnd_by_pid(pid)
        return self.hwnd is not None

    def _refresh_template(self):
        if not self.hwnd or not is_window_alive(self.hwnd):
            self.current_template = None
            self.current_src = "none"
            return
        try:
            l, t, r, b = get_client_rect_screen(self.hwnd)
            cw, ch = r - l, b - t
            if cw <= 0 or ch <= 0:
                self.current_template = None
                self.current_src = "invalid"
                return
            size_key = f"{cw}x{ch}"
            self.current_size_key = size_key
            if size_key in self.templates:
                self.current_template = self.templates[size_key]
                self.current_src = f"template:{size_key}"
                return
            self.current_template = None
            self.current_src = f"missing:{size_key}"
        except Exception as e:
            print(f"👁 刷新模板失败: {e}", flush=True)
            self.current_template = None
            self.current_src = "error"

    def _collect_exclude(self):
        exclude = []
        if self.overlay is not None and self.overlay.hwnd:
            exclude.append(self.overlay.hwnd)
        if self.own_hwnds_cb is not None:
            try:
                own = self.own_hwnds_cb()
                if own:
                    exclude.extend(own)
            except Exception as e:
                print(f"👁 白名单收集失败: {e}", flush=True)
        return list(set(exclude))

    def _run(self):
        hits = 0
        miss_hits = 0
        have_seen = False

        last_trigger = 0.0
        covered_log_counter = 0
        fg_skip_counter = 0

        iw = self.cfg.get("img_watch", {})
        interval = float(iw.get("interval", 0.5))
        consecutive = int(iw.get("consecutive", 2))
        cooldown = float(iw.get("cooldown", 10.0))
        debug = bool(iw.get("debug_log", False))
        trigger_mode = iw.get("trigger_mode", "appear")
        require_fg = bool(iw.get("require_foreground", False))

        if not _OCR_AVAILABLE:
            print("⚠️ 未安装 rapidocr-onnxruntime，OCR 监控禁用", flush=True)

        print(f"👁 监控线程启动：触发模式={trigger_mode} 前台要求={require_fg}", flush=True)

        while not self.stop_event.is_set():
            try:
                if not self._refresh_hwnd():
                    hits = 0
                    miss_hits = 0
                    time.sleep(max(interval, 1.0))
                    continue

                if (not is_window_alive(self.hwnd)
                        or not is_window_visible(self.hwnd)
                        or is_window_minimized(self.hwnd)
                        or is_window_cloaked(self.hwnd)
                        or not has_valid_rect(self.hwnd)):
                    hits = 0
                    miss_hits = 0
                    time.sleep(interval)
                    continue

                if require_fg and not is_window_foreground(self.hwnd):
                    fg_skip_counter += 1
                    if fg_skip_counter % 20 == 1:
                        print(f"👁 目标窗口不在前台，跳过检测（累计 {fg_skip_counter} 次）", flush=True)
                    hits = 0
                    miss_hits = 0
                    time.sleep(interval)
                    continue
                fg_skip_counter = 0

                self._refresh_template()

                if self.current_template is None:
                    if self._missing_warned != self.current_size_key:
                        print(f"👁 当前尺寸 {self.current_size_key or '?'} 无模板，"
                              f"请长按 👁 框选采集", flush=True)
                        self._missing_warned = self.current_size_key
                    hits = 0
                    miss_hits = 0
                    time.sleep(interval)
                    continue
                self._missing_warned = ""

                exclude = self._collect_exclude()
                if is_window_covered(self.hwnd, exclude_hwnds=exclude):
                    covered_log_counter += 1
                    if covered_log_counter % 20 == 1:
                        print("👁 窗口被遮挡，跳过检测", flush=True)
                    hits = 0
                    miss_hits = 0
                    time.sleep(interval)
                    continue
                covered_log_counter = 0

                tpl = self.current_template
                roi_tuple = (tpl["x1"], tpl["y1"], tpl["x2"], tpl["y2"])
                expected = tpl.get("ocr_text", "")
                match_mode = tpl.get("match_mode", "regex")

                bgra, rect = capture_roi_bgra(self.hwnd, roi_tuple)
                if bgra is None or bgra.size == 0:
                    hits = 0
                    miss_hits = 0
                    time.sleep(interval)
                    continue

                ocr_text = ocr_recognize(bgra)
                matched = ocr_text_matches(ocr_text, expected, match_mode)
                now = time.time()

                if debug:
                    extra = f" mode={trigger_mode} seen={have_seen} " \
                            f"hits={hits} miss={miss_hits}"
                    show_text = (ocr_text or "").replace("\n", " ")[:40]
                    print(f"👁 ROI={rect} src={self.current_src} "
                          f"match={matched} expected='{expected[:20]}' "
                          f"got='{show_text}'{extra}", flush=True)

                if trigger_mode == "disappear":
                    if matched:
                        have_seen = True
                        miss_hits = 0
                    else:
                        if have_seen:
                            miss_hits += 1
                        else:
                            miss_hits = 0

                    if (have_seen
                            and miss_hits >= consecutive
                            and (now - last_trigger) >= cooldown):
                        last_trigger = now
                        have_seen = False
                        miss_hits = 0
                        print(f"👁 文字消失触发！got='{(ocr_text or '')[:30]}'", flush=True)
                        if self.on_match:
                            self.on_match()
                else:
                    if matched:
                        hits += 1
                    else:
                        hits = 0

                    if hits >= consecutive and (now - last_trigger) >= cooldown:
                        last_trigger = now
                        hits = 0
                        print(f"👁 文字出现触发！got='{(ocr_text or '')[:30]}'", flush=True)
                        if self.on_match:
                            self.on_match()

            except Exception as e:
                print(f"👁 OCR 监控异常: {e}", flush=True)

            time.sleep(interval)


# ============================================================
#                    防火墙工具
# ============================================================
def run_cmd(cmd_str, exit_on_failure=True, ignore_keywords=None):
    try:
        process = subprocess.Popen(cmd_str, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        output_lines = []
        for line in iter(process.stdout.readline, b''):
            decoded = None
            for enc in ('gbk', 'utf-8', 'cp437'):
                try:
                    decoded = line.decode(enc).rstrip()
                    break
                except:
                    continue
            if decoded is None:
                decoded = line.decode('utf-8', errors='ignore').rstrip()
            output_lines.append(decoded)
            print(decoded, flush=True)
        process.stdout.close()
        process.wait()
        full_output = "\n".join(output_lines)
        if process.returncode not in (0, None):
            if ignore_keywords and any(k in full_output for k in ignore_keywords):
                print("⚠️ 命令非0退出码，但包含可忽略内容，继续执行。", flush=True)
                return
            if not exit_on_failure:
                print("⚠️ 命令执行失败，但忽略继续运行。", flush=True)
                return
            print(f"❌ 命令执行失败:\n{cmd_str}\n\n输出信息:\n{full_output}", flush=True)
            if exit_on_failure:
                sys.exit(1)
    except Exception as e:
        if not exit_on_failure:
            print(f"⚠️ 命令异常但忽略: {e}", flush=True)
            return
        print(f"❌ 命令异常: {cmd_str}\n{e}", flush=True)
        sys.exit(1)


def block_network_for_targets(rule_base, exe_paths):
    for idx, exe_path in enumerate(exe_paths):
        if exe_path and os.path.exists(exe_path):
            rule_name = f"{rule_base}_{idx}"
            for d in ['in', 'out']:
                run_cmd(f'netsh advfirewall firewall add rule name="{rule_name}_{d}" dir={d} action=block program="{exe_path}" enable=yes profile=any')


def unblock_network_for_targets(rule_base, count):
    for idx in range(count):
        rule_name = f"{rule_base}_{idx}"
        for d in ['in', 'out']:
            run_cmd(f'netsh advfirewall firewall delete rule name="{rule_name}_{d}"',
                    exit_on_failure=False,
                    ignore_keywords=["没有与指定标准相匹配的规则", "No rules match"])


def get_active_interfaces():
    interfaces = []
    try:
        output = subprocess.check_output('netsh interface show interface', shell=True,
                                         text=True, encoding='gbk')
        for line in output.splitlines():
            if '已启用' in line or 'Enabled' in line:
                if any(kw in line for kw in ['以太网', 'Ethernet', 'WLAN', 'Wi-Fi']):
                    parts = line.split('已启用' if '已启用' in line else 'Enabled')
                    if len(parts) >= 2:
                        name = parts[1].strip()
                        if name:
                            interfaces.append(name)
    except:
        pass
    return interfaces


def disable_all_network():
    for iface in get_active_interfaces():
        silent_cmd(f'netsh interface set interface "{iface}" admin=DISABLE')


def enable_all_network():
    for iface in get_active_interfaces():
        silent_cmd(f'netsh interface set interface "{iface}" admin=ENABLE')
    for name in ['以太网', 'WLAN', 'Wi-Fi', 'Ethernet']:
        silent_cmd(f'netsh interface set interface "{name}" admin=ENABLE')


def silent_cmd(cmd_str):
    try:
        subprocess.run(cmd_str, shell=True, capture_output=True, timeout=10)
    except:
        pass


# ============================================================
#                    音量控制
# ============================================================
def run_svv_hidden(args_list, timeout=15):
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0
    creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
    try:
        result = subprocess.run(
            args_list,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            startupinfo=startupinfo,
            creationflags=creationflags,
            timeout=timeout,
            check=False
        )
        try:
            stdout_text = result.stdout.decode('gbk', errors='ignore')
            stderr_text = result.stderr.decode('gbk', errors='ignore')
        except:
            stdout_text = result.stdout.decode('utf-8', errors='ignore')
            stderr_text = result.stderr.decode('utf-8', errors='ignore')
        return result.returncode, stdout_text, stderr_text
    except Exception as e:
        return -1, "", str(e)


def get_process_volume(sv_path, exe_path):
    exe_name = os.path.basename(exe_path)
    cmd = [sv_path, "/scomma", ""]
    print(f"🔍 执行命令：{' '.join(cmd)}", flush=True)
    rc, out, err = run_svv_hidden(cmd, timeout=15)
    print(f"   返回码：{rc}", flush=True)
    if rc != 0:
        print(f"   ❌ 命令返回非零", flush=True)
        return None

    target_line = None
    for line in out.splitlines():
        if exe_name.lower() in line.lower():
            target_line = line
            break
    if not target_line:
        print(f"   ❌ 未找到进程：{exe_name}", flush=True)
        return None

    print(f"   找到目标行：{target_line!r}", flush=True)
    m = re.search(r'(\d+(?:\.\d+)?)\s*%', target_line)
    if m:
        vol = int(float(m.group(1)))
        print(f"   ✅ 解析成功：音量 = {vol}%", flush=True)
        return vol
    else:
        print("   ❌ 无法解析音量", flush=True)
        return None


def set_process_volume(sv_path, exe_path, volume):
    exe_name = os.path.basename(exe_path)
    cmd = [sv_path, "/SetVolume", exe_name, str(volume)]
    print(f"🔍 执行命令：{' '.join(cmd)}", flush=True)
    rc, out, err = run_svv_hidden(cmd, timeout=15)
    print(f"   返回码：{rc}", flush=True)
    return rc == 0


# ============================================================
#                    日志窗口 Text 写入器
# ============================================================
class LogTextHandler:
    def __init__(self, widget):
        self.widget = widget
        self._mark_name = f"replace_mark_{id(self)}"

    def __call__(self, action, text):
        try:
            w = self.widget
            w.configure(state="normal")
            if action == "REPLACE":
                try:
                    w.delete(self._mark_name, "end")
                except tk.TclError:
                    pass
            start_index = w.index("end-1c")
            w.insert("end", text)
            try:
                w.mark_set(self._mark_name, start_index)
                w.mark_gravity(self._mark_name, "left")
            except tk.TclError:
                pass
            w.see("end")
            w.configure(state="disabled")
        except:
            pass


# ============================================================
#                    OCR 确认对话框
# ============================================================
class OcrConfirmDialog:
    REGEX_PRESETS = [
        ("玩家 ID", DEFAULT_ID_REGEX),
        ("数字", r"\d+"),
        ("血量数字", r"血量\s*\d+"),
        ("百分比", r"\d+(\.\d+)?%"),
    ]

    def __init__(self, parent, detected_text, scale=1.0, size=(560, 560)):
        self.parent = parent
        self.detected_text = detected_text or ""
        self.scale = scale
        self.dialog_size = size
        self.result = None

        self.dlg = tk.Toplevel(parent)
        self.dlg.title("OCR 文字确认")
        self.dlg.attributes('-topmost', True)
        self.dlg.configure(bg='#FAFAFA')
        try:
            self.dlg.grab_set()
        except:
            pass

        S = scale
        w = int(size[0] * S)
        h = int(size[1] * S)
        self.dlg.update_idletasks()
        sw = self.dlg.winfo_screenwidth()
        sh = self.dlg.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.dlg.geometry(f"{w}x{h}+{x}+{y}")

        pad = int(16 * S)
        f_title = ("微软雅黑", -max(14, int(16 * S)), "bold")
        f_text = ("微软雅黑", -max(12, int(13 * S)))
        f_mono = ("Consolas", -max(11, int(12 * S)))

        tk.Label(self.dlg, text="🔤 框选区域 OCR 识别结果", bg='#FAFAFA',
                 font=f_title, fg='#1976D2').pack(pady=(pad, int(4 * S)))

        tk.Label(self.dlg, text=f"OCR 实际识别到：{self.detected_text or '（无）'}",
                 bg='#FAFAFA', fg='#555', font=f_text,
                 wraplength=int(500 * S), justify='left').pack(anchor='w', padx=pad,
                                                                pady=(0, int(8 * S)))

        edit_hint = tk.Label(self.dlg,
                             text="⬇ 下方是可编辑输入框（默认为玩家 ID 正则）⬇",
                             bg='#FFF3E0', fg='#E65100',
                             font=("微软雅黑", -max(11, int(12 * S)), "bold"),
                             padx=int(8 * S), pady=int(4 * S))
        edit_hint.pack(fill=tk.X, padx=pad, pady=(0, int(4 * S)))

        text_frame = tk.Frame(self.dlg, bg='#FAFAFA')
        text_frame.pack(fill=tk.X, padx=pad, pady=(0, int(8 * S)))

        self.text_widget = tk.Text(text_frame, height=3, wrap=tk.WORD, font=f_mono,
                                   bg='#FFFFFF', relief='solid', bd=2,
                                   highlightthickness=2,
                                   highlightbackground='#1976D2',
                                   highlightcolor='#1976D2',
                                   insertbackground='#1976D2')
        self.text_widget.pack(fill=tk.X, expand=False)
        self.text_widget.insert("1.0", DEFAULT_ID_REGEX)
        self.text_widget.focus_set()
        self.text_widget.tag_add("sel", "1.0", "end")

        tk.Label(self.dlg, text="匹配模式：", bg='#FAFAFA',
                 font=("微软雅黑", -max(12, int(13 * S)), "bold"),
                 fg='#333').pack(anchor='w', padx=pad)

        self.mode_var = tk.StringVar(value="regex")
        mode_frame = tk.Frame(self.dlg, bg='#FAFAFA')
        mode_frame.pack(anchor='w', padx=pad, pady=(int(2 * S), int(6 * S)))

        for val, label in [("contains", "包含（宽松）"),
                           ("equals", "完全相等（严格）"),
                           ("regex", "正则表达式（推荐）")]:
            tk.Radiobutton(mode_frame, text=label, variable=self.mode_var,
                           value=val, bg='#FAFAFA', font=f_text,
                           anchor='w',
                           command=self._on_mode_change).pack(anchor='w')

        self.regex_frame = tk.Frame(self.dlg, bg='#FAFAFA')
        self.regex_frame.pack(anchor='w', padx=pad, pady=(0, int(6 * S)))
        tk.Label(self.regex_frame, text="快捷填入：",
                 bg='#FAFAFA', fg='#666',
                 font=("微软雅黑", -max(10, int(11 * S)))).pack(anchor='w')

        preset_row = tk.Frame(self.regex_frame, bg='#FAFAFA')
        preset_row.pack(anchor='w', pady=(int(2 * S), 0))
        for name, pattern in self.REGEX_PRESETS:
            tk.Button(preset_row, text=name, bg='#E3F2FD', fg='#0D47A1',
                      font=("微软雅黑", -max(10, int(11 * S))),
                      relief='flat', padx=int(8 * S), pady=int(3 * S),
                      command=lambda p=pattern: self._fill_pattern(p)
                      ).pack(side=tk.LEFT, padx=(0, int(4 * S)))

        self._on_mode_change()

        tk.Label(self.dlg,
                 text="contains：识别文字里包含期望文字就算命中（不加 ^$）\n"
                      "equals：识别文字与期望文字完全一致\n"
                      "regex：用正则匹配（默认已填玩家 ID 正则）",
                 bg='#FAFAFA', font=("微软雅黑", -max(10, int(11 * S))),
                 fg='#888', justify='left').pack(anchor='w', padx=pad,
                                                  pady=(0, int(8 * S)))

        btn_frame = tk.Frame(self.dlg, bg='#FAFAFA')
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=int(12 * S))

        tk.Button(btn_frame, text="✓ 确认保存", command=self._on_ok,
                  bg='#4CAF50', fg='white', font=f_text,
                  relief='flat', padx=int(20 * S), pady=int(6 * S)
                  ).pack(side=tk.RIGHT, padx=int(16 * S))
        tk.Button(btn_frame, text="✕ 取消", command=self._on_cancel,
                  bg='#F44336', fg='white', font=f_text,
                  relief='flat', padx=int(20 * S), pady=int(6 * S)
                  ).pack(side=tk.RIGHT)

        self.dlg.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.dlg.bind("<Escape>", lambda e: self._on_cancel())

    def _on_mode_change(self):
        is_regex = self.mode_var.get() == "regex"
        for child in self.regex_frame.winfo_children():
            if isinstance(child, tk.Frame):
                for btn in child.winfo_children():
                    try:
                        btn.config(state='normal' if is_regex else 'disabled')
                    except:
                        pass

    def _fill_pattern(self, pattern):
        self.text_widget.delete("1.0", "end")
        self.text_widget.insert("1.0", pattern)
        self.text_widget.focus_set()

    def _on_ok(self):
        text = self.text_widget.get("1.0", "end").strip()
        mode = self.mode_var.get()
        self.result = {"ocr_text": text, "match_mode": mode}
        try:
            self.dlg.grab_release()
        except:
            pass
        self.dlg.destroy()

    def _on_cancel(self):
        self.result = None
        try:
            self.dlg.grab_release()
        except:
            pass
        self.dlg.destroy()

    def show(self):
        self.parent.wait_window(self.dlg)
        return self.result


# ============================================================
#                    主界面
# ============================================================
class NetworkBlockerApp:
    def __init__(self, root):
        self.root = root
        self.cleanup_done = False
        self.is_running = False
        self.log_window = None
        self.md_window = None
        self.md_text = None
        self.time_dialog = None
        self.time_entry = None
        self.stop_monitor = Event()
        self.stop_ping_event = Event()
        self.rule_base = "Block_App"

        self.animate_id = None
        self.wave_offset = 0
        self.time_update_id = None

        self.saved_volume = None
        self.is_muted = False
        self.volume_btn = None

        self.ping_timeout_counter = 0
        self.ping_label_id = None

        self.scale = get_dpi_scale()

        # 加载配置
        self.config, self.templates, self.state = load_config()

        ui = self.config.get("ui", {})
        timing = self.config.get("timing", {})

        self.bg_color = ui.get("bg_color", "#E0E0E0")
        self.drag_color = ui.get("drag_color", "#D0D0D0")
        self.transparent_color = ui.get("transparent_color", "#00FF00")
        self.window_width_config = ui.get("window_width", 200)
        self.window_height_config = ui.get("window_height", 200)
        self.long_press_ms = int(ui.get("long_press_ms", 2000))
        self.multi_click_count = int(ui.get("multi_click_count", 6))
        self.multi_click_window_s = float(ui.get("multi_click_window_s", 2.0))
        self.toggle_click_delay_ms = int(ui.get("toggle_click_delay_ms", 500))

        lw = ui.get("log_window", {})
        self.log_window_w = int(lw.get("width", 460))
        self.log_window_h = int(lw.get("height", 340))

        mw = ui.get("md_window", {})
        self.md_default_w = int(mw.get("width", 400))
        self.md_default_h = int(mw.get("height", 300))
        self.md_font_family = mw.get("font_family", "微软雅黑")
        self.md_font_size = int(mw.get("font_size", 10))
        self.md_font_color = mw.get("font_color", "#000000")
        self.md_bg_color = mw.get("bg_color", "#FFFFFF")

        od = ui.get("ocr_dialog", {})
        self.ocr_dialog_w = int(od.get("width", 560))
        self.ocr_dialog_h = int(od.get("height", 560))

        self.clock_interval_ms = int(timing.get("clock_interval_ms", 200))
        self.animation_interval_ms = int(timing.get("animation_interval_ms", 1000))
        self.ping_interval_s = int(timing.get("ping_interval_s", 3))
        self.game_monitor_interval_s = int(timing.get("game_monitor_interval_s", 3))

        self.block_time = self.config.get("block_time", 5)

        raw_sv = self.config.get("sound_volume_view_path", "")
        self.sv_path = self._resolve_sv_path(raw_sv)
        self.volume_mute_value = self.config.get("volume_mute_value", 0)

        launch_cfg = self.config.get("launch_app", "default")
        self.launch_exe_path = resolve_exe_path(launch_cfg) if launch_cfg else ""

        raw_targets = self.config.get("block_targets", [])
        if not isinstance(raw_targets, list):
            raw_targets = [raw_targets]
        self.block_targets_config = raw_targets
        self.block_targets_exe = []
        for cfg in self.block_targets_config:
            if cfg == "default":
                resolved = os.path.join(SCRIPT_DIR, DEFAULT_GAME_NAME)
            elif cfg == "":
                resolved = ""
            else:
                resolved = cfg
            self.block_targets_exe.append(resolved)

        self.valid_targets = [p for p in self.block_targets_exe if p and os.path.exists(p)]
        self.is_global_mode = (len(self.valid_targets) == 0)

        self.ping_target = self.config.get("ping_target", "qq.com")
        self.auto_exit_on_game_exit = self.config.get("auto_exit_on_game_exit", True)

        self.md_scroll_pos = self.state.get("md_scroll_pos", 0.0)

        self.w = int(self.window_width_config * self.scale)
        self.h = int(self.window_height_config * self.scale)

        self.font_size = -max(13, int(13 * self.scale))
        self.small_font = -max(11, int(11 * self.scale))
        self.time_font_size = -max(12, int(12 * self.scale))

        iw = self.config.get("img_watch", {})
        self.img_watch_enabled = iw.get("enabled", False)
        self.template_watcher = None
        self.roi_overlay = None
        self.btn_imgwatch = None

        self._imgwatch_longpress_job = None
        self._imgwatch_longpress_fired = False
        self._imgwatch_click_times = []
        self._imgwatch_toggle_job = None
        self._imgwatch_warn_job = None

        self._region_selector = None
        self._select_hwnd = None
        self._select_client_rect = None

        self._log_handler = None

        self.root.overrideredirect(True)
        self.root.attributes('-toolwindow', True)
        self.root.attributes('-topmost', True)
        self.root.configure(bg=self.transparent_color)
        self.root.attributes('-transparentcolor', self.transparent_color)
        self.root.geometry(f"{self.w}x{self.h}")
        self.root.title("月圆之夜断网工具 v4.3.0")

        try:
            dpi_now = windll.user32.GetDpiForWindow(self.root.winfo_id())
        except:
            dpi_now = 0
        print(f"🪟 窗口尺寸: {self.w}x{self.h} "
              f"(scale={self.scale:.3f}, dpi={dpi_now})", flush=True)

        wx = self.state.get("window_x")
        wy = self.state.get("window_y")
        if wx is not None and wy is not None:
            self.root.geometry(f"+{wx}+{wy}")
        else:
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            x = (sw - self.w) // 2
            y = (sh - self.h) // 2
            self.root.geometry(f"+{x}+{y}")

        self.restore_network_on_startup()
        self.validate_config_and_prompt()
        self.launch_app_if_needed()

        self.create_widgets()
        self.add_drag_functionality()
        self.start_game_monitor()
        self.start_ping_monitor()
        self.start_heartbeat_animation()
        self.start_clock_update()

        self._refresh_imgwatch_button()
        if self.img_watch_enabled and _IMGWATCH_AVAILABLE and _OCR_AVAILABLE and self.valid_targets:
            self.start_image_watch()

    def _resolve_sv_path(self, raw_path):
        if not raw_path:
            return ""
        if os.path.isfile(raw_path):
            return raw_path
        elif os.path.isdir(raw_path):
            candidate = os.path.join(raw_path, "SoundVolumeView.exe")
            if os.path.isfile(candidate):
                return candidate
        return ""

    def restore_network_on_startup(self):
        print("🔄 启动恢复：清理遗留规则 + 启用所有网卡...", flush=True)
        unblock_network_for_targets(self.rule_base, len(self.block_targets_exe))
        enable_all_network()

    def validate_config_and_prompt(self):
        invalid_targets = []
        for cfg, resolved in zip(self.block_targets_config, self.block_targets_exe):
            if cfg == "":
                continue
            if not os.path.exists(resolved):
                invalid_targets.append(resolved)
        if self.launch_exe_path and not os.path.exists(self.launch_exe_path):
            invalid_targets.append(self.launch_exe_path)

        if invalid_targets and not self.is_global_mode:
            msg = "以下程序未找到，断网/启动功能可能受限：\n\n"
            for p in invalid_targets[:5]:
                msg += f"• {p}\n"
            msg += "\n是否继续运行？"
            if not messagebox.askyesno("配置警告", msg):
                self.root.after(100, self.safe_exit)
                return
        elif self.is_global_mode and not self.block_targets_exe:
            print("🌐 全局断网模式", flush=True)

    def safe_exit(self):
        self.stop_animation()
        self.stop_clock()
        self.stop_image_watch()
        self.restore_volume_if_needed()
        self.cleanup()
        self.root.destroy()

    def launch_app_if_needed(self):
        if not self.launch_exe_path:
            return
        if not os.path.exists(self.launch_exe_path):
            print(f"❌ 连带启动应用不存在：{self.launch_exe_path}", flush=True)
            return
        if is_process_running(self.launch_exe_path):
            print(f"✅ 应用已在运行：{os.path.basename(self.launch_exe_path)}", flush=True)
            return
        print(f"🚀 正在启动应用：{self.launch_exe_path}", flush=True)
        try:
            subprocess.Popen([self.launch_exe_path], cwd=os.path.dirname(self.launch_exe_path))
            time.sleep(2)
        except Exception as e:
            print(f"❌ 启动失败: {e}", flush=True)

    def start_game_monitor(self):
        def monitor():
            while not self.stop_monitor.is_set():
                if not self.is_global_mode:
                    all_exited = True
                    for target in self.valid_targets:
                        if is_process_running(target):
                            all_exited = False
                            break
                    if all_exited:
                        print("🛑 所有目标程序均已退出", flush=True)
                        if self.auto_exit_on_game_exit:
                            self.root.after(0, self.cleanup_and_exit)
                            break
                        else:
                            print("ℹ️ 配置为不自动退出，保持运行", flush=True)
                time.sleep(self.game_monitor_interval_s)
        Thread(target=monitor, daemon=True).start()

    def start_ping_monitor(self):
        if not self.ping_target:
            return

        def ping_loop():
            while not self.stop_ping_event.is_set():
                delay = self.get_ping_delay(self.ping_target)
                if delay is None:
                    self.ping_timeout_counter += 1
                    if self.ping_timeout_counter > 999:
                        self.ping_timeout_counter = 999
                    display_text = f"{self.ping_timeout_counter:03d}"
                else:
                    self.ping_timeout_counter = 0
                    display_text = str(delay)
                self.root.after(0, lambda t=display_text: self.update_ping_label(t))
                time.sleep(self.ping_interval_s)
        Thread(target=ping_loop, daemon=True).start()

    def get_ping_delay(self, target):
        try:
            cmd = f"ping -n 1 {target}"
            proc = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                                  timeout=4, encoding='gbk', errors='ignore')
            output = proc.stdout
            match = re.search(r'(?:时间|time)=(\d+)ms', output)
            if match:
                return int(match.group(1))
            else:
                return None
        except:
            return None

    def update_ping_label(self, text):
        if self.ping_label_id and self.canvas:
            self.canvas.itemconfig(self.ping_label_id, text=text)

    def cleanup_and_exit(self):
        self.state["window_x"] = self.root.winfo_x()
        self.state["window_y"] = self.root.winfo_y()
        if self.md_window is not None and self.md_window.winfo_exists():
            self.save_md_state()
        save_state(self.state)

        self.stop_animation()
        self.stop_clock()
        self.stop_ping_event.set()
        self.stop_image_watch()
        self.restore_volume_if_needed()
        self.cleanup()
        self.root.destroy()

    def restore_volume_if_needed(self):
        if self.is_muted and self.saved_volume is not None and self.sv_path and self.valid_targets:
            target_exe = self.valid_targets[0]
            if os.path.exists(target_exe) and is_process_running(target_exe):
                if set_process_volume(self.sv_path, target_exe, self.saved_volume):
                    print(f"🔊 退出时已恢复目标游戏音量到 {self.saved_volume}%", flush=True)
                self.is_muted = False
                self.saved_volume = None
                if self.volume_btn:
                    self.volume_btn.config(text="🔊", bg='#E0E0E0')

    def _layout_row_buttons(self, buttons, y, bottom=False):
        buttons = [b for b in buttons if b is not None]
        n = len(buttons)
        if n == 0:
            return
        anchor = "s" if bottom else "n"
        if n == 1:
            cx = (self.rect_left + self.rect_right) // 2
            self.canvas.create_window(cx, y, window=buttons[0], anchor=anchor)
            return
        try:
            first_w = buttons[0].winfo_reqwidth()
            last_w = buttons[-1].winfo_reqwidth()
        except:
            first_w = last_w = 40
        first_cx = self.rect_left + first_w // 2
        last_cx = self.rect_right - last_w // 2
        if last_cx <= first_cx:
            last_cx = first_cx + 1
        for i, w in enumerate(buttons):
            cx = first_cx + int((last_cx - first_cx) * i / (n - 1))
            self.canvas.create_window(cx, y, window=w, anchor=anchor)

    def create_widgets(self):
        S = self.scale
        self.canvas = tk.Canvas(self.root, bg=self.transparent_color, highlightthickness=0, bd=0,
                                width=self.w, height=self.h)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        pad = int(12 * S)
        btn_common = {
            'bg': '#E0E0E0',
            'activebackground': '#C0C0C0',
            'fg': '#333',
            'font': ("Arial", self.font_size),
            'width': 3, 'height': 1,
            'bd': 0, 'relief': 'flat'
        }
        self.btn_time = tk.Button(self.canvas, text="⏱", command=self.toggle_time_dialog, **btn_common)
        self.btn_clear = tk.Button(self.canvas, text="🗑", command=self.clear_firewall_rules, **btn_common)
        self.btn_imgwatch = tk.Button(self.canvas, text="👁",
                                      bg='#E0E0E0', activebackground='#C0C0C0', fg='#333',
                                      font=("Arial", self.font_size), width=3, height=1,
                                      bd=0, relief='flat')
        self.btn_imgwatch.bind("<ButtonPress-1>", self._on_imgwatch_press)
        self.btn_imgwatch.bind("<ButtonRelease-1>", self._on_imgwatch_release)

        self.btn_log = tk.Button(self.canvas, text="📋", command=self.toggle_log_window, **btn_common)
        self.btn_exit = tk.Button(self.canvas, text="✕", command=self.cleanup_and_exit,
                                  bg='#FFD0D0', activebackground='#FFAAAA', fg='#333',
                                  font=("Arial", self.small_font), width=3, height=1, bd=0)
        self.btn_md = tk.Button(self.canvas, text="📄", command=self.toggle_md_window, **btn_common)

        self.volume_btn = None
        if self.sv_path and self.valid_targets and os.path.exists(self.sv_path):
            self.volume_btn = tk.Button(self.canvas, text="🔊", command=self.toggle_volume,
                                        bg='#E0E0E0', activebackground='#C0C0C0', fg='#333',
                                        font=("Arial", self.font_size), width=2, height=1,
                                        bd=0, relief='flat', highlightthickness=0)

        self.root.update_idletasks()
        time_btn_width = self.btn_time.winfo_reqwidth()
        drag_height = int(time_btn_width * 2 / 3)
        min_drag_height = int(18 * S)
        if drag_height < min_drag_height:
            drag_height = min_drag_height

        top_pad = int(6 * S)
        self.rect_left = pad
        self.rect_right = self.w - pad
        drag_top = top_pad
        drag_bottom = top_pad + drag_height
        self.rect_top = drag_bottom + int(4 * S)
        btn_height = self.btn_log.winfo_reqheight()
        self.rect_bottom = self.h - pad - btn_height - int(4 * S)

        self.bg_rect = self.canvas.create_rectangle(
            self.rect_left, self.rect_top, self.rect_right, self.rect_bottom,
            fill=self.bg_color, outline="", tags="bg"
        )
        self.canvas.tag_bind("bg", "<Button-1>", self.toggle_process)

        self.drag_rect = self.canvas.create_rectangle(
            self.rect_left, drag_top, self.rect_right, drag_bottom,
            fill=self.drag_color, outline="", tags="drag"
        )

        mid_y = (drag_top + drag_bottom) // 2
        o_hour = int(15 * S); o_sep1 = int(30 * S)
        o_min = int(45 * S); o_sep2 = int(60 * S)
        o_sec = int(75 * S); o_sep3 = int(88 * S)

        self.time_hour = self.canvas.create_text(
            self.rect_left + o_hour, mid_y,
            text="00", font=("Consolas", self.time_font_size, "bold"), fill="#333", tags="time"
        )
        self.time_sep1 = self.canvas.create_text(
            self.rect_left + o_sep1, mid_y,
            text=":", font=("Arial", self.time_font_size, "bold"), fill="#555", tags="time"
        )
        self.time_min = self.canvas.create_text(
            self.rect_left + o_min, mid_y,
            text="00", font=("Consolas", self.time_font_size, "bold"), fill="#333", tags="time"
        )
        self.time_sep2 = self.canvas.create_text(
            self.rect_left + o_sep2, mid_y,
            text=":", font=("Arial", self.time_font_size, "bold"), fill="#555", tags="time"
        )
        self.time_sec = self.canvas.create_text(
            self.rect_left + o_sec, mid_y,
            text="00", font=("Consolas", self.time_font_size, "bold"), fill="#333", tags="time"
        )

        if self.ping_target:
            self.canvas.create_text(
                self.rect_left + o_sep3, mid_y,
                text="-", font=("Arial", self.time_font_size, "bold"), fill="#555", tags="time"
            )
            ping_x = self.rect_right - int(10 * S)
            self.ping_label_id = self.canvas.create_text(
                ping_x, mid_y, text="000",
                font=("Consolas", self.time_font_size, "bold"),
                fill="#333", tags="time", anchor="e"
            )

        row2 = [self.btn_time]
        if self.volume_btn is not None:
            row2.append(self.volume_btn)
        row2.append(self.btn_imgwatch)
        row2.append(self.btn_clear)
        self._layout_row_buttons(row2, self.rect_top, bottom=False)

        row_bottom = [self.btn_log, self.btn_md, self.btn_exit]
        self._layout_row_buttons(row_bottom, self.rect_bottom, bottom=True)

        self.canvas.tag_bind("drag", "<Button-1>", self.start_move)
        self.canvas.tag_bind("drag", "<B1-Motion>", self.on_move)
        self.canvas.tag_bind("time", "<Button-1>", self.start_move)
        self.canvas.tag_bind("time", "<B1-Motion>", self.on_move)
        self.canvas.tag_raise("window")

    def add_drag_functionality(self):
        self.canvas.bind("<Button-1>", self.start_move)
        self.canvas.bind("<B1-Motion>", self.on_move)

    def start_move(self, event):
        self.x = event.x_root - self.root.winfo_x()
        self.y = event.y_root - self.root.winfo_y()

    def on_move(self, event):
        x = event.x_root - self.x
        y = event.y_root - self.y
        self.root.geometry(f"+{x}+{y}")

    def _refresh_imgwatch_button(self):
        if self.btn_imgwatch is None:
            return
        if not _IMGWATCH_AVAILABLE or not _OCR_AVAILABLE:
            self.btn_imgwatch.config(text="👁", bg='#E0E0E0', fg='#999')
            return
        if self.img_watch_enabled:
            self.btn_imgwatch.config(bg='#B3E5FC', text="👁", fg='#0D47A1')
        else:
            self.btn_imgwatch.config(bg='#E0E0E0', text="👁", fg='#333')

    def _on_imgwatch_press(self, event):
        self._imgwatch_longpress_fired = False
        if self._imgwatch_longpress_job:
            try:
                self.root.after_cancel(self._imgwatch_longpress_job)
            except:
                pass
        try:
            self.btn_imgwatch.config(bg='#FFB74D')
        except:
            pass
        self._imgwatch_warn_job = self.root.after(1000, self._imgwatch_warn)
        self._imgwatch_longpress_job = self.root.after(
            self.long_press_ms, self._fire_imgwatch_longpress)

    def _imgwatch_warn(self):
        self._imgwatch_warn_job = None
        if self._imgwatch_longpress_fired:
            return
        try:
            self.btn_imgwatch.config(bg='#FF7043', text="👁")
        except:
            pass

    def _fire_imgwatch_longpress(self):
        self._imgwatch_longpress_job = None
        self._imgwatch_longpress_fired = True
        if self._imgwatch_warn_job:
            try:
                self.root.after_cancel(self._imgwatch_warn_job)
            except:
                pass
            self._imgwatch_warn_job = None
        if self._imgwatch_toggle_job:
            try:
                self.root.after_cancel(self._imgwatch_toggle_job)
            except:
                pass
            self._imgwatch_toggle_job = None
        self._imgwatch_click_times.clear()
        self.enter_region_select_mode()

    def _on_imgwatch_release(self, event):
        if self._imgwatch_longpress_job:
            try:
                self.root.after_cancel(self._imgwatch_longpress_job)
            except:
                pass
            self._imgwatch_longpress_job = None
        if self._imgwatch_warn_job:
            try:
                self.root.after_cancel(self._imgwatch_warn_job)
            except:
                pass
            self._imgwatch_warn_job = None

        if not self._imgwatch_longpress_fired:
            self._on_imgwatch_short_click()
        else:
            self._refresh_imgwatch_button()
        self._imgwatch_longpress_fired = False

    def _on_imgwatch_short_click(self):
        now = time.time()
        self._imgwatch_click_times.append(now)
        self._imgwatch_click_times = [t for t in self._imgwatch_click_times
                                      if now - t <= self.multi_click_window_s]
        if self._imgwatch_toggle_job:
            try:
                self.root.after_cancel(self._imgwatch_toggle_job)
            except:
                pass
            self._imgwatch_toggle_job = None

        if len(self._imgwatch_click_times) >= self.multi_click_count:
            self._imgwatch_click_times.clear()
            self._toggle_debug_overlay()
            return

        self._imgwatch_toggle_job = self.root.after(
            self.toggle_click_delay_ms, self._resolve_imgwatch_click)

    def _resolve_imgwatch_click(self):
        self._imgwatch_toggle_job = None
        self._imgwatch_click_times.clear()
        self.toggle_image_watch()

    def _toggle_debug_overlay(self):
        iw = self.config.get("img_watch", {})
        new_val = not bool(iw.get("debug_overlay", True))
        update_config_field(["img_watch", "debug_overlay"], new_val)
        iw["debug_overlay"] = new_val
        self.config["img_watch"] = iw
        print(f"👁 调试边框已{'开启' if new_val else '关闭'}"
              f"（连击 {self.multi_click_count} 次 👁 可切换）", flush=True)
        if self.img_watch_enabled and self.template_watcher is not None:
            self.stop_image_watch()
            self.start_image_watch()

    def toggle_image_watch(self):
        if not _IMGWATCH_AVAILABLE:
            messagebox.showerror("错误", "未安装 mss/numpy")
            return
        if not _OCR_AVAILABLE:
            messagebox.showerror("错误", "未安装 rapidocr-onnxruntime\n请执行：pip install rapidocr-onnxruntime")
            return
        if self.is_global_mode or not self.valid_targets:
            messagebox.showerror("错误", "无有效断网目标")
            return

        iw = self.config.get("img_watch", {})

        if not self.img_watch_enabled:
            if not self.templates:
                if not messagebox.askyesno("提示", "还没有采集任何模板。\n是否仍要启用？\n\n长按 👁 可框选采集。"):
                    return
            self.img_watch_enabled = True
            self.start_image_watch()
        else:
            self.img_watch_enabled = False
            self.stop_image_watch()

        self._refresh_imgwatch_button()
        update_config_field(["img_watch", "enabled"], self.img_watch_enabled)
        iw["enabled"] = self.img_watch_enabled
        self.config["img_watch"] = iw

    def _collect_own_hwnds(self):
        hwnds = []

        def _add(widget):
            try:
                if widget is None:
                    return
                if hasattr(widget, "winfo_exists") and not widget.winfo_exists():
                    return
                wid = widget.winfo_id()
                top = _user32.GetAncestor(wid, GA_ROOT) or wid
                if top:
                    hwnds.append(top)
            except:
                pass

        _add(self.root)
        if self.roi_overlay is not None:
            try:
                if self.roi_overlay.hwnd:
                    hwnds.append(self.roi_overlay.hwnd)
            except:
                pass
        _add(self.log_window)
        _add(self.time_dialog)
        _add(self.md_window)
        try:
            if self._region_selector is not None:
                _add(self._region_selector.mask_top)
                _add(self._region_selector.ui_top)
        except:
            pass

        return hwnds

    def start_image_watch(self):
        if self.template_watcher is not None:
            return

        target_exe = self.valid_targets[0]
        iw = self.config.get("img_watch", {})

        if bool(iw.get("debug_overlay", True)):
            self.roi_overlay = RoiOverlay(
                self.root,
                exe_name=os.path.basename(target_exe),
                scale=self.scale,
                get_templates_cb=lambda: self.templates,
            )
            self.roi_overlay.show()
        else:
            self.roi_overlay = None

        self.template_watcher = TemplateWatcher(
            exe_path=target_exe,
            config=self.config,
            templates=self.templates,
            overlay=self.roi_overlay,
            on_match=lambda: self.root.after(0, self._on_image_match),
            own_hwnds_cb=self._collect_own_hwnds,
        )
        self.template_watcher.start()
        print("👁 OCR 监控已启动", flush=True)

    def stop_image_watch(self):
        if self.template_watcher is not None:
            self.template_watcher.stop()
            self.template_watcher = None
        if self.roi_overlay is not None:
            self.roi_overlay.hide()
            self.roi_overlay = None
        print("👁 OCR 监控已停止", flush=True)

    def _on_image_match(self):
        iw = self.config.get("img_watch", {})
        mode = iw.get("trigger_mode", "appear")
        if mode == "disappear":
            print("👁 文字消失，触发断网", flush=True)
        else:
            print("👁 文字出现，触发断网", flush=True)
        if not self.is_running:
            self.toggle_process()

    def enter_region_select_mode(self):
        if not _IMGWATCH_AVAILABLE:
            messagebox.showerror("错误", "未安装 mss/numpy。")
            return
        if not _OCR_AVAILABLE:
            messagebox.showerror("错误", "未安装 rapidocr-onnxruntime。\n请执行：pip install rapidocr-onnxruntime")
            return
        if self.is_global_mode or not self.valid_targets:
            messagebox.showerror("错误", "无有效断网目标")
            return

        target_exe = self.valid_targets[0]
        exe_name = os.path.basename(target_exe)
        pid = get_pid_by_exe_name(exe_name)
        if pid is None:
            messagebox.showerror("错误", "目标游戏未运行。")
            return
        hwnd = get_hwnd_by_pid(pid)
        if not hwnd:
            messagebox.showerror("错误", "找不到游戏窗口。")
            return

        if not is_window_visible(hwnd) or is_window_minimized(hwnd) or is_window_cloaked(hwnd):
            messagebox.showwarning("提示", "请先把游戏窗口显示出来，再进入框选模式。")
            return

        l, t, r, b = get_client_rect_screen(hwnd)
        cw, ch = r - l, b - t
        if cw <= 0 or ch <= 0:
            messagebox.showerror("错误", "游戏窗口客户区矩形无效。")
            return

        self._select_hwnd = hwnd
        self._select_client_rect = (l, t, cw, ch)

        if self.roi_overlay is not None:
            self.roi_overlay.hide()
            self.roi_overlay = None

        print(f"🔲 进入框选模式：客户区 ({l},{t}) {cw}x{ch}", flush=True)
        self._region_selector = RegionSelector(
            self.root,
            hint_text="拖拽框选文字区域 · 拖动框调整 · 点确认提交 · ESC 或取消放弃",
            on_done=self._on_region_selected,
            on_cancel=self._on_region_cancelled,
            scale=self.scale,
        )
        self._region_selector.show()

    def _on_region_selected(self, left, top, right, bottom):
        if not self._select_client_rect or self._select_hwnd is None:
            return
        l, t, cw, ch = self._select_client_rect

        x1 = max(0.0, min(1.0, (left - l) / cw))
        y1 = max(0.0, min(1.0, (top - t) / ch))
        x2 = max(0.0, min(1.0, (right - l) / cw))
        y2 = max(0.0, min(1.0, (bottom - t) / ch))
        if x1 > x2:
            x1, x2 = x2, x1
        if y1 > y2:
            y1, y2 = y2, y1

        size_key = f"{cw}x{ch}"

        print(f"📷 正在 OCR 识别：尺寸={size_key} 区域像素 {right-left}x{bottom-top}", flush=True)

        detected = ""
        for i in range(2):
            bgra, _ = capture_roi_bgra(self._select_hwnd, (x1, y1, x2, y2))
            if bgra is None or bgra.size == 0:
                continue
            txt = ocr_recognize(bgra)
            if txt:
                detected = txt
                break
            time.sleep(0.1)

        print(f"🔤 OCR 识别结果：'{detected}'", flush=True)

        dlg = OcrConfirmDialog(self.root, detected_text=detected, scale=self.scale,
                               size=(self.ocr_dialog_w, self.ocr_dialog_h))
        result = dlg.show()

        if result is None:
            print("ℹ️ 用户取消了 OCR 确认", flush=True)
            return

        ocr_text = result["ocr_text"]
        match_mode = result["match_mode"]

        if not ocr_text.strip():
            messagebox.showerror("错误", "期望文字不能为空。")
            return

        template = {
            "x1": round(x1, 4),
            "y1": round(y1, 4),
            "x2": round(x2, 4),
            "y2": round(y2, 4),
            "ocr_text": ocr_text,
            "match_mode": match_mode,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "frame_px": [right - left, bottom - top],
            "client_size": [cw, ch],
        }

        old = self.templates.get(size_key)
        self.templates[size_key] = template
        save_templates(self.templates)

        if old:
            print(f"✅ 覆盖尺寸 {size_key} 的模板", flush=True)
        else:
            print(f"✅ 新增尺寸 {size_key} 的模板", flush=True)
        print(f"   ROI x[{x1:.4f},{x2:.4f}] y[{y1:.4f},{y2:.4f}]", flush=True)
        print(f"   期望文字='{ocr_text}'  匹配模式={match_mode}", flush=True)

        if self.img_watch_enabled:
            self.stop_image_watch()
            self.start_image_watch()
        else:
            if messagebox.askyesno("模板已保存",
                                   f"已保存 {size_key} 的 OCR 模板\n\n"
                                   f"期望文字：{ocr_text}\n"
                                   f"匹配模式：{match_mode}\n\n"
                                   f"是否立即启用监控？"):
                self.img_watch_enabled = True
                update_config_field(["img_watch", "enabled"], True)
                iw = self.config.get("img_watch", {})
                iw["enabled"] = True
                self.config["img_watch"] = iw
                self._refresh_imgwatch_button()
                self.start_image_watch()

    def _on_region_cancelled(self):
        print("ℹ️ 用户取消了框选", flush=True)

    def toggle_volume(self):
        if not self.sv_path or not self.valid_targets or not os.path.exists(self.sv_path):
            messagebox.showerror("错误", "音量控制不可用。")
            return
        target_exe = self.valid_targets[0]
        if not os.path.exists(target_exe):
            messagebox.showerror("错误", "目标游戏不存在，无法静音。")
            return
        if not is_process_running(target_exe):
            messagebox.showerror("错误", "目标游戏未运行，无法静音。")
            return

        if not self.is_muted:
            current_vol = get_process_volume(self.sv_path, target_exe)
            if current_vol is None:
                messagebox.showerror("错误", "无法获取当前音量")
                return
            self.saved_volume = current_vol
            target_volume = int(self.volume_mute_value)
            set_process_volume(self.sv_path, target_exe, target_volume)
            self.is_muted = True
            if self.volume_btn:
                self.volume_btn.config(text="🔇", bg="#FFD0D0")
            print(f"🔇 已将音量调整为 {target_volume}%，原音量 {self.saved_volume}%", flush=True)
        else:
            if self.saved_volume is None:
                return
            set_process_volume(self.sv_path, target_exe, self.saved_volume)
            self.is_muted = False
            self.saved_volume = None
            if self.volume_btn:
                self.volume_btn.config(text="🔊", bg='#E0E0E0')
            print("🔊 音量已恢复", flush=True)

    def toggle_time_dialog(self):
        if self.time_dialog is not None and self.time_dialog.winfo_exists():
            self.save_time_from_dialog()
            self.time_dialog.destroy()
            self.time_dialog = None
            self.time_entry = None
            return

        S = self.scale
        dlg = tk.Toplevel(self.root)
        dlg.overrideredirect(True)
        dlg.attributes('-topmost', True)
        dlg.configure(bg='white')
        dlg_w, dlg_h = int(200 * S), int(60 * S)
        x, y = self.calculate_dialog_position(dlg_w, dlg_h)
        dlg.geometry(f"{dlg_w}x{dlg_h}+{x}+{y}")

        tk.Label(dlg, text="断网秒数 (1-3600):", bg='white',
                 font=("", self.small_font)).pack(pady=int(2 * S))
        entry = tk.Entry(dlg, width=8, font=("", self.small_font))
        entry.pack(pady=int(2 * S))
        entry.insert(0, str(self.block_time))
        entry.focus_set()

        self.time_dialog = dlg
        self.time_entry = entry

        def on_close():
            self.save_time_from_dialog()
            dlg.destroy()
            self.time_dialog = None
            self.time_entry = None

        btn_frame = tk.Frame(dlg, bg='white')
        btn_frame.pack(pady=int(2 * S))
        tk.Button(btn_frame, text="确定", command=on_close, font=("", self.small_font),
                  width=5).pack(side=tk.LEFT, padx=int(3 * S))
        tk.Button(btn_frame, text="取消", command=on_close, font=("", self.small_font),
                  width=5).pack(side=tk.LEFT, padx=int(3 * S))

    def calculate_dialog_position(self, dlg_w, dlg_h):
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        main_x = self.root.winfo_x()
        main_y = self.root.winfo_y()
        main_w = self.w
        margin = int(5 * self.scale)
        left_space = main_x
        right_space = screen_w - (main_x + main_w)
        if left_space >= dlg_w + margin:
            x = main_x - dlg_w - margin
        elif right_space >= dlg_w + margin:
            x = main_x + main_w + margin
        else:
            x = max(0, min(screen_w - dlg_w, main_x + main_w // 2 - dlg_w // 2))
        y = main_y
        if y + dlg_h > screen_h:
            y = screen_h - dlg_h - margin
        if y < 0:
            y = margin
        return x, y

    def save_time_from_dialog(self):
        if self.time_entry is not None:
            s = self.time_entry.get()
            if s.isdigit():
                t = int(s)
                if 1 <= t <= 3600:
                    self.block_time = t
                    update_config_field(["block_time"], t)
                    print(f"✅ 断网时间已设为 {t} 秒（已写回 config.toml）", flush=True)
                else:
                    print("❌ 请输入1~3600之间的数字，保留原值", flush=True)
            else:
                print("❌ 输入无效，保留原值", flush=True)

    def toggle_log_window(self):
        if self.log_window is not None and self.log_window.winfo_exists():
            if self.log_window.state() == 'withdrawn':
                self.log_window.deiconify()
                self.log_window.lift()
                self._attach_log_view()
            else:
                self.log_window.withdraw()
                self._detach_log_view()
            return

        self.log_window = tk.Toplevel(self.root)
        self.log_window.title("月圆之夜断网工具 - 日志")
        self.log_window.geometry(
            f"{int(self.log_window_w * self.scale)}x{int(self.log_window_h * self.scale)}")
        self.log_window.protocol("WM_DELETE_WINDOW", self.hide_log_window)
        frame = tk.Frame(self.log_window)
        frame.pack(fill=tk.BOTH, expand=True)
        scroll = tk.Scrollbar(frame)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text = tk.Text(frame, wrap=tk.WORD, font=("Consolas", self.small_font),
                                yscrollcommand=scroll.set)
        self.log_text.pack(fill=tk.BOTH, expand=True)
        scroll.config(command=self.log_text.yview)
        clear_btn = tk.Button(self.log_window, text="清空显示（不清除缓冲）",
                              command=self.clear_log_display, font=("", self.small_font))
        clear_btn.pack(pady=int(2 * self.scale))
        self._attach_log_view()

    def _attach_log_view(self):
        if not hasattr(self, "log_text") or self.log_text is None:
            return
        try:
            self.log_text.configure(state="normal")
            self.log_text.delete("1.0", "end")
            snapshot = LOG_BUFFER.snapshot()
            self.log_text.insert("end", snapshot)
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        except:
            pass
        self._detach_log_view()
        self._log_handler = LogTextHandler(self.log_text)
        LOG_BUFFER.add_listener(self._log_handler)

    def _detach_log_view(self):
        if self._log_handler is not None:
            LOG_BUFFER.remove_listener(self._log_handler)
            self._log_handler = None

    def hide_log_window(self):
        self._detach_log_view()
        if self.log_window:
            self.log_window.withdraw()

    def clear_log_display(self):
        if hasattr(self, "log_text") and self.log_text:
            try:
                self.log_text.configure(state="normal")
                self.log_text.delete("1.0", "end")
                self.log_text.configure(state="disabled")
            except:
                pass

    def toggle_md_window(self):
        md_file_external = os.path.join(SCRIPT_DIR, "文本.md")
        md_file_builtin = resource_path("内置文本.md")
        if os.path.exists(md_file_external):
            md_file = md_file_external
        elif os.path.exists(md_file_builtin):
            md_file = md_file_builtin
        else:
            return

        if self.md_window is not None and self.md_window.winfo_exists():
            if self.md_window.state() == 'withdrawn':
                self.md_window.deiconify()
                self.md_window.lift()
            else:
                self.save_md_state()
                self.md_window.withdraw()
            return

        self.md_window = tk.Toplevel(self.root)
        self.md_window.title("文本.md")
        width = self.state.get("md_window_width") or self.md_default_w
        height = self.state.get("md_window_height") or self.md_default_h
        x = self.state.get("md_window_x")
        y = self.state.get("md_window_y")
        if x is not None and y is not None:
            self.md_window.geometry(f"{int(width * self.scale)}x{int(height * self.scale)}+{x}+{y}")
        else:
            self.md_window.geometry(f"{int(width * self.scale)}x{int(height * self.scale)}")
        self.md_window.protocol("WM_DELETE_WINDOW", self.hide_md_window)

        frame = tk.Frame(self.md_window)
        frame.pack(fill=tk.BOTH, expand=True)
        scroll = tk.Scrollbar(frame)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        md_font = (self.md_font_family, -max(10, int(self.md_font_size * self.scale)))
        self.md_text = tk.Text(frame, wrap=tk.WORD, font=md_font,
                               fg=self.md_font_color, bg=self.md_bg_color,
                               yscrollcommand=scroll.set)
        self.md_text.pack(fill=tk.BOTH, expand=True)
        scroll.config(command=self.md_text.yview)

        try:
            with open(md_file, "r", encoding="utf-8") as f:
                content = f.read()
            self.md_text.insert("1.0", content)
            self.md_text.config(state=tk.DISABLED)
            self.md_text.yview_moveto(self.md_scroll_pos)
        except Exception as e:
            messagebox.showerror("错误", f"无法读取 {md_file}:\n{e}")

    def save_md_state(self):
        if self.md_window is not None and self.md_window.winfo_exists():
            self.state["md_scroll_pos"] = self.md_text.yview()[0] if self.md_text else 0.0
            self.state["md_window_x"] = self.md_window.winfo_x()
            self.state["md_window_y"] = self.md_window.winfo_y()
            self.state["md_window_width"] = self.md_window.winfo_width()
            self.state["md_window_height"] = self.md_window.winfo_height()
            save_state(self.state)

    def hide_md_window(self):
        self.save_md_state()
        if self.md_window:
            self.md_window.withdraw()

    def toggle_process(self, event=None):
        if not self.is_running:
            self.is_running = True
            self.canvas.itemconfig(self.bg_rect, fill="#F44336")
            self.thread = Thread(target=self.run_block_once, args=(self.block_time,), daemon=True)
            self.thread.start()
        else:
            self.is_running = False
            self.canvas.itemconfig(self.bg_rect, fill=self.bg_color)

    def clear_firewall_rules(self):
        try:
            print("🧹 手动清除防火墙规则并恢复网络...", flush=True)
            unblock_network_for_targets(self.rule_base, len(self.block_targets_exe))
            enable_all_network()
            self.is_running = False
            self.canvas.itemconfig(self.bg_rect, fill=self.bg_color)
            print("✅ 网络已恢复", flush=True)
        except Exception as e:
            print(f"清除规则出错: {e}", flush=True)

    def cleanup(self):
        if self.cleanup_done:
            return
        print("正在清理资源...", flush=True)
        self.is_running = False
        self.stop_monitor.set()
        self.stop_ping_event.set()
        self.stop_image_watch()
        try:
            unblock_network_for_targets(self.rule_base, len(self.block_targets_exe))
            enable_all_network()
            print("✅ 已恢复网络", flush=True)
        except Exception as e:
            print(f"清理防火墙规则时出错: {e}", flush=True)
        self.cleanup_done = True

    def run_block_once(self, block_time):
        try:
            if self.is_global_mode:
                print(f"🌐 全局断网：禁用所有网卡，持续 {block_time} 秒", flush=True)
                disable_all_network()
                print(f"✅ 全局断网已生效", flush=True)
            else:
                print(f"🛑 添加防火墙规则：阻断 {block_time} 秒 (目标数量: {len(self.valid_targets)})", flush=True)
                block_network_for_targets(self.rule_base, self.valid_targets)
                print(f"✅ 应用断网已开始，持续 {block_time} 秒", flush=True)

            start = time.time()
            while time.time() - start < block_time:
                if not self.is_running:
                    print("⏹ 用户中断，提前恢复网络", flush=True)
                    break
                time.sleep(0.1)

            if self.is_global_mode:
                print("🔄 正在启用所有网卡，恢复网络", flush=True)
                enable_all_network()
            else:
                print("🔄 正在删除防火墙规则，恢复网络", flush=True)
                unblock_network_for_targets(self.rule_base, len(self.valid_targets))
            print("✅ 网络已恢复", flush=True)

        except Exception as e:
            print(f"❌ 发生错误: {e}", flush=True)
        finally:
            if self.is_running:
                self.is_running = False
                self.root.after(0, lambda: self.canvas.itemconfig(self.bg_rect, fill=self.bg_color))

    def start_clock_update(self):
        self.update_clock()

    def stop_clock(self):
        if self.time_update_id:
            self.root.after_cancel(self.time_update_id)
            self.time_update_id = None

    def update_clock(self):
        now = datetime.now()
        self.canvas.itemconfig(self.time_hour, text=now.strftime("%H"))
        self.canvas.itemconfig(self.time_min, text=now.strftime("%M"))
        self.canvas.itemconfig(self.time_sec, text=now.strftime("%S"))
        self.time_update_id = self.root.after(self.clock_interval_ms, self.update_clock)

    def start_heartbeat_animation(self):
        self.update_wave()

    def stop_animation(self):
        if self.animate_id:
            self.root.after_cancel(self.animate_id)
            self.animate_id = None

    def update_wave(self):
        S = self.scale
        canvas = self.canvas
        left = self.rect_left + int(10 * S)
        right = self.rect_right - int(10 * S)
        top = self.rect_top + int(20 * S)
        bottom = self.rect_bottom - int(20 * S)
        w = right - left
        h = bottom - top
        if w < 20 or h < 20:
            self.animate_id = self.root.after(self.animation_interval_ms, self.update_wave)
            return
        mid_y = top + h // 2
        step = max(4, int(8 * S))
        amplitude = int(15 * S) if not self.is_running else 0
        self.wave_offset = (self.wave_offset + 1) % step
        dot_r = max(1, int(2 * S))

        canvas.delete("wave")
        for x in range(-step, w + step, step):
            draw_x = left + x + self.wave_offset
            if left <= draw_x <= right:
                rel = ((draw_x - left) / w) * 4 * math.pi
                y = mid_y
                if not self.is_running:
                    if 0.4 * w < (draw_x - left) < 0.6 * w or (draw_x - left) > 0.9 * w:
                        phase = (draw_x - left - 0.5 * w) / (0.1 * w)
                        y = mid_y - int(amplitude * math.exp(-phase**2) * math.cos(phase * 3))
                    else:
                        y = mid_y + int(amplitude * 0.2 * math.sin(rel))
                canvas.create_oval(draw_x - dot_r, y - dot_r, draw_x + dot_r, y + dot_r,
                                   fill="#FFFFFF", outline="", tags="wave")
        self.canvas.tag_raise("wave")
        self.animate_id = self.root.after(self.animation_interval_ms, self.update_wave)


# ============================================================
#                    main
# ============================================================
def main():
    if os.name != 'nt':
        messagebox.showerror("错误", "此脚本仅支持 Windows 系统")
        sys.exit(1)

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except:
            pass

    mutex, already = check_single_instance()
    if already:
        try:
            hwnd = windll.user32.FindWindowW(None, "月圆之夜断网工具 v4.3.0")
            if hwnd:
                windll.user32.ShowWindow(hwnd, 9)
                windll.user32.SetForegroundWindow(hwnd)
        except:
            pass
        sys.exit(0)

    if not is_admin():
        run_as_admin()
        sys.exit()

    root = tk.Tk()
    try:
        dpi = windll.user32.GetDpiForWindow(root.winfo_id()) or 96
        root.tk.call('tk', 'scaling', dpi / 72.0)
    except:
        pass

    app = NetworkBlockerApp(root)
    try:
        root.mainloop()
    except SystemExit:
        pass
    except Exception as e:
        print(f"程序发生错误: {e}", flush=True)
        app.cleanup()
    finally:
        if 'app' in locals() and not getattr(app, 'cleanup_done', True):
            app.cleanup()
        try:
            root.destroy()
        except tk.TclError:
            pass
        if mutex:
            windll.kernel32.CloseHandle(mutex)


if __name__ == "__main__":
    main()