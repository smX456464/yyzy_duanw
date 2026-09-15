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
        self._disabled_ifaces = []
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

        # ---- 启动就绪标记（供按钮检查用） ----
        self._ready_network = False   # 网卡工具就绪
        self._ready_config = False    # 游戏路径检查完
        self._ready_launch = False    # 启动游戏完成
        self._bg_net_thread = None
        self._bg_launch_thread = None

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
        print("=" * 56, flush=True)
        print("🚀 信号变频 · 月圆之夜断网工具", flush=True)
        print("=" * 56, flush=True)
        print(f"📂 工作目录：{SCRIPT_DIR}", flush=True)
        print(f"🪟 窗口尺寸：{self.w}x{self.h} "
              f"(scale={self.scale:.3f}, DPI={dpi_now})", flush=True)
        if self.is_global_mode:
            print("🎯 断网目标：整机断网（断开全部网络）", flush=True)
        else:
            for _p in self.valid_targets:
                print(f"🎯 断网目标：{_p}", flush=True)
        if self.launch_exe_path:
            print(f"🚀 同步启动：{self.launch_exe_path}", flush=True)
        else:
            print("🚀 同步启动：已关闭（launch_app 为空）", flush=True)
        print(f"⏱ 断网秒数：手动 {self.block_time}s · "
              f"OCR 默认 {getattr(self, 'ocr_block_time', 1)}s", flush=True)
        if self.ping_target:
            print(f"📡 Ping 目标：{self.ping_target}", flush=True)
        else:
            print("📡 Ping：已禁用", flush=True)
        print("-" * 56, flush=True)

        wx = self.state.get("window_x")
        wy = self.state.get("window_y")
        if wx is not None and wy is not None:
            self.root.geometry(f"+{wx}+{wy}")
        else:
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            self.root.geometry(f"+{(sw-self.w)//2}+{(sh-self.h)//2}")

        # ============================================================
        # 一、UI 优先：快速搭建窗口（<0.3 秒）
        # ============================================================
        self.create_widgets()
        self.add_drag_functionality()
        self._setup_hotkeys()
        self.start_clock_update()
        self.start_heartbeat_animation()
        self.start_ping_monitor()
        self._refresh_imgwatch_button()
        # 让窗口立即显示
        try:
            self.root.update_idletasks()
        except Exception:
            pass
        # 启动图标自动刷新（每 2 秒同步一次状态）
        try:
            self._start_icon_auto_refresh()
        except Exception as e:
            print(f"⚠️ 图标自动刷新启动失败：{e}", flush=True)
        print("✅ UI 已就绪（后台初始化中…）", flush=True)

        # ============================================================
        # 二、后台慢操作
        # ============================================================
        # 后台线程 1：网卡清理（netsh 慢，1~2 秒）
        import threading as _th
        self._bg_net_thread = _th.Thread(
            target=self._bg_init_network, daemon=True)
        self._bg_net_thread.start()

        # 主线程 after：路径检查（Tkinter 弹窗必须主线程）
        self.root.after(30, self._init_after_ui)

    def _bg_init_network(self):
        """后台：清理防火墙规则 + 启用网卡"""
        try:
            print("🔄 [后台] 启动恢复：清理遗留防火墙规则…", flush=True)
            unblock_network_for_targets(self.rule_base,
                                         len(self.block_targets_exe))
            print("🔄 [后台] 启动恢复：启用所有网卡…", flush=True)
            enable_all_network()
            print("✅ [后台] 启动恢复完成", flush=True)
        except Exception as e:
            print(f"⚠️ [后台] 启动恢复失败：{e}", flush=True)
        finally:
            self._ready_network = True

    def _init_after_ui(self):
        """主线程：路径检查 + 游戏启动"""
        try:
            if not self._check_game_path():
                return
        except Exception as e:
            print(f"⚠️ 路径检查失败：{e}", flush=True)
        self._ready_config = True
        try:
            self.validate_config_and_prompt()
        except Exception as e:
            print(f"⚠️ 配置校验失败：{e}", flush=True)
        # 后台线程 2：启动游戏（不阻塞）
        import threading as _th
        self._bg_launch_thread = _th.Thread(
            target=self._bg_launch_app, daemon=True)
        self._bg_launch_thread.start()
        # 其他后台监控
        self.start_game_monitor()
        self.start_visibility_mute_monitor()
        # OCR 监控：如果游戏已在运行，立刻启动；
        # 否则等 start_game_monitor 检测到游戏后自动启动（_on_game_appeared）
        if self.img_watch_enabled and is_capture_available() \
                and is_ocr_available() and self.valid_targets:
            try:
                _game_now = any(is_process_running(t)
                                for t in self.valid_targets)
                if _game_now:
                    self.start_image_watch()
                else:
                    print("👁 OCR 监控：等待游戏启动后自动启用…",
                          flush=True)
            except Exception as e:
                print(f"⚠️ OCR 监控启动失败：{e}", flush=True)

    def _bg_launch_app(self):
        """后台：启动游戏"""
        try:
            self.launch_app_if_needed()
        except Exception as e:
            print(f"⚠️ [后台] 启动游戏失败：{e}", flush=True)
        finally:
            self._ready_launch = True

    def _wait_ready(self, which, name):
        """检查某项是否就绪，未就绪弹提示。返回 True 表示可继续。

        which: 'network' / 'config' / 'launch'
        """
        flag = getattr(self, f"_ready_{which}", True)
        if flag:
            return True
        try:
            from tkinter import messagebox
            messagebox.showinfo(
                "正在初始化",
                f"{name} 正在准备中，请稍候几秒…\n\n"
                f"（首次启动或刚重载配置时会慢一点）",
                parent=self.root)
        except Exception:
            pass
        return False

    def safe_exit(self):
        """安全退出（跟 cleanup_and_exit 一致：立即隐藏 + 后台清理）"""
        self.cleanup_and_exit()


    def cleanup_and_exit(self):
        """关闭工具：立即隐藏窗口 + 后台清理

        用户视觉：窗口瞬间消失（<100ms）
        后台：真正清理 netsh 规则（约 1~2 秒）
        完成后进程退出
        """
        if self.cleanup_done:
            return
        # 1. 保存窗口位置
        try:
            self.state["window_x"] = self.root.winfo_x()
            self.state["window_y"] = self.root.winfo_y()
            if self.md_window is not None and self.md_window.winfo_exists():
                self.save_md_state()
            save_state(self.state)
        except Exception as e:
            print(f"\u26a0\ufe0f 保存状态失败: {e}", flush=True)

        # 2. 立即隐藏窗口（用户看到"瞬关"）
        try:
            self.root.withdraw()
        except Exception:
            pass

        # 3. 停止快速操作（不涉及 netsh）
        try:
            self.stop_animation()
        except Exception:
            pass
        try:
            self.stop_clock()
        except Exception:
            pass
        try:
            self.stop_ping_event.set()
        except Exception:
            pass
        try:
            self.stop_vis_mute_event.set()
        except Exception:
            pass

        # 4. 后台线程处理慢操作
        import threading as _th
        _th.Thread(target=self._bg_cleanup_and_quit, daemon=True).start()

    def _bg_cleanup_and_quit(self):
        """后台：真正清理网络 + 退出进程"""
        try:
            # 停止 OCR 监控
            try:
                self.stop_image_watch()
            except Exception as e:
                print(f"\u26a0\ufe0f 停止 OCR 监控失败: {e}", flush=True)
            # 恢复音量
            try:
                self.restore_volume_if_needed()
            except Exception as e:
                print(f"\u26a0\ufe0f 恢复音量失败: {e}", flush=True)
            # 清理防火墙 + 启用网卡（最慢的部分）
            try:
                print("\U0001f9f9 [后台] 正在清理网络…", flush=True)
                self.cleanup()
            except Exception as e:
                print(f"\u26a0\ufe0f 后台清理失败: {e}", flush=True)
        finally:
            # 无论成功失败，都退出
            try:
                self.root.after(0, self._final_quit)
            except Exception:
                pass

    def _final_quit(self):
        """最后一步：销毁 root 让 mainloop 退出"""
        try:
            self.root.destroy()
        except Exception:
            pass
        # 保险：如果 destroy 后 mainloop 还没退，强制退出
        try:
            import os as _os
            _os._exit(0)
        except Exception:
            pass


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

    def toggle_process(self, event=None, custom_block_time=None,
                       rule_name=""):
        # 未就绪检查
        if not self.is_running and not self._wait_ready("network", "网卡工具"):
            return
        if not self.is_running:
            self.is_running = True
            self.canvas.itemconfig(self.bg_rect, fill="#F44336")
            bt = custom_block_time if custom_block_time else self.block_time
            self.thread = Thread(target=self.run_block_once,
                                 args=(bt, rule_name), daemon=True)
            self.thread.start()
        else:
            self.is_running = False
            self.canvas.itemconfig(self.bg_rect, fill=self.bg_color)

    def clear_firewall_rules(self):
        if not self._wait_ready("network", "网卡工具"):
            return
        try:
            print("🧹 清除防火墙规则...", flush=True)
            unblock_network_for_targets(self.rule_base, len(self.block_targets_exe))
            enable_all_network()
            self.is_running = False
            self.canvas.itemconfig(self.bg_rect, fill=self.bg_color)
            print("✅ 网络已恢复", flush=True)
        except Exception as e:
            print(f"清除规则出错: {e}", flush=True)

    def _rollback_config_if_first_run(self):
        """首次运行时（config.toml 刚生成），
        用户选择退出则删除刚生成的配置文件，
        做到“启动前什么样，启动后也什么样”。
        """
        from . import config_manager
        if not config_manager.JUST_CREATED_CONFIG:
            return
        targets = [
            config_manager.CONFIG_TOML,
            config_manager.TEMPLATES_TOML,
            config_manager.STATE_TOML,
        ]
        for path in targets:
            try:
                if os.path.exists(path):
                    os.remove(path)
                    print(f"ℹ 已删除本次生成的：{os.path.basename(path)}",
                          flush=True)
            except Exception as e:
                print(f"⚠ 删除 {os.path.basename(path)} 失败: {e}",
                      flush=True)

    def cleanup(self):
        if self.cleanup_done:
            return
        print("-" * 56, flush=True)
        print("🧹 正在清理资源…", flush=True)
        self.is_running = False
        self.stop_monitor.set()
        self.stop_ping_event.set()
        self.stop_vis_mute_event.set()
        self.stop_image_watch()
        try:
            print("🧹 清理防火墙规则…", flush=True)
            unblock_network_for_targets(self.rule_base,
                                         len(self.block_targets_exe))
            print("🧹 启用所有网卡…", flush=True)
            enable_all_network()
            print("✅ 网络已恢复", flush=True)
        except Exception as e:
            print(f"⚠️  清理时出错: {e}", flush=True)
        self.cleanup_done = True
        print("👋 已退出", flush=True)


    def run_block_once(self, block_time, rule_name=""):
        """断网：至少 block_time 秒，之后每秒检查黑白名单：
          · 黑名单命中 → 恢复
          · 只白名单命中 → 继续断（最多 HARD_MAX 秒）
          · 都不命中 → 恢复
        """
        HARD_MAX = 30.0
        try:
            tag = f"｜规则「{rule_name}」" if rule_name else "｜手动"
            if self.is_global_mode:
                print(f"🌐 整机断网 {block_time} 秒{tag}", flush=True)
                self._disabled_ifaces = disable_all_network()
            else:
                print(f"🛑 防火墙阻断 {block_time} 秒{tag}"
                      f"（目标 {len(self.valid_targets)} 个）", flush=True)
                block_network_for_targets(self.rule_base, self.valid_targets)
            start = time.time()
            # 阶段一：至少断 block_time 秒
            while time.time() - start < block_time:
                if not self.is_running:
                    break
                time.sleep(0.1)
            elapsed = time.time() - start
            print(f"✅ 已断 {elapsed:.1f} 秒，进入动态检查…", flush=True)
            # 阶段二：动态检查
            while self.is_running and (time.time() - start) < HARD_MAX:
                res = None
                try:
                    if self.template_watcher is not None:
                        res = self.template_watcher.get_last_scan_result()
                except Exception:
                    res = None
                if res is None:
                    print("ℹ 无扫描结果 → 直接恢复", flush=True)
                    break
                bl = bool(res.get("bl_hit"))
                wl = bool(res.get("wl_hit"))
                rn = res.get("rule_name", "")
                elapsed = time.time() - start
                if bl:
                    print(f"✅ 黑名单命中 → 恢复（已断 {elapsed:.1f}s）",
                          flush=True)
                    break
                if not wl:
                    print(f"✅ 无命中 → 恢复（已断 {elapsed:.1f}s）",
                          flush=True)
                    break
                print(f"⏳ 仍白名单命中"
                      + (f"「{rn}」" if rn else "")
                      + f"（{elapsed:.1f}s）→ 继续 1 秒", flush=True)
                time.sleep(1.0)
            else:
                if self.is_running:
                    elapsed = time.time() - start
                    print(f"⚠ 达到 {HARD_MAX}s 上限 → 强制恢复", flush=True)
            # 恢复
            if self.is_global_mode:
                enable_all_network(self._disabled_ifaces)
                self._disabled_ifaces = []
            else:
                unblock_network_for_targets(self.rule_base,
                                             len(self.valid_targets))
            print("✅ 网络已恢复", flush=True)
        except Exception as e:
            print(f"❌ 错误: {e}", flush=True)
        finally:
            if self.is_running:
                self.is_running = False
                self.root.after(0, lambda: self.canvas.itemconfig(
                    self.bg_rect, fill=self.bg_color))

    def _check_game_path(self):
        """启动时检查游戏路径。

        规则：
          · 源码模式（sys.frozen == False）→ 跳过
          · game_path_check_enabled = false → 跳过
          · 打包模式且找不到 exe → 弹向导让用户指定
        """
        if not bool(self.config.get("game_path_check_enabled", True)):
            print("ℹ 游戏路径检查已关闭（game_path_check_enabled = false）",
                  flush=True)
            return True
        # 首次运行（config.toml 刚生成）也弹向导
        from .config_manager import JUST_CREATED_CONFIG
        is_first_run = bool(JUST_CREATED_CONFIG)
        import sys as _sys
        if not is_first_run and not getattr(_sys, "frozen", False):
            print("ℹ 源码模式：跳过游戏路径检查（打包后才启用）", flush=True)
            return True
        if is_first_run:
            print("ℹ 首次运行（config.toml 刚生成）→ 启用游戏路径检查",
                  flush=True)
        if not self.block_targets_config:
            return True
        if all(not t for t in self.block_targets_config):
            return True
        if self.valid_targets:
            return True
        draft_path = str(self.config.get("game_path_draft", "") or "")
        draft_sync = bool(self.config.get("game_path_draft_sync", True))
        try:
            from .game_path_dialog import GamePathDialog
            _hint = "Night of the Full Moon.exe"
            if (self.block_targets_config
                    and self.block_targets_config[0] not in ("", "default")):
                _hint = os.path.basename(self.block_targets_config[0])
            dlg = GamePathDialog(self.root, scale=self.scale,
                                  exe_hint=_hint,
                                  draft_path=draft_path,
                                  draft_sync=draft_sync)
            result = dlg.show()
        except Exception as e:
            print(f"游戏路径对话框失败: {e}", flush=True)
            return True
        if result is None:
            print("用户退出（未选路径）", flush=True)
            self.root.after(10, self.root.destroy)
            return False
        action = result.get("action", "save")

        # ---- 退出：完全无痕 ----
        if action == "exit" or result is None:
            self._rollback_config_if_first_run()
            print("用户退出（未保存任何设置）", flush=True)
            self.root.after(10, self.root.destroy)
            return False

        # ---- 整机断网模式 ----
        if action == "global_mode":
            update_config_field(["block_targets"], [])
            update_config_field(["launch_app"], "")
            update_config_field(["game_path_draft"], "")
            self.config, self.templates, self.state = load_config()
            self._apply_config_to_attributes()
            print("OK: 已切换为整机断网模式",
                  flush=True)
            return True

        # ---- 仅保存 / 保存并启动 ----
        path = result["path"]
        sync = result["sync_launch"]
        sync_path = result.get("sync_path") or path
        update_config_field(["block_targets"], [path])
        if sync:
            update_config_field(["launch_app"], sync_path)
        else:
            update_config_field(["launch_app"], "")
        update_config_field(["game_path_draft"], path)
        update_config_field(["game_path_draft_sync"], sync)
        self.config, self.templates, self.state = load_config()
        self._apply_config_to_attributes()
        print(f"OK 已保存游戏路径: {path}", flush=True)

        if action == "save":
            print("仅保存完成 → 退出工具", flush=True)
            self.root.after(10, self.root.destroy)
            return False

        # save_and_launch
        try:
            import subprocess
            subprocess.Popen([path], cwd=os.path.dirname(path))
            print(f"OK 已启动游戏：{path}", flush=True)
        except Exception as e:
            print(f"启动游戏失败: {e}", flush=True)
        return True