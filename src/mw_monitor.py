"""Mixin: 后台监控 + 高亮 + 音量"""
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


class MainWindowMonitor:
    def get_target_exe_name(self):
        """供 rule_manager 调用，返回目标 exe 名字"""
        if not self.valid_targets: return ""
        return os.path.basename(self.valid_targets[0])

    def restore_network_on_startup(self):
        print("🔄 启动恢复：清理遗留规则 + 启用所有网卡...", flush=True)
        unblock_network_for_targets(self.rule_base, len(self.block_targets_exe))
        enable_all_network()

    def validate_config_and_prompt(self):
        invalid_targets = []
        for cfg, resolved in zip(self.block_targets_config, self.block_targets_exe):
            if cfg == "": continue
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

    def launch_app_if_needed(self):
        if not self.launch_exe_path: return
        if not os.path.exists(self.launch_exe_path): return
        if is_process_running(self.launch_exe_path):
            print(f"✅ 应用已在运行：{os.path.basename(self.launch_exe_path)}", flush=True)
            return
        print(f"🚀 正在启动应用：{self.launch_exe_path}", flush=True)
        try:
            subprocess.Popen([self.launch_exe_path],
                             cwd=os.path.dirname(self.launch_exe_path))
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
                time.sleep(self.game_monitor_interval_s)
        Thread(target=monitor, daemon=True).start()

    def start_visibility_mute_monitor(self):
        # 线程只启动一次，内部动态检查 self.auto_mute_when_hidden 开关
        if getattr(self, "_vis_mute_thread_started", False):
            return
        self._vis_mute_thread_started = True
        def monitor():
            last_visible = None
            while not self.stop_vis_mute_event.is_set():
                try:
                    if not self.auto_mute_when_hidden:
                        last_visible = None
                        time.sleep(self.visibility_check_interval_s); continue
                    if self.is_global_mode or not self.valid_targets:
                        time.sleep(self.visibility_check_interval_s); continue
                    if not self.sv_path or not os.path.exists(self.sv_path):
                        time.sleep(self.visibility_check_interval_s); continue
                    target_exe = self.valid_targets[0]
                    if not is_process_running(target_exe):
                        time.sleep(self.visibility_check_interval_s); continue
                    exe_name = os.path.basename(target_exe)
                    visible = is_game_window_on_screen(exe_name)
                    if visible != last_visible:
                        if visible:
                            self.root.after(0, self._auto_unmute_for_hide)
                        else:
                            self.root.after(0, self._auto_mute_for_hide)
                        last_visible = visible
                except Exception as e:
                    print(f"👁 可见性监控异常: {e}", flush=True)
                time.sleep(self.visibility_check_interval_s)
        Thread(target=monitor, daemon=True).start()
        print("👁 窗口可见性静音监控已启动", flush=True)

    def stop_visibility_mute_monitor(self):
        self.stop_vis_mute_event.set()

    def _auto_mute_for_hide(self):
        if self.auto_muted_by_hide or self.is_muted: return
        if not self.sv_path or not self.valid_targets or not os.path.exists(self.sv_path):
            return
        target_exe = self.valid_targets[0]
        if not is_process_running(target_exe): return
        current_vol = get_process_volume(self.sv_path, target_exe)
        if current_vol is None: return
        self.saved_volume = current_vol
        set_process_volume(self.sv_path, target_exe, int(self.volume_mute_value))
        self.is_muted = True
        self.auto_muted_by_hide = True
        if self.volume_btn:
            self.volume_btn.config(text="🔇", bg="#FFD0D0")
        print(f"👁 游戏窗口隐藏 → 自动静音（原音量 {current_vol}%）", flush=True)

    def _auto_unmute_for_hide(self):
        if not self.auto_muted_by_hide: return
        if self.saved_volume is None or not self.sv_path or not self.valid_targets:
            self.auto_muted_by_hide = False; return
        target_exe = self.valid_targets[0]
        if not is_process_running(target_exe):
            self.auto_muted_by_hide = False; return
        if set_process_volume(self.sv_path, target_exe, self.saved_volume):
            print(f"👁 游戏窗口恢复 → 自动恢复音量到 {self.saved_volume}%", flush=True)
        self.is_muted = False
        self.saved_volume = None
        self.auto_muted_by_hide = False
        if self.volume_btn:
            self.volume_btn.config(text="🔊", bg='#E0E0E0')

    def start_ping_monitor(self):
        if not self.ping_target: return
        def ping_loop():
            while not self.stop_ping_event.is_set():
                delay = self.get_ping_delay(self.ping_target)
                if delay is None:
                    self.ping_timeout_counter = min(999, self.ping_timeout_counter + 1)
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
            match = re.search(r'(?:时间|time)=(\d+)ms', proc.stdout)
            return int(match.group(1)) if match else None
        except Exception:
            return None

    def update_ping_label(self, text):
        if self.ping_label_id and self.canvas:
            self.canvas.itemconfig(self.ping_label_id, text=text)

    def restore_volume_if_needed(self):
        if self.is_muted and self.saved_volume is not None and self.sv_path \
                and self.valid_targets:
            target_exe = self.valid_targets[0]
            if os.path.exists(target_exe) and is_process_running(target_exe):
                set_process_volume(self.sv_path, target_exe, self.saved_volume)
            self.is_muted = False
            self.saved_volume = None
            self.auto_muted_by_hide = False
            if self.volume_btn:
                self.volume_btn.config(text="🔊", bg='#E0E0E0')

    def toggle_image_watch(self):
        if not is_capture_available():
            messagebox.showerror("错误", "未安装 mss/numpy"); return
        if not is_ocr_available():
            messagebox.showerror("错误", "未安装 rapidocr-onnxruntime"); return
        if self.is_global_mode or not self.valid_targets:
            messagebox.showerror("错误", "无有效断网目标"); return
        iw = self.config.get("img_watch", {})
        if not self.img_watch_enabled:
            self.img_watch_enabled = True
            self.start_image_watch()
        else:
            self.img_watch_enabled = False
            self.stop_image_watch()
        self._refresh_imgwatch_button()
        update_config_field(["img_watch", "enabled"], self.img_watch_enabled)
        iw["enabled"] = self.img_watch_enabled
        self.config["img_watch"] = iw

    def start_image_watch(self):
        if self.template_watcher is not None: return
        target_exe = self.valid_targets[0]
        iw = self.config.get("img_watch", {})
        if bool(iw.get("debug_overlay", True)):
            self.roi_overlay = RoiOverlay(
                self.root, exe_name=os.path.basename(target_exe), scale=self.scale,
                get_rules_cb=lambda: self.templates)
            self.roi_overlay.show()
        else:
            self.roi_overlay = None
        self.template_watcher = TemplateWatcher(
            exe_path=target_exe, config=self.config, templates=self.templates,
            overlay=self.roi_overlay,
            on_match=lambda: self.root.after(0, self._on_image_match),
            own_hwnds_cb=self._collect_own_hwnds,
            on_highlight=self._make_highlight_cb())
        self.template_watcher.start()
        print("👁 OCR 监控已启动", flush=True)

    def stop_image_watch(self):
        if self.template_watcher is not None:
            try: self.template_watcher.stop()
            except Exception as e:
                print(f"👁 停止监控线程失败: {e}", flush=True)
            self.template_watcher = None
        if self.roi_overlay is not None:
            try: self.roi_overlay.hide()
            except Exception as e:
                print(f"👁 隐藏叠加框失败: {e}", flush=True)
            self.roi_overlay = None
        print("👁 OCR 监控已停止", flush=True)

    def _on_image_match(self):
        print("👁 触发断网", flush=True)
        if not self.is_running:
            self.toggle_process()

    def _make_highlight_cb(self):
        """构造给 TemplateWatcher 用的高亮回调（线程安全，调度到主线程）"""
        def cb(names, kind):
            try:
                self.root.after(0, lambda: self._on_highlight(names, kind))
            except Exception as e:
                print(f"调度高亮失败: {e}", flush=True)
        return cb

    def _on_highlight(self, names, kind):
        """规则命中：记录历史 + 闪烁高亮框"""
        ts = datetime.now().strftime("%H:%M:%S")
        name_str = "、".join(names) if names else "?"
        self.hit_history.append((ts, kind, name_str))
        self._refresh_hit_history_view()
        try:
            self._show_highlight_flash(names, kind)
        except Exception as e:
            print(f"高亮闪烁失败: {e}", flush=True)

    def _show_highlight_flash(self, names, kind, duration_ms=900):
        """在游戏客户区上闪一个绿/蓝框，标记命中的规则"""
        if self.is_global_mode or not self.valid_targets:
            return
        target_exe = self.valid_targets[0]
        exe_name = os.path.basename(target_exe)
        pid = get_pid_by_exe_name(exe_name)
        if pid is None: return
        hwnd = get_hwnd_by_pid(pid)
        if not hwnd or not is_window_alive(hwnd):
            return
        if (not is_window_visible(hwnd) or is_window_minimized(hwnd)
                or is_window_cloaked(hwnd)):
            return
        l, t, r, b = get_client_rect_screen(hwnd)
        cw, ch = r - l, b - t
        if cw <= 0 or ch <= 0: return
        size_key = f"{cw}x{ch}"
        rules = self.templates.get(size_key, {})
        if not isinstance(rules, dict) or not rules:
            rules = self.templates.get("default", {})
        if not isinstance(rules, dict):
            return
        lst_key = "whitelist" if kind == "white" else "blacklist"
        lst = rules.get(lst_key, [])
        if not isinstance(lst, list): return
        names_set = set(names) if names else None
        boxes = []
        for rr in lst:
            if not isinstance(rr, dict): continue
            if not rule_has_roi(rr): continue
            if names_set is not None and rr.get("name", "") not in names_set:
                continue
            x1, y1, x2, y2 = rule_roi(rr)
            boxes.append((
                l + int(cw * x1), t + int(ch * y1),
                l + int(cw * x2), t + int(ch * y2),
            ))
        if not boxes:
            return
        # 销毁上一次高亮
        if self._highlight_overlay is not None:
            try: self._highlight_overlay.destroy()
            except Exception: pass
            self._highlight_overlay = None
        if self._highlight_job is not None:
            try: self.root.after_cancel(self._highlight_job)
            except Exception: pass
            self._highlight_job = None
        try:
            top = tk.Toplevel(self.root)
            top.overrideredirect(True)
            top.attributes('-topmost', True)
            top.configure(bg='#FE01FE')
            try: top.attributes('-transparentcolor', '#FE01FE')
            except Exception: pass
            min_x = min(bx[0] for bx in boxes)
            min_y = min(bx[1] for bx in boxes)
            max_x = max(bx[2] for bx in boxes)
            max_y = max(bx[3] for bx in boxes)
            pad = 8
            w = (max_x - min_x) + pad * 2
            h = (max_y - min_y) + pad * 2
            top.geometry(f"{w}x{h}+{min_x - pad}+{min_y - pad}")
            cvs = tk.Canvas(top, bg='#FE01FE', highlightthickness=0, bd=0)
            cvs.pack(fill=tk.BOTH, expand=True)
            color = '#4CAF50' if kind == 'white' else '#2196F3'
            for (x1, y1, x2, y2) in boxes:
                cvs.create_rectangle(x1 - min_x + pad, y1 - min_y + pad,
                                     x2 - min_x + pad, y2 - min_y + pad,
                                     outline=color, width=5, fill='')
            try:
                from .win_utils import set_window_capture_exclude
                raw = top.winfo_id()
                th = _user32.GetAncestor(raw, GA_ROOT) or raw
                set_window_capture_exclude(th)
            except Exception:
                pass
            self._highlight_overlay = top

            def finish():
                try:
                    if self._highlight_overlay is not None:
                        self._highlight_overlay.destroy()
                except Exception:
                    pass
                self._highlight_overlay = None
                self._highlight_job = None

            self._highlight_job = self.root.after(duration_ms, finish)
        except Exception as e:
            print(f"高亮框创建失败: {e}", flush=True)

    def toggle_volume(self):
        if not self.sv_path or not self.valid_targets \
                or not os.path.exists(self.sv_path):
            messagebox.showerror("错误", "音量控制不可用。"); return
        target_exe = self.valid_targets[0]
        if not os.path.exists(target_exe) or not is_process_running(target_exe):
            messagebox.showerror("错误", "目标游戏未运行。"); return
        if not self.is_muted:
            current_vol = get_process_volume(self.sv_path, target_exe)
            if current_vol is None:
                messagebox.showerror("错误", "无法获取当前音量"); return
            self.saved_volume = current_vol
            set_process_volume(self.sv_path, target_exe, int(self.volume_mute_value))
            self.is_muted = True
            self.auto_muted_by_hide = False
            if self.volume_btn:
                self.volume_btn.config(text="🔇", bg="#FFD0D0")
            print(f"🔇 静音（原音量 {current_vol}%）", flush=True)
        else:
            if self.saved_volume is None: return
            set_process_volume(self.sv_path, target_exe, self.saved_volume)
            self.is_muted = False
            self.saved_volume = None
            self.auto_muted_by_hide = False
            if self.volume_btn:
                self.volume_btn.config(text="🔊", bg='#E0E0E0')
            print("🔊 音量已恢复", flush=True)
