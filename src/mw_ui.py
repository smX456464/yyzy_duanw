"""Mixin: 界面构建 + 时钟 + 动画"""
import ctypes
import os
import re
import subprocess
import sys
import time
import math
import tkinter as tk
from tkinter import messagebox
from threading import Thread, Event
from datetime import datetime
from collections import deque

from .log_buffer import LOG_BUFFER, LogTextHandler
from .win_utils import (is_process_running, is_window_alive, is_window_visible,
                        is_window_minimized, is_window_cloaked, has_valid_rect,
                        get_client_rect_screen, is_game_window_on_screen,
                        get_pid_by_exe_name, get_hwnd_by_pid, _user32, GA_ROOT)
from .config_manager import (load_config, save_templates, save_state,
                              update_config_field, deep_copy,
                              migrate_old_template, guide_rules,
                              PRESET_GUIDE_WHITELIST, PRESET_GUIDE_BLACKLIST,
                              rule_has_roi, rule_roi,
                              resolve_exe_path,
                              SCRIPT_DIR, DEFAULT_GAME_NAME)
from .network_tools import (block_network_for_targets,
                             unblock_network_for_targets,
                             disable_all_network, enable_all_network)
from .volume_tools import resolve_sv_path, get_process_volume, set_process_volume
from .capture import is_capture_available
from .ocr_engine import is_ocr_available
from .region_selector import RegionSelector
from .roi_overlay import RoiOverlay
from .template_watcher import TemplateWatcher
from .rule_manager import RuleManagerDialog


