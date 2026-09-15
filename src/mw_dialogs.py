"""Mixin: 对话框 + 日志/文本窗口 + 命中历史"""
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
                              build_effective_rules,
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
from .roi_editor import RoiEditor
from .roi_overlay import RoiOverlay
from .template_watcher import TemplateWatcher
from .rule_manager import RuleManagerDialog


class MainWindowDialogs:
    def open_rule_manager(self, watch_was_enabled=None):
        """长按 👁：打开规则管理对话框（非阻塞）"""
        if not is_capture_available() or not is_ocr_available():
            messagebox.showerror("错误", "OCR 不可用"); return
        if self.is_global_mode or not self.valid_targets:
            messagebox.showerror("错误", "无有效断网目标"); return

        # 已打开则唤起（withdrawn 状态必须 deiconify 才能重新显示）
        if self._rule_dialog is not None:
            try:
                d = self._rule_dialog.dlg
                if d is not None and d.winfo_exists():
                    try:
                        if d.state() == 'withdrawn':
                            d.deiconify()
                    except Exception:
                        pass
                    # 强化置顶：切 topmost + 多次 lift 确保真的到最前
                    try:
                        d.attributes('-topmost', False)
                        d.attributes('-topmost', True)
                    except Exception:
                        pass
                    try:
                        d.lift()
                    except Exception:
                        pass
                    try:
                        d.focus_force()
                    except Exception:
                        pass
                    # 调度再抬一次，对抗其他窗口的抢占
                    try:
                        d.after(30, lambda w=d: self._force_front(w))
                    except Exception:
                        pass
                    print("📋 规则管理窗口已存在，唤起", flush=True)
                    return
            except Exception as e:
                print(f"唤起规则管理窗口失败: {e}", flush=True)
            self._rule_dialog = None

        if watch_was_enabled is None:
            watch_was_enabled = bool(self.img_watch_enabled
                                     or self.template_watcher is not None)
        target_exe = self.valid_targets[0]
        exe_name = os.path.basename(target_exe)
        pid = get_pid_by_exe_name(exe_name)
        if pid is None:
            messagebox.showerror("错误", "目标游戏未运行。"); return
        hwnd = get_hwnd_by_pid(pid)
        if not hwnd:
            messagebox.showerror("错误", "找不到游戏窗口。"); return
        if not is_window_visible(hwnd) or is_window_minimized(hwnd) \
                or is_window_cloaked(hwnd):
            messagebox.showwarning("提示", "请先把游戏窗口显示出来。"); return
        l, t, r, b = get_client_rect_screen(hwnd)
        cw, ch = r - l, b - t
        if cw <= 0 or ch <= 0:
            messagebox.showerror("错误", "客户区无效"); return

        size_key = f"{cw}x{ch}"
        rules, stats = build_effective_rules(self.templates, size_key)
        if stats['exact'] == 0:
            # 当前分辨率没有专属规则：用引导规则填充对话框，方便用户参考/编辑
            rules = {
                "whitelist": [dict(r) for r in PRESET_GUIDE_WHITELIST],
                "blacklist": [dict(r) for r in PRESET_GUIDE_BLACKLIST],
            }
            for k in ("whitelist", "blacklist"):
                for r in rules[k]:
                    r["_source"] = "exact"
            print(f"📋 分辨率 {size_key} 无专属规则，已载入引导模板"
                  f"（点应用会保存为本分辨率的规则）", flush=True)
        else:
            print(f"📋 规则：专用 {stats['exact']} 条（分辨率 {size_key}）",
                  flush=True)

        # 隐藏叠加框避免遮挡
        if self.roi_overlay is not None:
            self.roi_overlay.hide()
            self.roi_overlay = None

        # 取通用规则
        uni_rules = self.templates.get("universal", {})
        if not isinstance(uni_rules, dict):
            uni_rules = {}
        uni_rules = migrate_old_template(uni_rules)
        if not isinstance(uni_rules.get("whitelist"), list):
            uni_rules["whitelist"] = []
        if not isinstance(uni_rules.get("blacklist"), list):
            uni_rules["blacklist"] = []

        dlg = RuleManagerDialog(self, size_key, rules, scale=self.scale,
                                size=(self.rule_dialog_w, self.rule_dialog_h),
                                watch_was_enabled=watch_was_enabled,
                                source_summary=stats,
                                universal_rules=uni_rules,
                                on_apply=self._on_rule_applied,
                                on_cancel_cb=self._on_rule_cancelled)
        self._rule_dialog = dlg
        dlg.show(nonblocking=True)

    def _on_rule_applied(self, result):
        """规则管理点击应用后回调：
        1. 处理通用规则（universal 段）
        2. 只把 _source == 'exact' 的专用规则写回当前分辨率段
        """
        dlg = self._rule_dialog
        size_key = dlg.size_key if dlg else None
        was_enabled = dlg.watch_was_enabled if dlg else False
        self._rule_dialog = None
        if result is None or not size_key:
            return

        # ---- 处理通用规则 ----
        # 重要：主规则管理的"应用"永远不删通用规则。
        # 只有 _universal 里明确有内容时才更新；空的话保持不动。
        uni_result = result.get("_universal")
        print(f"\U0001f50d _on_rule_applied: templates keys="
              f"{sorted(self.templates.keys())}", flush=True)
        if isinstance(uni_result, dict):
            _wl_n = len(uni_result.get("whitelist", []) or [])
            _bl_n = len(uni_result.get("blacklist", []) or [])
            print(f"\U0001f50d _universal 传入：白名单 {_wl_n} 条 · "
                  f"黑名单 {_bl_n} 条", flush=True)
            clean_uni = {"whitelist": [], "blacklist": []}
            for kind in ("whitelist", "blacklist"):
                for r in uni_result.get(kind, []) or []:
                    if not isinstance(r, dict):
                        continue
                    rr = {k: v for k, v in r.items()
                          if not k.startswith("_")}
                    for k in ("x1", "y1", "x2", "y2"):
                        rr.pop(k, None)
                    clean_uni[kind].append(rr)
            if clean_uni["whitelist"] or clean_uni["blacklist"]:
                self.templates["universal"] = clean_uni
                print(f"\U0001f4be 更新通用规则："
                      f"白名单 {len(clean_uni['whitelist'])} 条 · "
                      f"黑名单 {len(clean_uni['blacklist'])} 条",
                      flush=True)
            else:
                # \u4e0d\u5220\uff0c\u4fdd\u6301\u539f\u6837
                print("\u2139\ufe0f _universal 传入为空，保持原有 universal 不动",
                      flush=True)
        else:
            print("\u2139\ufe0f result 里没有 _universal，保持现有 universal 不动",
                  flush=True)

        # ---- 再处理专用规则 ----
        to_save = {"whitelist": [], "blacklist": []}
        for kind in ("whitelist", "blacklist"):
            for r in result.get(kind, []) or []:
                if not isinstance(r, dict):
                    continue
                if r.get("_source", "exact") == "exact":
                    rr = {k: v for k, v in r.items() if k != "_source"}
                    to_save[kind].append(rr)
        if to_save["whitelist"] or to_save["blacklist"]:
            self.templates[size_key] = to_save
            print(f"\U0001f4be 写入专用规则到 {size_key}："
                  f"白名单 {len(to_save['whitelist'])} 条 · "
                  f"黑名单 {len(to_save['blacklist'])} 条", flush=True)
        else:
            if size_key in self.templates:
                del self.templates[size_key]
            print(f"\U0001f4be {size_key} 无专用规则，移除该段", flush=True)

        # ---- 保存到文件 ----
        ok = save_templates(self.templates)
        if ok:
            print(f"\u2705 规则已保存到 templates.toml", flush=True)
        else:
            print(f"\u274c 保存失败（templates.toml 写入异常）", flush=True)

        # ---- 恢复监控 ----
        wl_n = len(to_save.get("whitelist", []))
        if was_enabled and wl_n > 0:
            self.img_watch_enabled = True
            update_config_field(["img_watch", "enabled"], True)
            self._refresh_imgwatch_button()
            if self.template_watcher is None:
                self.start_image_watch()
            else:
                self.stop_image_watch()
                self.start_image_watch()
        else:
            self.img_watch_enabled = False
            update_config_field(["img_watch", "enabled"], False)
            self._refresh_imgwatch_button()
            if self.template_watcher is not None:
                self.stop_image_watch()


    def _on_rule_cancelled(self):
        """规则管理点击取消后回调：恢复原监控状态"""
        dlg = self._rule_dialog
        was_enabled = dlg.watch_was_enabled if dlg else False
        self._rule_dialog = None
        print("ℹ️ 规则管理取消", flush=True)
        if was_enabled and not self.img_watch_enabled:
            self.img_watch_enabled = True
            update_config_field(["img_watch", "enabled"], True)
            self._refresh_imgwatch_button()
            if self.template_watcher is None:
                self.start_image_watch()

    def update_scan_all(self, value):
        """由规则管理对话框回调：保存全量扫描开关"""
        update_config_field(["img_watch", "scan_all"], bool(value))
        iw = self.config.get("img_watch", {})
        iw["scan_all"] = bool(value)
        self.config["img_watch"] = iw
        print(f"👁 全量扫描模式：{'开' if value else '关'}", flush=True)

    def enter_region_select_mode_with_callback(self, on_done, hint_text="",
                                                on_done_restore=None):
        """供规则管理器调用：进入框选模式，回调返回 ROI"""
        if self.is_global_mode or not self.valid_targets:
            if on_done_restore: on_done_restore()
            return
        target_exe = self.valid_targets[0]
        exe_name = os.path.basename(target_exe)
        pid = get_pid_by_exe_name(exe_name)
        if pid is None:
            if on_done_restore: on_done_restore()
            return
        hwnd = get_hwnd_by_pid(pid)
        if not hwnd:
            if on_done_restore: on_done_restore()
            return
        if not is_window_visible(hwnd) or is_window_minimized(hwnd) \
                or is_window_cloaked(hwnd):
            if on_done_restore: on_done_restore()
            messagebox.showwarning("提示", "请先把游戏窗口显示出来。")
            return
        l, t, r, b = get_client_rect_screen(hwnd)
        cw, ch = r - l, b - t
        if cw <= 0 or ch <= 0:
            if on_done_restore: on_done_restore()
            return
        self._select_hwnd = hwnd
        self._select_client_rect = (l, t, cw, ch)
        self._select_on_done = on_done
        self._select_on_restore = on_done_restore

        self._region_selector = RegionSelector(
            self.root, hint_text=hint_text or "拖拽框选 · 点确认提交 · ESC 取消",
            on_done=self._on_region_selected_for_callback,
            on_cancel=self._on_region_cancelled_for_callback,
            scale=self.scale)
        self._region_selector.show()

    def edit_roi_with_callback(self, roi, on_done, on_restore=None,
                                hint_text=""):
        """在游戏画面上编辑现有 ROI（拖动/缩放）。回调返回新 ROI。"""
        if self.is_global_mode or not self.valid_targets:
            if on_restore: on_restore()
            return
        target_exe = self.valid_targets[0]
        exe_name = os.path.basename(target_exe)
        pid = get_pid_by_exe_name(exe_name)
        if pid is None:
            if on_restore: on_restore()
            messagebox.showwarning("提示", "目标游戏未运行。"); return
        hwnd = get_hwnd_by_pid(pid)
        if not hwnd:
            if on_restore: on_restore()
            messagebox.showwarning("提示", "找不到游戏窗口。"); return
        if (not is_window_visible(hwnd) or is_window_minimized(hwnd)
                or is_window_cloaked(hwnd)):
            if on_restore: on_restore()
            messagebox.showwarning("提示", "请先把游戏窗口显示出来。"); return
        l, t, r, b = get_client_rect_screen(hwnd)
        cw, ch = r - l, b - t
        if cw <= 0 or ch <= 0:
            if on_restore: on_restore()
            messagebox.showerror("错误", "客户区无效"); return

        self._roi_editor = RoiEditor(
            self.root, hwnd, (l, t, cw, ch), roi,
            hint_text=hint_text or "拖动框内移动 · 拖四角缩放 · Enter 确认 · ESC 取消",
            on_done=on_done,
            on_cancel=on_restore,
            scale=self.scale)

    def _on_region_selected_for_callback(self, left, top, right, bottom):
        if not self._select_client_rect:
            if self._select_on_restore: self._select_on_restore()
            return
        l, t, cw, ch = self._select_client_rect
        x1 = max(0.0, min(1.0, (left - l) / cw))
        y1 = max(0.0, min(1.0, (top - t) / ch))
        x2 = max(0.0, min(1.0, (right - l) / cw))
        y2 = max(0.0, min(1.0, (bottom - t) / ch))
        if x1 > x2: x1, x2 = x2, x1
        if y1 > y2: y1, y2 = y2, y1
        roi = (round(x1, 4), round(y1, 4), round(x2, 4), round(y2, 4))
        print(f"📷 已框选：x[{x1:.4f},{x2:.4f}] y[{y1:.4f},{y2:.4f}]", flush=True)
        if self._select_on_done:
            self._select_on_done(roi)
        if self._select_on_restore:
            self._select_on_restore()
        self._select_on_done = None
        self._select_on_restore = None

    def _on_region_cancelled_for_callback(self):
        print("ℹ️ 用户取消了框选", flush=True)
        if self._select_on_restore:
            self._select_on_restore()
        self._select_on_done = None
        self._select_on_restore = None

    def _collect_own_hwnds(self):
        """收集本工具所有顶层窗口的 hwnd，用于遮挡检测排除自身。

        通过枚举本进程的所有顶层窗口实现，新增窗口自动包含，
        避免手工列举遗漏（如命中历史、规则管理、音量设置、ROI 编辑器等）。
        """
        hwnds = []
        # 主方式：枚举本进程所有顶层窗口
        try:
            import os as _os
            from .win_utils import get_top_level_hwnds_by_pid
            hwnds = get_top_level_hwnds_by_pid(_os.getpid())
        except Exception as e:
            print(f"枚举本进程窗口失败，退回手工收集: {e}", flush=True)

        # 兜底：手工补充已知窗口
        def _add(widget):
            try:
                if widget is None:
                    return
                if hasattr(widget, "winfo_exists") and not widget.winfo_exists():
                    return
                wid = widget.winfo_id()
                top = _user32.GetAncestor(wid, GA_ROOT) or wid
                if top and top not in hwnds:
                    hwnds.append(top)
            except Exception:
                pass

        _add(self.root)
        _add(self.log_window)
        _add(self.time_dialog)
        _add(self.md_window)
        try:
            _add(getattr(self, "hit_history_window", None))
        except Exception:
            pass
        # 规则管理对话框
        try:
            rd = getattr(self, "_rule_dialog", None)
            if rd is not None:
                _add(rd.dlg)
                _add(getattr(rd, "_edit_dlg", None))
                _add(getattr(rd, "_ocr_dlg", None))
        except Exception:
            pass
        # 音量向导 / 音量设置
        try:
            vw = getattr(self, "_volume_wizard_dlg", None)
            if vw is not None:
                _add(vw.dlg)
        except Exception:
            pass
        try:
            vs = getattr(self, "_volume_settings_dlg", None)
            if vs is not None:
                _add(vs.dlg)
        except Exception:
            pass
        # ROI 编辑器
        try:
            re_ = getattr(self, "_roi_editor", None)
            if re_ is not None:
                _add(re_.top)
        except Exception:
            pass
        # ROI 调试叠加框
        try:
            if self.roi_overlay is not None and self.roi_overlay.hwnd:
                if self.roi_overlay.hwnd not in hwnds:
                    hwnds.append(self.roi_overlay.hwnd)
        except Exception:
            pass
        # 框选器
        try:
            if self._region_selector is not None:
                _add(self._region_selector.mask_top)
                _add(self._region_selector.ui_top)
        except Exception:
            pass
        return list(set(hwnds))
    def _refresh_hit_history_view(self):
        """刷新命中历史列表（智能粘连：只在原本到底时才滚到最新）"""
        if self._hit_history_listbox is None:
            return
        try:
            if not self._hit_history_listbox.winfo_exists():
                return
        except Exception:
            return
        lb = self._hit_history_listbox
        # 先记录是否在底部
        try:
            at_bottom = lb.yview()[1] >= 0.999
        except Exception:
            at_bottom = True
        try:
            lb.configure(state='normal')
            lb.delete(0, tk.END)
            for entry in self.hit_history:
                try:
                    if isinstance(entry, (list, tuple)):
                        n = len(entry)
                        if n >= 4:
                            ts, kind, name = entry[0], entry[1], entry[2]
                            text = entry[3]
                        elif n == 3:
                            ts, kind, name = entry[0], entry[1], entry[2]
                            text = ""
                        elif n == 2:
                            ts, name = entry[0], entry[1]
                            kind = "white"
                            text = ""
                        else:
                            continue
                    else:
                        continue
                except Exception:
                    continue
                tag = "白名单" if kind == "white" else "黑名单"
                if text:
                    line = f'{ts}  [{tag}]  {name}  ->  "{text}"'
                else:
                    line = f"{ts}  [{tag}]  {name}"
                lb.insert(tk.END, line)
                idx = lb.size() - 1
                lb.itemconfig(
                    idx, fg='#2E7D32' if kind == 'white' else '#1565C0')
            # 只在用户原本就在底部时才滚到最新
            if at_bottom:
                try:
                    lb.see(tk.END)
                except Exception:
                    pass
            lb.configure(state='disabled')
        except Exception as e:
            print(f"刷新命中历史失败: {e}", flush=True)


    def _open_hit_history(self):
        """打开命中历史窗口"""
        if self.hit_history_window is not None \
                and self.hit_history_window.winfo_exists():
            try:
                self.hit_history_window.deiconify()
                self.hit_history_window.lift()
            except Exception:
                pass
            self._refresh_hit_history_view()
            return
        S = self.scale
        top = tk.Toplevel(self.root)
        top.title("📊 规则命中历史")
        top.attributes('-topmost', True)
        w = int(440 * S); h = int(380 * S)
        top.geometry(f"{w}x{h}")
        top.configure(bg='#FAFAFA')
        self.hit_history_window = top

        f_text = ("Consolas", -max(11, int(12 * S)))
        tk.Label(top, text="📊 规则命中历史（最近 20 条）",
                 bg='#FAFAFA', fg='#1976D2',
                 font=("微软雅黑", -max(12, int(13 * S)), "bold")
                 ).pack(pady=int(6 * S))
        tk.Label(top, text="绿=白名单命中（触发断网） / 蓝=黑名单命中（抑制）",
                 bg='#FAFAFA', fg='#666',
                 font=("微软雅黑", -max(10, int(11 * S)))
                 ).pack()
        frame = tk.Frame(top, bg='#FAFAFA')
        frame.pack(fill=tk.BOTH, expand=True, padx=int(8 * S),
                   pady=int(6 * S))
        sb = tk.Scrollbar(frame)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        lb = tk.Listbox(frame, font=f_text, yscrollcommand=sb.set,
                        bg='white', relief='solid', bd=1,
                        activestyle='none')
        lb.pack(fill=tk.BOTH, expand=True)
        sb.config(command=lb.yview)
        self._hit_history_listbox = lb
        btn_frame = tk.Frame(top, bg='#FAFAFA')
        btn_frame.pack(fill=tk.X, padx=int(8 * S), pady=(0, int(8 * S)))
        tk.Button(btn_frame, text="清空记录",
                  command=self._clear_hit_history,
                  bg='#FFEBEE', fg='#C62828', relief='flat',
                  font=("微软雅黑", -max(10, int(11 * S))),
                  padx=int(10 * S), pady=int(4 * S)
                  ).pack(side=tk.LEFT)
        tk.Button(btn_frame, text="关闭",
                  command=self.hit_history_window.withdraw,
                  bg='#E0E0E0', fg='#333', relief='flat',
                  font=("微软雅黑", -max(10, int(11 * S))),
                  padx=int(10 * S), pady=int(4 * S)
                  ).pack(side=tk.RIGHT)

        def on_close():
            try: top.withdraw()
            except Exception: pass
        top.protocol("WM_DELETE_WINDOW", on_close)
        self._refresh_hit_history_view()

    def _clear_hit_history(self):
        self.hit_history.clear()
        self._refresh_hit_history_view()

    def toggle_time_dialog(self):
        if self.time_dialog is not None and self.time_dialog.winfo_exists():
            self.save_time_from_dialog()
            self.time_dialog.destroy()
            self.time_dialog = None
            self.time_entry = None
            self.ocr_time_entry = None
            self.overlay_var = None
            self.highlight_var = None
            return
        S = self.scale
        dlg = tk.Toplevel(self.root)
        dlg.overrideredirect(True)
        dlg.attributes('-topmost', True)
        dlg.configure(bg='#E0E0E0')

        inner = tk.Frame(dlg, bg='white')
        inner.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        pad = max(8, int(10 * S))
        f_title = ("微软雅黑", -max(12, int(13 * S)), "bold")
        f_label = ("微软雅黑", -max(10, int(11 * S)))
        f_hint = ("微软雅黑", -max(9, int(10 * S)))
        f_entry = ("Consolas", -max(10, int(11 * S)))
        f_btn = ("微软雅黑", -max(10, int(11 * S)))

        # 标题栏
        title_bar = tk.Frame(inner, bg='#1976D2')
        title_bar.pack(fill=tk.X)
        tk.Label(title_bar, text="⏱  断网设置", bg='#1976D2', fg='white',
                 font=f_title, anchor='w'
                 ).pack(side=tk.LEFT, padx=int(10 * S), pady=int(5 * S))

        # 内容
        body = tk.Frame(inner, bg='white')
        body.pack(fill=tk.BOTH, expand=True, padx=pad, pady=pad)

        # 手动点击
        tk.Label(body, text="手动点击断网秒数（1-1000）",
                 bg='white', font=f_label, fg='#333', anchor='w'
                 ).pack(fill=tk.X)
        r1 = tk.Frame(body, bg='white')
        r1.pack(fill=tk.X, pady=(1, int(6 * S)))
        entry = tk.Entry(r1, width=6, font=f_entry, relief='solid', bd=1)
        entry.pack(side=tk.LEFT)
        tk.Label(r1, text="  秒（点击中间大块时生效）",
                 bg='white', font=f_hint, fg='#888').pack(side=tk.LEFT)
        entry.insert(0, str(self.block_time))
        entry.focus_set()
        entry.select_range(0, tk.END)

        # OCR 默认
        tk.Label(body, text="OCR 命中默认断网秒数（1-1000）",
                 bg='white', font=f_label, fg='#333', anchor='w'
                 ).pack(fill=tk.X)
        r2 = tk.Frame(body, bg='white')
        r2.pack(fill=tk.X, pady=(1, int(6 * S)))
        ocr_entry = tk.Entry(r2, width=6, font=f_entry, relief='solid', bd=1)
        ocr_entry.pack(side=tk.LEFT)
        tk.Label(r2, text="  秒（规则留空时用此值）",
                 bg='white', font=f_hint, fg='#888').pack(side=tk.LEFT)
        try:
            _ocr_bt = int(self.config.get("ocr_block_time", 1))
        except Exception:
            _ocr_bt = 1
        ocr_entry.insert(0, str(_ocr_bt))

        # 分隔线
        tk.Frame(body, bg='#E0E0E0', height=1).pack(
            fill=tk.X, pady=int(6 * S))

        # 调试显示
        tk.Label(body, text="调试显示",
                 bg='white', font=f_label, fg='#333', anchor='w'
                 ).pack(fill=tk.X, pady=(0, 2))
        iw = self.config.get("img_watch", {})
        self.overlay_var = tk.BooleanVar(value=bool(iw.get("debug_overlay", True)))
        tk.Checkbutton(body, text="① 显示调试框（常亮 ROI 边框）",
                       variable=self.overlay_var,
                       bg='white', activebackground='white',
                       selectcolor='white', font=f_label,
                       anchor='w', bd=0, highlightthickness=0
                       ).pack(fill=tk.X)
        self.highlight_var = tk.BooleanVar(
            value=bool(iw.get("highlight_on_hit", True)))
        tk.Checkbutton(body, text="② 命中时闪烁提示",
                       variable=self.highlight_var,
                       bg='white', activebackground='white',
                       selectcolor='white', font=f_label,
                       anchor='w', bd=0, highlightthickness=0
                       ).pack(fill=tk.X)

        tk.Label(body,
                 text="提示：两个调试开关独立；不想看到闪烁就取消勾选②",
                 bg='white', font=f_hint, fg='#999',
                 anchor='w', justify='left', wraplength=int(320 * S)
                 ).pack(fill=tk.X, pady=(int(4 * S), 0))

        # 底部按钮
        btn_frame = tk.Frame(inner, bg='#FAFAFA')
        btn_frame.pack(fill=tk.X, side=tk.BOTTOM)
        tk.Frame(btn_frame, bg='#E0E0E0', height=1).pack(fill=tk.X)
        btn_inner = tk.Frame(btn_frame, bg='#FAFAFA')
        btn_inner.pack(fill=tk.X, padx=pad, pady=int(6 * S))

        self.time_dialog = dlg
        self.time_entry = entry
        self.ocr_time_entry = ocr_entry

        def do_save_close():
            self.save_time_from_dialog()
            dlg.destroy()
            self.time_dialog = None
            self.time_entry = None
            self.ocr_time_entry = None
            self.overlay_var = None
            self.highlight_var = None

        def do_cancel_close():
            dlg.destroy()
            self.time_dialog = None
            self.time_entry = None
            self.ocr_time_entry = None
            self.overlay_var = None
            self.highlight_var = None

        tk.Button(btn_inner, text="取消", command=do_cancel_close,
                  font=f_btn, width=5, relief='flat',
                  bg='#E0E0E0', fg='#333',
                  activebackground='#D0D0D0'
                  ).pack(side=tk.RIGHT, padx=(int(4 * S), 0))
        tk.Button(btn_inner, text="✓ 确定", command=do_save_close,
                  font=f_btn, width=7, relief='flat',
                  bg='#4CAF50', fg='white',
                  activebackground='#388E3C'
                  ).pack(side=tk.RIGHT)

        # ---- 自动计算合适尺寸（内容紧凑） ----
        dlg.update_idletasks()
        w = dlg.winfo_reqwidth() + int(8 * S)
        h = dlg.winfo_reqheight() + int(4 * S)
        x, y = self.calculate_dialog_position(w, h)
        dlg.geometry(f"{w}x{h}+{x}+{y}")


    def calculate_dialog_position(self, dlg_w, dlg_h):
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        main_x = self.root.winfo_x()
        main_y = self.root.winfo_y()
        main_w = self.w
        margin = int(5 * self.scale)
        left_space = main_x
        right_space = sw - (main_x + main_w)
        if left_space >= dlg_w + margin:
            x = main_x - dlg_w - margin
        elif right_space >= dlg_w + margin:
            x = main_x + main_w + margin
        else:
            x = max(0, min(sw - dlg_w, main_x + main_w // 2 - dlg_w // 2))
        y = main_y
        if y + dlg_h > sh: y = sh - dlg_h - margin
        if y < 0: y = margin
        return x, y

    def save_time_from_dialog(self):
        # ---- 手动点击秒数 ----
        if self.time_entry is not None:
            s = self.time_entry.get().strip()
            if s.isdigit():
                t = int(s)
                if 1 <= t <= 1000:
                    self.block_time = t
                    update_config_field(["block_time"], t)
                    print(f"✅ 手动点击断网秒数 = {t} 秒", flush=True)
                else:
                    print(f"⚠ 手动断网秒数 {t} 超出范围 1-1000，忽略", flush=True)
        # ---- OCR 命中默认秒数 ----
        ocr_entry = getattr(self, "ocr_time_entry", None)
        if ocr_entry is not None:
            s = ocr_entry.get().strip()
            if s.isdigit():
                t = int(s)
                if 1 <= t <= 1000:
                    self.ocr_block_time = t
                    update_config_field(["ocr_block_time"], t)
                    self.config["ocr_block_time"] = t
                    print(f"✅ OCR 命中默认断网秒数 = {t} 秒", flush=True)
                else:
                    print(f"⚠ OCR 断网秒数 {t} 超出范围 1-1000，忽略", flush=True)
        # ---- 调试显示开关 ----
        if self.overlay_var is not None:
            try: new_overlay = bool(self.overlay_var.get())
            except Exception: new_overlay = None
            if new_overlay is not None:
                iw = self.config.get("img_watch", {})
                old = bool(iw.get("debug_overlay", True))
                if old != new_overlay:
                    update_config_field(["img_watch", "debug_overlay"], new_overlay)
                    iw["debug_overlay"] = new_overlay
                    self.config["img_watch"] = iw
                    if self.img_watch_enabled and self.template_watcher is not None:
                        self.stop_image_watch()
                        self.start_image_watch()
        if getattr(self, "highlight_var", None) is not None:
            try: new_hl = bool(self.highlight_var.get())
            except Exception: new_hl = None
            if new_hl is not None:
                iw = self.config.get("img_watch", {})
                old_hl = bool(iw.get("highlight_on_hit", True))
                if old_hl != new_hl:
                    update_config_field(["img_watch", "highlight_on_hit"], new_hl)
                    iw["highlight_on_hit"] = new_hl
                    self.config["img_watch"] = iw


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
        self.log_window.title("日志")
        self.log_window.geometry(
            f"{int(self.log_window_w * self.scale)}x{int(self.log_window_h * self.scale)}")
        self.log_window.protocol("WM_DELETE_WINDOW", self.hide_log_window)
        frame = tk.Frame(self.log_window)
        frame.pack(fill=tk.BOTH, expand=True)
        scroll = tk.Scrollbar(frame)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text = tk.Text(frame, wrap=tk.WORD,
                                font=("Consolas", self.small_font),
                                yscrollcommand=scroll.set)
        self.log_text.pack(fill=tk.BOTH, expand=True)
        scroll.config(command=self.log_text.yview)
        log_btn_row = tk.Frame(self.log_window)
        log_btn_row.pack(pady=int(2 * self.scale))
        tk.Button(log_btn_row, text="清空显示",
                  command=self.clear_log_display,
                  font=("", self.small_font)).pack(side=tk.LEFT,
                                                   padx=int(2 * self.scale))
        tk.Button(log_btn_row, text="📊 命中历史",
                  command=self._open_hit_history,
                  font=("", self.small_font),
                  bg='#E3F2FD', fg='#0D47A1',
                  relief='flat').pack(side=tk.LEFT,
                                      padx=int(2 * self.scale))
        self._attach_log_view()

    def _attach_log_view(self):
        if not hasattr(self, "log_text") or self.log_text is None: return
        try:
            self.log_text.configure(state="normal")
            self.log_text.delete("1.0", "end")
            self.log_text.insert("end", LOG_BUFFER.snapshot())
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        except Exception: pass
        self._detach_log_view()
        self._log_handler = LogTextHandler(self.log_text)
        LOG_BUFFER.add_listener(self._log_handler)

    def _detach_log_view(self):
        if self._log_handler is not None:
            LOG_BUFFER.remove_listener(self._log_handler)
            self._log_handler = None

    def hide_log_window(self):
        self._detach_log_view()
        if self.log_window: self.log_window.withdraw()

    def clear_log_display(self):
        if hasattr(self, "log_text") and self.log_text:
            try:
                self.log_text.configure(state="normal")
                self.log_text.delete("1.0", "end")
                self.log_text.configure(state="disabled")
            except Exception: pass

    def toggle_md_window(self):
        from .log_buffer import LOG_BUFFER as _LB
        from .config_manager import CONFIG_DIR as _CFG_DIR
        _ = _LB, _CFG_DIR
        md_file_external = os.path.join(SCRIPT_DIR, "文本.md")
        md_file_builtin = os.path.join(SCRIPT_DIR, "内置文本.md")
        if os.path.exists(md_file_external): md_file = md_file_external
        elif os.path.exists(md_file_builtin): md_file = md_file_builtin
        else: return
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
            self.md_window.geometry(
                f"{int(width * self.scale)}x{int(height * self.scale)}+{x}+{y}")
        else:
            self.md_window.geometry(
                f"{int(width * self.scale)}x{int(height * self.scale)}")
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
            messagebox.showerror("错误", f"无法读取: {e}")

    def save_md_state(self):
        if self.md_window is not None and self.md_window.winfo_exists():
            self.state["md_scroll_pos"] = self.md_text.yview()[0] \
                if self.md_text else 0.0
            self.state["md_window_x"] = self.md_window.winfo_x()
            self.state["md_window_y"] = self.md_window.winfo_y()
            self.state["md_window_width"] = self.md_window.winfo_width()
            self.state["md_window_height"] = self.md_window.winfo_height()
            save_state(self.state)

    def hide_md_window(self):
        self.save_md_state()
        if self.md_window: self.md_window.withdraw()

    def _open_volume_settings(self):
        """长按 🔊：打开音量控制设置对话框（单例）"""
        # 已存在则 lift 到前面
        if getattr(self, "_volume_settings_dlg", None) is not None:
            try:
                d = self._volume_settings_dlg.dlg
                if d is not None and d.winfo_exists():
                    d.lift()
                    d.focus_force()
                    return
            except Exception:
                pass
            self._volume_settings_dlg = None

        from .volume_settings import VolumeSettingsDialog
        dlg = VolumeSettingsDialog(self, scale=self.scale)
        self._volume_settings_dlg = dlg
        result = dlg.show()
        self._volume_settings_dlg = None
        if result is None:
            return
        ok1 = update_config_field(["sound_volume_view_path"],
                                  result["sound_volume_view_path"])
        ok2 = update_config_field(["volume_mute_value"],
                                  result["volume_mute_value"])
        ok3 = update_config_field(
            ["img_watch", "auto_mute_when_hidden"],
            result.get("auto_mute_when_hidden", False))
        self.config["sound_volume_view_path"] = result["sound_volume_view_path"]
        self.config["volume_mute_value"] = result["volume_mute_value"]
        iw = self.config.get("img_watch", {})
        iw["auto_mute_when_hidden"] = bool(
            result.get("auto_mute_when_hidden", False))
        self.config["img_watch"] = iw
        self.sv_path = resolve_sv_path(result["sound_volume_view_path"])
        self.volume_mute_value = result["volume_mute_value"]
        self.auto_mute_when_hidden = bool(
            result.get("auto_mute_when_hidden", False))
        try: self._refresh_volume_button()
        except Exception: pass
        # 如果新开了自动静音但可见性监控线程未启动，现在启动
        if self.auto_mute_when_hidden:
            try: self.start_visibility_mute_monitor()
            except Exception as e:
                print(f"启动可见性静音监控失败: {e}", flush=True)
        else:
            # 关掉时，如果当前处于自动静音状态，恢复音量
            try:
                if getattr(self, "auto_muted_by_hide", False):
                    self._auto_unmute_for_hide()
            except Exception:
                pass
        if ok1 and ok2 and ok3:
            print(f"✅ 音量设置已保存：path={result['sound_volume_view_path']!r} "
                  f"mute={result['volume_mute_value']} "
                  f"auto_mute={self.auto_mute_when_hidden}", flush=True)
        else:
            print(f"⚠ 音量设置已应用到内存（config.toml 部分写入失败）"
                  f"：path={result['sound_volume_view_path']!r} "
                  f"mute={result['volume_mute_value']} "
                  f"auto_mute={self.auto_mute_when_hidden}", flush=True)
        # 提示用户路径是否可用
        if result["sound_volume_view_path"] and not os.path.exists(
                result["sound_volume_view_path"]):
            messagebox.showwarning(
                "提示",
                f"路径找不到：\n{result['sound_volume_view_path']}\n\n"
                "请确认 SoundVolumeView.exe 是否存在。",
                parent=self.root)

    def _open_md_settings(self):
        from .md_settings import MdSettingsDialog
        dlg = MdSettingsDialog(self, scale=self.scale)
        result = dlg.show()
        if result is None:
            return
        ui = self.config.get("ui", {})
        ui["md_window"] = result
        self.config["ui"] = ui
        for k, v in result.items():
            try: update_config_field(["ui", "md_window", k], v)
            except Exception: pass
        print(f"✅ 文本窗口设置已保存：{result}", flush=True)
        self.md_default_w = result["width"]
        self.md_default_h = result["height"]
        self.md_font_family = result["font_family"]
        self.md_font_size = result["font_size"]
        self.md_font_color = result["font_color"]
        self.md_bg_color = result["bg_color"]
        # 若当前 md_window 开着，重建以应用新配置
        if self.md_window is not None and self.md_window.winfo_exists():
            try: self.md_window.destroy()
            except Exception: pass
            self.md_window = None
            self.md_text = None
            self.toggle_md_window()
