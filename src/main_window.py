"""主窗口：把所有模块串起来"""
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

from .mw_ui import MainWindowUI
from .mw_drag import MainWindowDrag
from .mw_monitor import MainWindowMonitor
from .mw_dialogs import MainWindowDialogs


class NetworkBlockerApp(MainWindowUI, MainWindowDrag,
                       MainWindowMonitor, MainWindowDialogs):
    def __init__(self, root):
        self.root = root
        self.cleanup_done = False
        self.is_running = False
        self.log_window = None
        self.md_window = None
        self.md_text = None
        self.time_dialog = None
        self.time_entry = None
        self.overlay_var = None
        self.stop_monitor = Event()
        self.stop_ping_event = Event()
        self.stop_vis_mute_event = Event()
        self.rule_base = "Block_App"

        self.animate_id = None
        self.wave_offset = 0
        self.time_update_id = None

        self.saved_volume = None
        self.is_muted = False
        self.auto_muted_by_hide = False
        self.volume_btn = None
        self.ping_timeout_counter = 0
        self.ping_label_id = None

        self._move_job = None
        self._pending_x = 0
        self._pending_y = 0
        self._drag_offset_x = None
        self._drag_offset_y = None

        self.scale = self._get_dpi_scale()
        self.config, self.templates, self.state = load_config()
        self._apply_config_to_attributes()

        self.template_watcher = None
        self.roi_overlay = None
        self.btn_imgwatch = None
        self._hold_start = 0.0
        self._hold_anim_job = None
        self._imgwatch_longpress_job = None
        self._imgwatch_longpress_fired = False
        self._imgwatch_toggle_job = None
        self._imgwatch_warn_job = None
        self._md_longpress_job = None
        self._md_longpress_fired = False
        self._volume_longpress_job = None
        self._volume_longpress_fired = False
        self._exit_longpress_job = None
        self._exit_longpress_fired = False
        self._exit_warn_job = None
        self._region_selector = None
        self._roi_editor = None
        self._volume_wizard_dlg = None
        self._volume_settings_dlg = None
        self._select_hwnd = None
        self._select_client_rect = None
        self._select_on_done = None
        self._select_on_restore = None
        self._log_handler = None
        self._rule_dialog = None
        self.hit_history = deque(maxlen=20)
        self.hit_history_window = None
        self._hit_history_listbox = None
        self._highlight_overlay = None
        self._highlight_job = None

        self.root.overrideredirect(True)
        self.root.attributes('-toolwindow', True)
        self.root.attributes('-topmost', True)
        self.root.configure(bg=self.transparent_color)
        self.root.attributes('-transparentcolor', self.transparent_color)
        self.root.geometry(f"{self.w}x{self.h}")
        self.root.title("月圆之夜断网工具 v4.8.0")

        try:
            dpi_now = _user32.GetDpiForWindow(self.root.winfo_id())
        except Exception:
            dpi_now = 0
        print(f"🪟 窗口尺寸: {self.w}x{self.h} (scale={self.scale:.3f}, dpi={dpi_now})",
              flush=True)

        wx = self.state.get("window_x")
        wy = self.state.get("window_y")
        if wx is not None and wy is not None:
            self.root.geometry(f"+{wx}+{wy}")
        else:
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            self.root.geometry(f"+{(sw-self.w)//2}+{(sh-self.h)//2}")

        self.restore_network_on_startup()
        self.validate_config_and_prompt()
        self.launch_app_if_needed()
        self.create_widgets()
        self.add_drag_functionality()
        self._setup_hotkeys()
        self.start_game_monitor()
        self.start_ping_monitor()
        self.start_heartbeat_animation()
        self.start_clock_update()
        self.start_visibility_mute_monitor()
        self._refresh_imgwatch_button()
        if self.img_watch_enabled and is_capture_available() and is_ocr_available() \
                and self.valid_targets:
            self.start_image_watch()

    def safe_exit(self):
        self.stop_animation()
        self.stop_clock()
        self.stop_image_watch()
        self.stop_visibility_mute_monitor()
        self.restore_volume_if_needed()
        self.cleanup()
        self.root.destroy()

    def cleanup_and_exit(self):
        self.state["window_x"] = self.root.winfo_x()
        self.state["window_y"] = self.root.winfo_y()
        if self.md_window is not None and self.md_window.winfo_exists():
            self.save_md_state()
        save_state(self.state)
        self.stop_animation(); self.stop_clock()
        self.stop_ping_event.set(); self.stop_vis_mute_event.set()
        self.stop_image_watch()
        self.restore_volume_if_needed()
        self.cleanup()
        self.root.destroy()





    def reload_config(self):
        print("🔄 重载配置...", flush=True)
        try:
            win_x = self.root.winfo_x(); win_y = self.root.winfo_y()
        except Exception:
            win_x = win_y = None
        self.stop_monitor.set()
        self.stop_ping_event.set()
        self.stop_vis_mute_event.set()
        try: self.stop_image_watch()
        except Exception: pass
        self.stop_clock(); self.stop_animation()
        self.config, self.templates, self.state = load_config()
        self._apply_config_to_attributes()
        self.stop_monitor.clear()
        self.stop_ping_event.clear()
        self.stop_vis_mute_event.clear()
        self._region_selector = None
        self._select_hwnd = None
        self._select_client_rect = None
        try: self.canvas.destroy()
        except Exception: pass
        self.create_widgets()
        self.add_drag_functionality()
        self._setup_hotkeys()
        if win_x is not None and win_y is not None:
            self.root.geometry(f"{self.w}x{self.h}+{win_x}+{win_y}")
        else:
            self.root.geometry(f"{self.w}x{self.h}")
        self.start_game_monitor()
        self.start_ping_monitor()
        self.start_heartbeat_animation()
        self.start_clock_update()
        self.start_visibility_mute_monitor()
        self._refresh_imgwatch_button()
        if self.img_watch_enabled and is_capture_available() and is_ocr_available() \
                and self.valid_targets:
            self.start_image_watch()
        print("✅ 配置重载完成", flush=True)

    def toggle_process(self, event=None):
        if not self.is_running:
            self.is_running = True
            self.canvas.itemconfig(self.bg_rect, fill="#F44336")
            self.thread = Thread(target=self.run_block_once,
                                 args=(self.block_time,), daemon=True)
            self.thread.start()
        else:
            self.is_running = False
            self.canvas.itemconfig(self.bg_rect, fill=self.bg_color)

    def clear_firewall_rules(self):
        try:
            print("🧹 清除防火墙规则...", flush=True)
            unblock_network_for_targets(self.rule_base, len(self.block_targets_exe))
            enable_all_network()
            self.is_running = False
            self.canvas.itemconfig(self.bg_rect, fill=self.bg_color)
            print("✅ 网络已恢复", flush=True)
        except Exception as e:
            print(f"清除规则出错: {e}", flush=True)

    def cleanup(self):
        if self.cleanup_done: return
        print("正在清理资源...", flush=True)
        self.is_running = False
        self.stop_monitor.set()
        self.stop_ping_event.set()
        self.stop_vis_mute_event.set()
        self.stop_image_watch()
        try:
            unblock_network_for_targets(self.rule_base, len(self.block_targets_exe))
            enable_all_network()
            print("✅ 已恢复网络", flush=True)
        except Exception: pass
        self.cleanup_done = True

    def run_block_once(self, block_time):
        try:
            if self.is_global_mode:
                print(f"🌐 全局断网 {block_time} 秒", flush=True)
                disable_all_network()
            else:
                print(f"🛑 防火墙阻断 {block_time} 秒", flush=True)
                block_network_for_targets(self.rule_base, self.valid_targets)
            start = time.time()
            while time.time() - start < block_time:
                if not self.is_running: break
                time.sleep(0.1)
            if self.is_global_mode:
                enable_all_network()
            else:
                unblock_network_for_targets(self.rule_base, len(self.valid_targets))
            print("✅ 网络已恢复", flush=True)
        except Exception as e:
            print(f"❌ 错误: {e}", flush=True)
        finally:
            if self.is_running:
                self.is_running = False
                self.root.after(0, lambda: self.canvas.itemconfig(
                    self.bg_rect, fill=self.bg_color))

    # ---------------- 使用手册（📄）长短按 ----------------

