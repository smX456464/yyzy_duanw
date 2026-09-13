"""Mixin: 拖动 + 长按交互 + 长按视觉"""
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


class MainWindowDrag:
    def add_drag_functionality(self):
        self.canvas.bind("<Button-1>", self.start_move)
        self.canvas.bind("<B1-Motion>", self.on_move)
        self.canvas.bind("<ButtonRelease-1>", self.on_release_move)

    def start_move(self, event):
        self._drag_offset_x = event.x_root - self.root.winfo_x()
        self._drag_offset_y = event.y_root - self.root.winfo_y()
        self.stop_animation(); self.stop_clock()

    def on_move(self, event):
        if getattr(self, "_drag_offset_x", None) is None:
            try:
                self.start_move(event)
            except Exception:
                return
        new_x = event.x_root - self._drag_offset_x
        new_y = event.y_root - self._drag_offset_y
        try:
            self.root.geometry(f"+{new_x}+{new_y}")
        except Exception:
            pass

    def on_release_move(self, event):
        self.start_heartbeat_animation()
        self.start_clock_update()

    def _on_imgwatch_press(self, event):
        self._imgwatch_longpress_fired = False
        if self._imgwatch_longpress_job:
            try: self.root.after_cancel(self._imgwatch_longpress_job)
            except Exception: pass
        # 长按期间：图标变强对比色（红）
        try:
            self.btn_imgwatch.config(fg='#F44336')
        except Exception:
            pass
        # 启动长按视觉
        self._start_hold_visual(self.long_press_ms)
        self._imgwatch_warn_job = self.root.after(1000, self._imgwatch_warn)
        self._imgwatch_longpress_job = self.root.after(
            self.long_press_ms, self._fire_imgwatch_longpress)

    def _start_hold_visual(self, total_ms):
        """开始长按视觉：记录原色，启动定时器"""
        try:
            self._hold_saved_bg = self.canvas.itemcget(self.bg_rect, "fill")
        except Exception:
            self._hold_saved_bg = self.bg_color
        self._hold_total_ms = max(1, int(total_ms))
        self._hold_start = time.time()
        if self._hold_anim_job:
            try: self.root.after_cancel(self._hold_anim_job)
            except Exception: pass
            self._hold_anim_job = None
        self._update_hold_visual()

    def _update_hold_visual(self):
        """按时序把中间区域背景色从浅黄→橙→红→绿"""
        if self._hold_start <= 0:
            self._hold_anim_job = None
            return
        elapsed_ms = (time.time() - self._hold_start) * 1000.0
        total = max(1, self._hold_total_ms)
        pct = min(1.0, elapsed_ms / total)

        if pct < 0.25:
            color = "#FFF59D"   # 浅黄
        elif pct < 0.50:
            color = "#FFB74D"   # 橙黄
        elif pct < 0.75:
            color = "#FF7043"   # 深橙
        elif pct < 1.00:
            color = "#F44336"   # 红
        else:
            color = "#66BB6A"   # 绿（可以松手了）

        try:
            self.canvas.itemconfig(self.bg_rect, fill=color)
        except Exception:
            pass

        self._hold_anim_job = self.root.after(30, self._update_hold_visual)

    def _stop_hold_visual(self):
        """结束长按：恢复原色"""
        self._hold_start = 0
        if self._hold_anim_job:
            try: self.root.after_cancel(self._hold_anim_job)
            except Exception: pass
            self._hold_anim_job = None
        try:
            if self.is_running:
                self.canvas.itemconfig(self.bg_rect, fill="#F44336")
            else:
                self.canvas.itemconfig(self.bg_rect, fill=self.bg_color)
        except Exception:
            pass

    def _imgwatch_warn(self):
        self._imgwatch_warn_job = None
        # 1 秒：深一档提示
        try:
            self.btn_imgwatch.config(fg='#B71C1C')
        except Exception:
            pass

    def _fire_imgwatch_longpress(self):
        self._stop_hold_visual()
        self._imgwatch_longpress_job = None
        self._imgwatch_longpress_fired = True
        if self._imgwatch_warn_job:
            try: self.root.after_cancel(self._imgwatch_warn_job)
            except Exception: pass
            self._imgwatch_warn_job = None
        if self._imgwatch_toggle_job:
            try: self.root.after_cancel(self._imgwatch_toggle_job)
            except Exception: pass
            self._imgwatch_toggle_job = None
        # 长按：记录当前状态，然后关闭监控
        _was_enabled = bool(self.img_watch_enabled
                            or self.template_watcher is not None)
        if self.img_watch_enabled:
            self.img_watch_enabled = False
            try: self.stop_image_watch()
            except Exception: pass
            update_config_field(["img_watch", "enabled"], False)
            iw = self.config.get("img_watch", {})
            iw["enabled"] = False
            self.config["img_watch"] = iw
            self._refresh_imgwatch_button()
            print("⏹ 长按 👁：监控已关闭，打开规则管理", flush=True)
        self.open_rule_manager(watch_was_enabled=_was_enabled)

    def _on_imgwatch_release(self, event):
        if self._imgwatch_longpress_job:
            try: self.root.after_cancel(self._imgwatch_longpress_job)
            except Exception: pass
            self._imgwatch_longpress_job = None
        if self._imgwatch_warn_job:
            try: self.root.after_cancel(self._imgwatch_warn_job)
            except Exception: pass
            self._imgwatch_warn_job = None
        self._stop_hold_visual()
        if not self._imgwatch_longpress_fired:
            self._on_imgwatch_short_click()
        else:
            self._refresh_imgwatch_button()
        self._imgwatch_longpress_fired = False

    def _on_imgwatch_short_click(self):
        if self._imgwatch_toggle_job:
            try: self.root.after_cancel(self._imgwatch_toggle_job)
            except Exception: pass
            self._imgwatch_toggle_job = None
        self._imgwatch_toggle_job = self.root.after(
            self.toggle_click_delay_ms, self._resolve_imgwatch_click)

    def _resolve_imgwatch_click(self):
        self._imgwatch_toggle_job = None
        self.toggle_image_watch()

    def _on_exit_press(self, event):
        self._exit_longpress_fired = False
        if self._exit_longpress_job:
            try: self.root.after_cancel(self._exit_longpress_job)
            except Exception: pass
        try: self.btn_exit.config(bg='#FF8A80')
        except Exception: pass
        self._start_hold_visual(self.exit_reload_long_press_ms)
        self._exit_warn_job = self.root.after(
            max(500, self.exit_reload_long_press_ms // 2), self._exit_warn)
        self._exit_longpress_job = self.root.after(
            self.exit_reload_long_press_ms, self._fire_exit_longpress)

    def _exit_warn(self):
        self._exit_warn_job = None
        if self._exit_longpress_fired: return
        try: self.btn_exit.config(bg='#FF7043', text="↻")
        except Exception: pass

    def _fire_exit_longpress(self):
        self._stop_hold_visual()
        self._exit_longpress_job = None
        self._exit_longpress_fired = True
        if self._exit_warn_job:
            try: self.root.after_cancel(self._exit_warn_job)
            except Exception: pass
            self._exit_warn_job = None
        self.reload_config()

    def _on_exit_release(self, event):
        if self._exit_longpress_job:
            try: self.root.after_cancel(self._exit_longpress_job)
            except Exception: pass
            self._exit_longpress_job = None
        if self._exit_warn_job:
            try: self.root.after_cancel(self._exit_warn_job)
            except Exception: pass
            self._exit_warn_job = None
        self._stop_hold_visual()
        if not self._exit_longpress_fired:
            self.cleanup_and_exit()
        else:
            try: self.btn_exit.config(bg='#FFD0D0', text="✕")
            except Exception: pass
        self._exit_longpress_fired = False

    def _on_volume_press(self, event):
        self._volume_longpress_fired = False
        if self._volume_longpress_job:
            try: self.root.after_cancel(self._volume_longpress_job)
            except Exception: pass
        try: self.volume_btn.config(bg='#FFB74D')
        except Exception: pass
        self._start_hold_visual(self.long_press_ms)
        self._volume_longpress_job = self.root.after(
            self.long_press_ms, self._fire_volume_longpress)

    def _fire_volume_longpress(self):
        self._stop_hold_visual()
        self._volume_longpress_job = None
        self._volume_longpress_fired = True
        try: self.volume_btn.config(bg='#E0E0E0')
        except Exception: pass
        self._open_volume_settings()

    def _on_volume_release(self, event):
        if self._volume_longpress_job:
            try: self.root.after_cancel(self._volume_longpress_job)
            except Exception: pass
            self._volume_longpress_job = None
        try: self.volume_btn.config(bg='#E0E0E0')
        except Exception: pass
        self._stop_hold_visual()
        if not self._volume_longpress_fired:
            # 短按：如果路径未绑定，弹出四选项向导
            if not self.sv_path or not os.path.exists(self.sv_path):
                self._open_volume_wizard()
            else:
                self.toggle_volume()
        self._volume_longpress_fired = False

    def _open_volume_wizard(self):
        """短按 🔊 且路径未配置：弹出四选项向导（单例）"""
        # 已存在则 lift 到前面，不新建
        if getattr(self, "_volume_wizard_dlg", None) is not None:
            try:
                d = self._volume_wizard_dlg.dlg
                if d is not None and d.winfo_exists():
                    d.lift()
                    d.focus_force()
                    return
            except Exception:
                pass
            self._volume_wizard_dlg = None

        from .volume_settings import VolumeWizardDialog
        from .config_manager import update_config_field

        dlg = VolumeWizardDialog(self, scale=self.scale)
        self._volume_wizard_dlg = dlg
        action = dlg.show()
        self._volume_wizard_dlg = None
        print(f"🔊 音量向导选择：{action}", flush=True)

        if action == "download":
            # 复用 _on_download：先打开设置对话框再触发下载
            self._open_volume_settings()
        elif action == "manual":
            # 打开设置对话框，让用户填路径
            self._open_volume_settings()
        elif action == "later":
            # 什么都不做
            pass
        elif action == "disable":
            # 关闭音量功能：写 volume_enabled = false，然后重载
            ok = update_config_field(["volume_enabled"], False)
            self.config["volume_enabled"] = False
            print(f"🔇 音量功能已关闭（写入 config.toml: {ok}），"
                  f"即将重载配置", flush=True)
            # 延迟一点，让向导窗口先销毁干净
            self.root.after(80, self.reload_config)

    def _on_md_press(self, event):
        self._md_longpress_fired = False
        if self._md_longpress_job:
            try: self.root.after_cancel(self._md_longpress_job)
            except Exception: pass
        try: self.btn_md.config(bg='#FFB74D')
        except Exception: pass
        self._start_hold_visual(self.long_press_ms)
        self._md_longpress_job = self.root.after(
            self.long_press_ms, self._fire_md_longpress)

    def _fire_md_longpress(self):
        self._stop_hold_visual()
        self._md_longpress_job = None
        self._md_longpress_fired = True
        try: self.btn_md.config(bg='#E0E0E0')
        except Exception: pass
        self._open_md_settings()

    def _on_md_release(self, event):
        if self._md_longpress_job:
            try: self.root.after_cancel(self._md_longpress_job)
            except Exception: pass
            self._md_longpress_job = None
        try: self.btn_md.config(bg='#E0E0E0')
        except Exception: pass
        self._stop_hold_visual()
        if not self._md_longpress_fired:
            self.toggle_md_window()
        self._md_longpress_fired = False