class MainWindowUI:
    def _get_dpi_scale(self):
        try:
            hdc = _user32.GetDC(0)
            dpi_x = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)
            _user32.ReleaseDC(0, hdc)
            return max(1.0, dpi_x / 96.0)
        except Exception:
            return 1.0

    def _setup_hotkeys(self):
        if not getattr(self, "hotkeys_enabled", False):
            return
        try:
            self.root.bind_all("<Control-r>", lambda e: self.reload_config())
            self.root.bind_all("<Control-l>", lambda e: self.toggle_log_window())
            self.root.bind_all("<Control-q>", lambda e: self.cleanup_and_exit())
            print("⌨ 快捷键已启用：Ctrl+R 重载 / Ctrl+L 日志 / Ctrl+Q 退出",
                  flush=True)
        except Exception as e:
            print(f"⌨ 快捷键绑定失败: {e}", flush=True)

    def _apply_config_to_attributes(self):
        ui = self.config.get("ui", {})
        timing = self.config.get("timing", {})
        self.bg_color = ui.get("bg_color", "#E0E0E0")
        self.drag_color = ui.get("drag_color", "#D0D0D0")
        self.transparent_color = ui.get("transparent_color", "#00FF00")
        self.window_width_config = ui.get("window_width", 200)
        self.window_height_config = ui.get("window_height", 200)
        self.long_press_ms = int(ui.get("long_press_ms", 2000))
        self.toggle_click_delay_ms = int(ui.get("toggle_click_delay_ms", 500))
        self.exit_reload_long_press_ms = int(ui.get("exit_reload_long_press_ms", 3000))
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
        self.ocr_dialog_h = int(od.get("height", 600))
        rd = ui.get("rule_dialog", {})
        self.rule_dialog_w = int(rd.get("width", 720))
        self.rule_dialog_h = int(rd.get("height", 640))
        hk = ui.get("hotkeys", {})
        self.hotkeys_enabled = bool(hk.get("enabled", False))
        self.clock_interval_ms = int(timing.get("clock_interval_ms", 200))
        self.animation_interval_ms = int(timing.get("animation_interval_ms", 80))
        self.ping_interval_s = int(timing.get("ping_interval_s", 3))
        self.game_monitor_interval_s = int(timing.get("game_monitor_interval_s", 3))
        self.block_time = self.config.get("block_time", 5)
        self.ocr_block_time = int(self.config.get("ocr_block_time", 1))
        self.volume_enabled = bool(self.config.get("volume_enabled", True))
        raw_sv = self.config.get("sound_volume_view_path", "")
        self.sv_path = resolve_sv_path(raw_sv)
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
        self.auto_mute_when_hidden = bool(iw.get("auto_mute_when_hidden", True))
        self.visibility_check_interval_s = float(
            iw.get("visibility_check_interval_s", 2.0))

    def _layout_row_buttons(self, buttons, y, bottom=False):
        buttons = [b for b in buttons if b is not None]
        n = len(buttons)
        if n == 0: return
        anchor = "s" if bottom else "n"
        if n == 1:
            cx = (self.rect_left + self.rect_right) // 2
            self.canvas.create_window(cx, y, window=buttons[0], anchor=anchor)
            return
        try:
            first_w = buttons[0].winfo_reqwidth()
            last_w = buttons[-1].winfo_reqwidth()
        except Exception:
            first_w = last_w = 40
        first_cx = self.rect_left + first_w // 2
        last_cx = self.rect_right - last_w // 2
        if last_cx <= first_cx: last_cx = first_cx + 1
        for i, w in enumerate(buttons):
            cx = first_cx + int((last_cx - first_cx) * i / (n - 1))
            self.canvas.create_window(cx, y, window=w, anchor=anchor)

    def create_widgets(self):
        S = self.scale
        self.canvas = tk.Canvas(self.root, bg=self.transparent_color,
                                highlightthickness=0, bd=0,
                                width=self.w, height=self.h)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        pad = int(12 * S)
        btn_common = {
            'bg': '#E0E0E0', 'activebackground': '#C0C0C0', 'fg': '#333',
            'font': ("Arial", self.font_size), 'width': 3, 'height': 1,
            'bd': 0, 'relief': 'flat'
        }
        self.btn_time = tk.Button(self.canvas, text="⏱",
                                  command=self.toggle_time_dialog, **btn_common)
        self.btn_clear = tk.Button(self.canvas, text="🗑",
                                   command=self.clear_firewall_rules, **btn_common)
        # OCR 按钮使用 Windows 内置图标字体 Segoe MDL2 Assets
        # U+E7B3 = "View" 眼睛图标
        # 字体用负数 = 像素单位，避免 DPI 二次放大；和 btn_time 字号一致
        _eye_icon = chr(0xE7B3)
        _icon_font = ("Segoe MDL2 Assets", self.font_size)
        self.btn_imgwatch = tk.Button(
            self.canvas, text=_eye_icon,
            bg='#E0E0E0', activebackground='#E0E0E0',
            fg='#555555', disabledforeground='#BBBBBB',
            font=_icon_font, width=5, height=1,
            bd=0, relief='flat',
            highlightthickness=0,
            takefocus=0,
        )
        self.btn_imgwatch.bind("<ButtonPress-1>", self._on_imgwatch_press)
        self.btn_imgwatch.bind("<ButtonRelease-1>", self._on_imgwatch_release)
        self.btn_log = tk.Button(self.canvas, text="📋",
                                 command=self.toggle_log_window, **btn_common)
        self.btn_exit = tk.Button(self.canvas, text="✕",
                                  bg='#FFD0D0', activebackground='#FFAAAA', fg='#333',
                                  font=("Arial", self.small_font), width=3, height=1, bd=0)
        self.btn_exit.bind("<ButtonPress-1>", self._on_exit_press)
        self.btn_exit.bind("<ButtonRelease-1>", self._on_exit_release)
        self.btn_md = tk.Button(self.canvas, text="📄", **btn_common)
        self.btn_md.bind("<ButtonPress-1>", self._on_md_press)
        self.btn_md.bind("<ButtonRelease-1>", self._on_md_release)

        # 🔊 音量按钮：只有 volume_enabled = true 时才创建
        if getattr(self, "volume_enabled", True):
            self.volume_btn = tk.Button(
                self.canvas, text="🔊",
                bg='#E0E0E0', activebackground='#C0C0C0', fg='#333',
                disabledforeground='#BBBBBB',
                font=("Arial", self.font_size), width=2, height=1,
                bd=0, relief='flat', highlightthickness=0, takefocus=0,
            )
            self.volume_btn.bind("<ButtonPress-1>", self._on_volume_press)
            self.volume_btn.bind("<ButtonRelease-1>", self._on_volume_release)
        else:
            self.volume_btn = None

        self.root.update_idletasks()
        time_btn_width = self.btn_time.winfo_reqwidth()
        drag_height = int(time_btn_width * 2 / 3)
        min_drag_height = int(18 * S)
        if drag_height < min_drag_height: drag_height = min_drag_height
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
            fill=self.bg_color, outline="", tags="bg")
        self.canvas.tag_bind("bg", "<Button-1>", self.toggle_process)
        self.drag_rect = self.canvas.create_rectangle(
            self.rect_left, drag_top, self.rect_right, drag_bottom,
            fill=self.drag_color, outline="", tags="drag")

        mid_y = (drag_top + drag_bottom) // 2
        o_hour = int(15 * S); o_sep1 = int(30 * S)
        o_min = int(45 * S); o_sep2 = int(60 * S)
        o_sec = int(75 * S); o_sep3 = int(88 * S)
        self.time_hour = self.canvas.create_text(
            self.rect_left + o_hour, mid_y, text="00",
            font=("Consolas", self.time_font_size, "bold"), fill="#333", tags="time")
        self.time_sep1 = self.canvas.create_text(
            self.rect_left + o_sep1, mid_y, text=":",
            font=("Arial", self.time_font_size, "bold"), fill="#555", tags="time")
        self.time_min = self.canvas.create_text(
            self.rect_left + o_min, mid_y, text="00",
            font=("Consolas", self.time_font_size, "bold"), fill="#333", tags="time")
        # 只显示 HH:MM，去掉秒
        if self.ping_target:
            self.canvas.create_text(self.rect_left + o_sep3, mid_y, text="-",
                                    font=("Arial", self.time_font_size, "bold"),
                                    fill="#555", tags="time")
            ping_x = self.rect_right - int(10 * S)
            self.ping_label_id = self.canvas.create_text(
                ping_x, mid_y, text="000",
                font=("Consolas", self.time_font_size, "bold"),
                fill="#333", tags="time", anchor="e")

        row2 = [self.btn_time]
        if self.volume_btn is not None:
            row2.append(self.volume_btn)
        row2.append(self.btn_imgwatch)
        row2.append(self.btn_clear)
        self._layout_row_buttons(row2, self.rect_top, bottom=False)
        row_bottom = [self.btn_log, self.btn_md, self.btn_exit]
        self._layout_row_buttons(row_bottom, self.rect_bottom, bottom=True)
        self.canvas.tag_raise("window")
        self._refresh_volume_button()

    def _refresh_volume_button(self):
        if self.volume_btn is None: return
        ok = bool(self.sv_path) and os.path.exists(self.sv_path)
        try:
            if not ok:
                self.volume_btn.config(fg='#BBBBBB', text="🔇")
                return
            if self.is_muted:
                self.volume_btn.config(fg='#333', text="🔇", bg='#FFD0D0')
            else:
                self.volume_btn.config(fg='#333', text="🔊", bg='#E0E0E0')
        except Exception:
            pass

    def _start_icon_auto_refresh(self):
        """启动定时刷新图标（2 秒一次）。
        保证不论状态怎么变，图标总能跟上。
        """
        if getattr(self, "_icon_tick_id", None):
            return
        def tick():
            try:
                self._refresh_imgwatch_button()
                if getattr(self, "volume_btn", None) is not None:
                    self._refresh_volume_button()
            except Exception:
                pass
            try:
                self._icon_tick_id = self.root.after(2000, tick)
            except Exception:
                self._icon_tick_id = None
        self._icon_tick_id = self.root.after(2000, tick)
        print("🔄 图标自动刷新已启动（2 秒/次）", flush=True)

    def _current_has_exact_rules(self):
        """检查当前游戏分辨率是否有专属规则
        （用户保存的 或 内置模板的精确匹配）。
        兑底不算。
        """
        tw = getattr(self, "template_watcher", None)
        if tw is not None:
            src = getattr(tw, "current_src", "") or ""
            if src.startswith("user:") or src.startswith("builtin:"):
                return True
            if src.startswith("fallback"):
                return False
        try:
            import os as _os
            from .win_utils import (get_pid_by_exe_name, get_hwnd_by_pid,
                                    get_client_rect_screen)
            if not self.valid_targets:
                return False
            exe = self.valid_targets[0]
            pid = get_pid_by_exe_name(_os.path.basename(exe))
            if pid is None:
                return False
            hwnd = get_hwnd_by_pid(pid)
            if not hwnd:
                return False
            l, t, r, b = get_client_rect_screen(hwnd)
            cw, ch = r - l, b - t
            if cw <= 0 or ch <= 0:
                return False
            key = f"{cw}x{ch}"
            if key in self.templates:
                return True
            try:
                from .config_manager import get_builtin_templates
                if key in get_builtin_templates():
                    return True
            except Exception:
                pass
            return False
        except Exception:
            return False

    def _refresh_imgwatch_button(self):
        if self.btn_imgwatch is None: return
        icon = chr(0xE7B3)
        if not is_capture_available() or not is_ocr_available():
            try:
                self.btn_imgwatch.config(text=f" {icon} ", fg='#BBBBBB')
            except Exception:
                pass
            return
        has_exact = self._current_has_exact_rules()
        try:
            self.btn_imgwatch.config(bg='#E0E0E0', activebackground='#E0E0E0')
            if not has_exact:
                # 无专属规则（仅兑底）→ 图标变淡
                self.btn_imgwatch.config(text=f" {icon} ", fg='#CCCCCC')
            elif self.img_watch_enabled:
                self.btn_imgwatch.config(text=f" ${icon}$ ", fg='#1976D2')
            else:
                self.btn_imgwatch.config(text=f" {icon} ", fg='#555555')
        except Exception:
            pass

    def start_clock_update(self):
        self.update_clock()

    def stop_clock(self):
        if self.time_update_id:
            self.root.after_cancel(self.time_update_id)
            self.time_update_id = None

    def update_clock(self):
        now = datetime.now()
        try:
            self.canvas.itemconfig(self.time_hour, text=now.strftime("%H"))
            self.canvas.itemconfig(self.time_min, text=now.strftime("%M"))
        except Exception:
            pass
        # 计算到下一分钟的毫秒数，精准休眠
        ms_to_next_min = (60 - now.second) * 1000 - now.microsecond // 1000
        self.time_update_id = self.root.after(max(ms_to_next_min, 500), self.update_clock)

    def start_heartbeat_animation(self):
        self.update_wave()

    def stop_animation(self):
        if self.animate_id:
            self.root.after_cancel(self.animate_id)
            self.animate_id = None

    def update_wave(self):
        S = self.scale
        left = self.rect_left + int(10 * S)
        right = self.rect_right - int(10 * S)
        top = self.rect_top + int(20 * S)
        bottom = self.rect_bottom - int(20 * S)
        if right - left < 30 or bottom - top < 30:
            self.animate_id = self.root.after(500, self.update_wave)
            return

        cx = (left + right) // 2
        cy = (top + bottom) // 2

        try:
            self.canvas.delete("wave")
            if self.is_running:
                self._draw_pause_icon(cx, cy, S)
            else:
                self._draw_play_icon(cx, cy, S)
            self.canvas.tag_bind("wave", "<Button-1>", self._on_wave_click)
            self.canvas.tag_raise("wave")
        except Exception:
            pass

        # 状态不常变，500ms 检查一次就够
        self.animate_id = self.root.after(500, self.update_wave)

    def _draw_play_icon(self, cx, cy, S):
        """▶ 播放图标（绿色三角）"""
        size = 22 * S
        self.canvas.create_polygon(
            cx - size * 0.35, cy - size * 0.60,
            cx - size * 0.35, cy + size * 0.60,
            cx + size * 0.55, cy,
            fill="#4CAF50", outline="", tags="wave",
        )

    def _on_wave_click(self, event):
        # 不阻止事件冒泡，让 canvas 的 <Button-1> 触发 start_move
        self.toggle_process(event)

    def _draw_pause_icon(self, cx, cy, S):
        """⏸ 暂停图标（红色双竖条）"""
        size = 22 * S
        bar_w = size * 0.28
        bar_h = size * 1.20
        gap = size * 0.16
        self.canvas.create_rectangle(
            cx - gap / 2 - bar_w, cy - bar_h / 2,
            cx - gap / 2, cy + bar_h / 2,
            fill="#FF8A80", outline="", tags="wave",
        )
        self.canvas.create_rectangle(
            cx + gap / 2, cy - bar_h / 2,
            cx + gap / 2 + bar_w, cy + bar_h / 2,
            fill="#FF8A80", outline="", tags="wave",
        )
