"""规则管理对话框：黑名单优先（抑制），白名单后扫（触发）"""
import tkinter as tk
from tkinter import messagebox
import re

from .config_manager import deep_copy, rule_has_roi, ensure_preset_rules
from .ocr_engine import ocr_recognize, is_ocr_available
from .capture import capture_roi_bgra
from .win_utils import (get_pid_by_exe_name, get_hwnd_by_pid, is_window_alive,
                        is_window_visible, is_window_minimized, is_window_cloaked,
                        get_client_rect_screen, _user32, GA_ROOT,
                        set_window_capture_exclude)


class RuleManagerDialog:
    def __init__(self, parent_app, size_key, rules, scale=1.0, size=(720, 640),
                 watch_was_enabled=False, source_summary=None,
                 available_templates=None, source_info=None,
                 universal_rules=None,
                 on_apply=None, on_cancel_cb=None):
        self.app = parent_app
        self.parent = parent_app.root
        self.size_key = size_key
        self.rules = deep_copy(rules)
        self.scale = scale
        self.dialog_size = size
        self.watch_was_enabled = bool(watch_was_enabled)
        self.source_summary = source_summary or {"exact": 0, "default": 0}
        self.available_templates = available_templates or {}
        self.source_info = source_info or {"kind": "user", "from_size": size_key}
        # 通用规则（黑白名单分开存）
        if not isinstance(universal_rules, dict):
            universal_rules = {}
        self.universal_rules = deep_copy(universal_rules)
        if not isinstance(self.universal_rules.get("whitelist"), list):
            self.universal_rules["whitelist"] = []
        if not isinstance(self.universal_rules.get("blacklist"), list):
            self.universal_rules["blacklist"] = []
        self.on_apply_cb = on_apply
        self.on_cancel_cb = on_cancel_cb
        self.initial_scan_all = bool(
            parent_app.config.get("img_watch", {}).get("scan_all", False))

        if "whitelist" not in self.rules or not isinstance(self.rules["whitelist"], list):
            self.rules["whitelist"] = []
        if "blacklist" not in self.rules or not isinstance(self.rules["blacklist"], list):
            self.rules["blacklist"] = []
        ensure_preset_rules(self.rules)

        self.result = None
        self.dlg = None
        self.scan_all_var = None
        self._edit_dlg = None
        self._ocr_dlg = None
        self._build()

    def _build(self):
        S = self.scale
        w = int(self.dialog_size[0] * S)
        h = int(self.dialog_size[1] * S)
        self.dlg = tk.Toplevel(self.parent)
        _title_status = " · 监控已暂停" if self.watch_was_enabled else ""
        self.dlg.title(f"规则管理 - {self.size_key}{_title_status}")
        self.dlg.attributes('-topmost', True)
        self.dlg.configure(bg='#FAFAFA')
        # 不 grab_set，允许操作主窗口；同时允许拖动改变大小
        self.dlg.resizable(True, True)
        self.dlg.update_idletasks()
        sw = self.dlg.winfo_screenwidth()
        sh = self.dlg.winfo_screenheight()
        self.dlg.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

        pad = int(12 * S)
        f_title = ("微软雅黑", -max(14, int(16 * S)), "bold")
        f_small = ("微软雅黑", -max(10, int(11 * S)))
        f_btn = ("微软雅黑", -max(11, int(12 * S)))

        tk.Label(self.dlg, text=f"📋 规则管理（{self.size_key}）", bg='#FAFAFA',
                 font=f_title, fg='#1976D2').pack(pady=(pad, int(2 * S)))
        tk.Label(self.dlg,
                 text="按顺序扫描：先黑名单（命中即抑制），后白名单（命中即触发）",
                 bg='#FAFAFA', font=f_small, fg='#666').pack(pady=(0, int(4 * S)))

        # ---- 来源卡片（明显的规则来源说明） ----
        _kind = getattr(self, "source_info", {}).get("kind", "unknown")
        _frm = getattr(self, "source_info", {}).get("from_size", "")
        _n_wl = len(self.rules.get("whitelist", []) or [])
        _n_bl = len(self.rules.get("blacklist", []) or [])
        if _kind == "user":
            _bg, _bd, _fg = "#E8F5E9", "#43A047", "#1B5E20"
            _icon = "[U]"
            _title = f"用户手动保存的规则（{self.size_key}）"
            _desc = "你自己在规则管理里保存的，编辑后会覆盖它"
        elif _kind == "builtin":
            _bg, _bd, _fg = "#E3F2FD", "#1E88E5", "#0D47A1"
            _icon = "[B]"
            _title = f"程序内置模板（{self.size_key}）"
            _desc = "工具自带的，你没改过；改了会变成「用户规则」"
        elif _kind == "fallback":
            _bg, _bd, _fg = "#FFF3E0", "#FB8C00", "#E65100"
            _icon = "[F]"
            _title = f"通用兜底（用 {_frm} 顶替）"
            _desc = f"当前 {self.size_key} 没专属规则，自动用 {_frm} 的规则"
        else:
            _bg, _bd, _fg = "#EEEEEE", "#9E9E9E", "#424242"
            _icon = "[?]"
            _title = "规则来源未知"
            _desc = ""
        _card = tk.Frame(self.dlg, bg=_bg,
                         highlightbackground=_bd, highlightthickness=2)
        _card.pack(fill=tk.X, padx=pad, pady=(0, int(6 * S)))
        _ci = tk.Frame(_card, bg=_bg)
        _ci.pack(fill=tk.X, padx=int(10 * S), pady=int(7 * S))
        tk.Label(_ci, text=f"{_icon}  {_title}",
                 bg=_bg, fg=_fg,
                 font=("微软雅黑", -max(11, int(13 * S)), "bold"),
                 anchor='w').pack(fill=tk.X)
        if _desc:
            tk.Label(_ci, text=_desc, bg=_bg, fg=_fg,
                     font=("微软雅黑", -max(9, int(10 * S))),
                     anchor='w', justify='left'
                     ).pack(fill=tk.X, pady=(1, 0))
        tk.Label(_ci,
                 text=f"共 {_n_wl + _n_bl} 条  ·  白名单 {_n_wl}  ·  黑名单 {_n_bl}",
                 bg=_bg, fg=_fg,
                 font=("微软雅黑", -max(9, int(10 * S))),
                 anchor='w').pack(fill=tk.X, pady=(1, 0))
        if self.watch_was_enabled:
            _pb = tk.Frame(self.dlg, bg="#FFF3E0",
                           highlightbackground="#FFB74D",
                           highlightthickness=1)
            _pb.pack(fill=tk.X, padx=pad, pady=(0, int(6 * S)))
            tk.Label(_pb, text="监控已暂停（本次编辑不会触发断网）",
                     bg="#FFF3E0", fg="#E65100",
                     font=("微软雅黑", -max(10, int(11 * S)), "bold"),
                     anchor='w').pack(fill=tk.X, padx=int(8 * S),
                                       pady=int(3 * S))
        scan_frame = tk.Frame(self.dlg, bg='#FFF3E0',
                              highlightbackground='#FFB74D', highlightthickness=1)
        scan_frame.pack(fill=tk.X, padx=pad, pady=(0, int(6 * S)))
        self.scan_all_var = tk.BooleanVar(value=self.initial_scan_all)
        tk.Checkbutton(
            scan_frame,
            text="全量扫描（测试模式）：无论是否命中，扫完全部规则（慢）",
            variable=self.scan_all_var,
            bg='#FFF3E0', fg='#E65100',
            activebackground='#FFF3E0', selectcolor='#FFF3E0',
            font=("微软雅黑", -max(10, int(11 * S)), "bold"),
            anchor='w'
        ).pack(fill=tk.X, padx=int(8 * S), pady=int(4 * S))

        container = tk.Frame(self.dlg, bg='#FAFAFA')
        container.pack(fill=tk.BOTH, expand=True, padx=pad)

        canvas = tk.Canvas(container, bg='#FAFAFA', highlightthickness=0)
        scrollbar = tk.Scrollbar(container, orient="vertical", command=canvas.yview)
        self.body = tk.Frame(canvas, bg='#FAFAFA')
        self.body.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.body, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # 黑名单标题行（左侧标题 + 右侧通用按钮，同一排）
        _bl_title_row = tk.Frame(self.body, bg='#FAFAFA')
        _bl_title_row.pack(fill=tk.X, pady=(0, int(2 * S)))
        tk.Label(_bl_title_row, text="── 黑名单（抑制断网，先扫）──",
                 bg='#FAFAFA',
                 font=("微软雅黑", -max(12, int(13 * S)), "bold"),
                 fg='#1565C0').pack(side=tk.LEFT)
        _uni_bl_n = len(self.universal_rules.get("blacklist", []))
        self._btn_uni_bl = tk.Button(
            _bl_title_row,
            text=f"⚙️ 通用规则（{_uni_bl_n}）",
            command=lambda: self._edit_universal("black"),
            bg='#F3E5F5', fg='#6A1B9A',
            font=("微软雅黑", -max(9, int(10 * S)), "bold"),
            relief='flat', padx=int(8 * S), pady=int(1 * S),
            activebackground='#E1BEE7', cursor='hand2')
        self._btn_uni_bl.pack(side=tk.RIGHT)

        self.bl_frame = tk.Frame(self.body, bg='#FFFFFF',
                                 highlightbackground='#90CAF9', highlightthickness=1)
        self.bl_frame.pack(fill=tk.X, pady=(0, int(8 * S)))

        # 白名单标题行（左侧标题 + 右侧通用按钮，同一排）
        _wl_title_row = tk.Frame(self.body, bg='#FAFAFA')
        _wl_title_row.pack(fill=tk.X, pady=(0, int(2 * S)))
        tk.Label(_wl_title_row, text="── 白名单（触发断网，后扫）──",
                 bg='#FAFAFA',
                 font=("微软雅黑", -max(12, int(13 * S)), "bold"),
                 fg='#2E7D32').pack(side=tk.LEFT)
        _uni_wl_n = len(self.universal_rules.get("whitelist", []))
        self._btn_uni_wl = tk.Button(
            _wl_title_row,
            text=f"⚙️ 通用规则（{_uni_wl_n}）",
            command=lambda: self._edit_universal("white"),
            bg='#F3E5F5', fg='#6A1B9A',
            font=("微软雅黑", -max(9, int(10 * S)), "bold"),
            relief='flat', padx=int(8 * S), pady=int(1 * S),
            activebackground='#E1BEE7', cursor='hand2')
        self._btn_uni_wl.pack(side=tk.RIGHT)

        self.wl_frame = tk.Frame(self.body, bg='#FFFFFF',
                                 highlightbackground='#A5D6A7', highlightthickness=1)
        self.wl_frame.pack(fill=tk.X, pady=(0, int(8 * S)))

        btn_frame = tk.Frame(self.dlg, bg='#FAFAFA')
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=pad, pady=int(10 * S))
        tk.Button(btn_frame, text="✓ 应用", command=self._on_apply,
                  bg='#4CAF50', fg='white', font=f_btn,
                  relief='flat', padx=int(20 * S), pady=int(6 * S)
                  ).pack(side=tk.RIGHT, padx=int(4 * S))
        tk.Button(btn_frame, text="✕ 取消", command=self._on_cancel,
                  bg='#F44336', fg='white', font=f_btn,
                  relief='flat', padx=int(20 * S), pady=int(6 * S)
                  ).pack(side=tk.RIGHT)

        self._refresh_lists()
        self.dlg.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.dlg.bind("<Escape>", lambda e: self._on_cancel())

    def _edit_universal(self, kind):
        """编辑通用规则（kind = 'black' 或 'white'）

        点通用编辑的"应用" → 直接写文件，不用等主规则管理
        """
        try:
            from .universal_editor import UniversalListDialog
        except Exception as e:
            messagebox.showerror("错误",
                                  f"无法打开通用规则编辑器：{e}",
                                  parent=self.dlg)
            return
        key = "blacklist" if kind == "black" else "whitelist"
        lst = self.universal_rules.get(key, [])
        if not isinstance(lst, list):
            lst = []
        print(f"⚙️ 打开通用规则编辑：{key}，当前 {len(lst)} 条",
              flush=True)
        dlg = UniversalListDialog(self.app, kind, lst, scale=self.scale)
        result = dlg.show()
        if result is None:
            print("ℹ️ 通用规则编辑取消", flush=True)
            return
        self.universal_rules[key] = result
        print(f"✅ 通用规则已更新：{key}，现在 {len(result)} 条",
              flush=True)
        # 直接写文件（不用等主规则管理）
        try:
            from .config_manager import save_templates, deep_copy as _dc
            merged = _dc(self.app.templates)
            if self.universal_rules.get("whitelist") \
                    or self.universal_rules.get("blacklist"):
                merged["universal"] = _dc(self.universal_rules)
            else:
                merged.pop("universal", None)
            ok = save_templates(merged)
            if ok:
                print("💾 通用规则已写入 templates.toml", flush=True)
            else:
                print("❌ 通用规则写文件失败", flush=True)
        except Exception as e:
            print(f"❌ 写文件异常：{e}", flush=True)
        # 刷新按钮
        try:
            if kind == "black":
                self._btn_uni_bl.config(
                    text=f"⚙️ 通用规则（{len(result)}）")
            else:
                self._btn_uni_wl.config(
                    text=f"⚙️ 通用规则（{len(result)}）")
        except Exception:
            pass


    def _refresh_lists(self):
        S = self.scale
        f_text = ("微软雅黑", -max(11, int(12 * S)))
        f_btn = ("微软雅黑", -max(10, int(11 * S)))
        f_arrow = ("Arial", -max(12, int(14 * S)), "bold")

        for w in self.bl_frame.winfo_children(): w.destroy()
        bl_list = self.rules.get("blacklist", [])
        for idx, r in enumerate(bl_list):
            self._build_rule_row(self.bl_frame, r, idx, "blacklist",
                                 f_text, f_btn, f_arrow, len(bl_list))
        add_row = tk.Frame(self.bl_frame, bg='#FFFFFF')
        add_row.pack(fill=tk.X, padx=int(8 * S), pady=int(4 * S))
        tk.Button(add_row, text="＋ 添加黑名单", bg='#E3F2FD', fg='#0D47A1',
                  font=f_btn, relief='flat', padx=int(10 * S), pady=int(3 * S),
                  command=lambda: self._on_add("blacklist")).pack(side=tk.LEFT)

        for w in self.wl_frame.winfo_children(): w.destroy()
        wl_list = self.rules.get("whitelist", [])
        for idx, r in enumerate(wl_list):
            self._build_rule_row(self.wl_frame, r, idx, "whitelist",
                                 f_text, f_btn, f_arrow, len(wl_list))
        add_row = tk.Frame(self.wl_frame, bg='#FFFFFF')
        add_row.pack(fill=tk.X, padx=int(8 * S), pady=int(4 * S))
        tk.Button(add_row, text="＋ 添加白名单", bg='#E8F5E9', fg='#2E7D32',
                  font=f_btn, relief='flat', padx=int(10 * S), pady=int(3 * S),
                  command=lambda: self._on_add("whitelist")).pack(side=tk.LEFT)

        # 重建后重新绑定滚轮到所有新 widget
        try:
            self._bind_wheel(self._canvas_scroll)
        except Exception:
            pass

    def _build_rule_row(self, parent, r, idx, list_name, f_text, f_btn, f_arrow, total):
        S = self.scale
        row = tk.Frame(parent, bg='#FFFFFF')
        row.pack(fill=tk.X, padx=int(8 * S), pady=int(4 * S))

        move_frame = tk.Frame(row, bg='#FFFFFF')
        move_frame.pack(side=tk.LEFT, padx=(0, int(4 * S)))
        up_state = 'normal' if idx > 0 else 'disabled'
        down_state = 'normal' if idx < total - 1 else 'disabled'
        tk.Button(move_frame, text="↑", bg='#EEEEEE', fg='#333',
                  font=f_arrow, relief='flat', width=2, state=up_state,
                  command=lambda i=idx, ln=list_name: self._on_move(ln, i, -1)
                  ).pack()
        tk.Button(move_frame, text="↓", bg='#EEEEEE', fg='#333',
                  font=f_arrow, relief='flat', width=2, state=down_state,
                  command=lambda i=idx, ln=list_name: self._on_move(ln, i, 1)
                  ).pack()

        has_roi = rule_has_roi(r)
        mark = "✓" if has_roi else "✗"
        color = "#2E7D32" if has_roi else "#B71C1C"
        tk.Label(row, text=f"{idx+1}.", bg='#FFFFFF', fg='#888',
                 font=f_text, width=3, anchor='w').pack(side=tk.LEFT)
        tk.Label(row, text=mark, bg='#FFFFFF',
                 font=("Arial", -max(12, int(14 * S)), "bold"),
                 fg=color, width=2).pack(side=tk.LEFT)
        if (r.get("exclude_text") or "").strip():
            tk.Label(row, text="⊘", bg='#FFFFFF',
                     font=("Arial", -max(12, int(14 * S)), "bold"),
                     fg='#C62828', width=2).pack(side=tk.LEFT)
        tk.Label(row, text=r.get("name", "未命名"), bg='#FFFFFF', font=f_text,
                 fg='#333', width=10, anchor='w').pack(side=tk.LEFT)
        _kind = getattr(self, "source_info", {}).get("kind", "user")
        if _kind == "user":
            _lt, _lbg, _lfg = "用户", "#E8F5E9", "#2E7D32"
        elif _kind == "builtin":
            _lt, _lbg, _lfg = "内置", "#E3F2FD", "#1565C0"
        elif _kind == "fallback":
            _lt, _lbg, _lfg = "兜底", "#FFF3E0", "#E65100"
        else:
            _lt, _lbg, _lfg = "?", "#EEEEEE", "#616161"
        tk.Label(row, text=f" {_lt} ", bg=_lbg, fg=_lfg,
                 font=("微软雅黑", -max(9, int(10 * S)), "bold"),
                 padx=2).pack(side=tk.LEFT, padx=(0, int(4 * S)))
        ocr_text = r.get("ocr_text", "")
        display = ocr_text[:20] + ("…" if len(ocr_text) > 20 else "")
        tk.Label(row, text=f"[{display}]", bg='#FFFFFF',
                 font=("Consolas", -max(10, int(11 * S))),
                 fg='#666', anchor='w').pack(side=tk.LEFT, padx=int(4 * S))

        tk.Button(row, text="删除", bg='#FFEBEE', fg='#C62828',
                  font=f_btn, relief='flat', padx=int(6 * S), pady=int(2 * S),
                  command=lambda i=idx, ln=list_name: self._on_delete(ln, i)
                  ).pack(side=tk.RIGHT, padx=int(2 * S))
        tk.Button(row, text="编辑", bg='#FFF3E0', fg='#E65100',
                  font=f_btn, relief='flat', padx=int(6 * S), pady=int(2 * S),
                  command=lambda i=idx, ln=list_name: self._on_edit(ln, i)
                  ).pack(side=tk.RIGHT, padx=int(2 * S))
        _adjust_text = "✏️ 调整" if has_roi else "✏️ 画框"
        tk.Button(row, text=_adjust_text,
                  bg='#E3F2FD', fg='#0D47A1',
                  font=f_btn, relief='flat', padx=int(6 * S), pady=int(2 * S),
                  command=lambda i=idx, ln=list_name: self._on_adjust(ln, i)
                  ).pack(side=tk.RIGHT, padx=int(2 * S))
        _preview_ok = rule_has_roi(r)
        tk.Button(row, text="预览",
                  bg='#F3E5F5' if _preview_ok else '#EEEEEE',
                  fg='#6A1B9A' if _preview_ok else '#AAAAAA',
                  font=f_btn, relief='flat', padx=int(6 * S), pady=int(2 * S),
                  state='normal' if _preview_ok else 'disabled',
                  command=lambda i=idx, ln=list_name: self._on_preview(ln, i)
                  ).pack(side=tk.RIGHT, padx=int(2 * S))
        _has_note = bool((r.get("note") or "").strip())
        tk.Button(row, text="备注",
                  bg='#E0F7FA' if _has_note else '#EEEEEE',
                  fg='#006064' if _has_note else '#999999',
                  font=f_btn, relief='flat', padx=int(6 * S), pady=int(2 * S),
                  command=lambda i=idx, ln=list_name: self._on_note(ln, i)
                  ).pack(side=tk.RIGHT, padx=int(2 * S))

    def _on_move(self, list_name, idx, delta):
        lst = self.rules.get(list_name, [])
        new_idx = idx + delta
        if not (0 <= new_idx < len(lst)): return
        lst[idx], lst[new_idx] = lst[new_idx], lst[idx]
        lst[idx]["_source"] = "exact"
        lst[new_idx]["_source"] = "exact"
        self._refresh_lists()

    def _on_add(self, list_name):
        self._show_edit_dialog(list_name, None, "添加规则")

    def _on_edit(self, list_name, idx):
        lst = self.rules.get(list_name, [])
        if not (0 <= idx < len(lst)): return
        self._show_edit_dialog(list_name, idx, "编辑规则")

    def _on_delete(self, list_name, idx):
        lst = self.rules.get(list_name, [])
        if not (0 <= idx < len(lst)): return
        name = lst[idx].get("name", "")
        if messagebox.askyesno("确认删除", f"确定删除规则「{name}」？", parent=self.dlg):
            lst.pop(idx)
            self._refresh_lists()

    def _show_edit_dialog(self, list_name, idx, title):
        S = self.scale
        f_title = ("微软雅黑", -max(12, int(13 * S)), "bold")
        f_text = ("微软雅黑", -max(11, int(12 * S)))
        f_hint = ("微软雅黑", -max(10, int(11 * S)))
        f_mono = ("Consolas", -max(11, int(12 * S)))
        r = {} if idx is None else self.rules[list_name][idx]
        self._roi_vars = {}

        dlg = tk.Toplevel(self.dlg)
        dlg.title(title)
        dlg.attributes('-topmost', True)
        dlg.configure(bg='white')
        self._edit_dlg = dlg
        w = int(640 * S); h = int(980 * S)
        dlg.update_idletasks()
        sw = dlg.winfo_screenwidth(); sh = dlg.winfo_screenheight()
        if h > sh - int(40 * S): h = sh - int(40 * S)
        dlg.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
        # 不 grab_set，允许切到游戏看位置
        dlg.lift()

        pad = int(14 * S)

        # ---- ROI 区域（移动现有画框 / 微调）----
        tk.Label(dlg, text="ROI 区域（相对客户区，0~1）",
                 bg='white', font=f_title, fg='#1976D2', anchor='w'
                 ).pack(fill=tk.X, padx=pad, pady=(pad, int(2 * S)))
        roi_frame = tk.Frame(dlg, bg='#F5F5F5',
                             highlightbackground='#BDBDBD',
                             highlightthickness=1)
        roi_frame.pack(fill=tk.X, padx=pad)
        has_roi = rule_has_roi(r)
        if has_roi:
            tk.Label(roi_frame,
                     text="✓ 已画框（可直接改数值微调 / 或点下方「重新画框」）",
                     bg='#F5F5F5', fg='#2E7D32', font=f_hint, anchor='w'
                     ).pack(fill=tk.X, padx=int(8 * S), pady=(int(4 * S), 0))
            for row_keys in (("x1", "y1"), ("x2", "y2")):
                row = tk.Frame(roi_frame, bg='#F5F5F5')
                row.pack(fill=tk.X, padx=int(8 * S), pady=int(2 * S))
                for k in row_keys:
                    tk.Label(row, text=k + ":", bg='#F5F5F5', fg='#555',
                             font=f_mono, width=3, anchor='w'
                             ).pack(side=tk.LEFT)
                    v = tk.StringVar(value=str(round(float(r[k]), 4)))
                    self._roi_vars[k] = v
                    tk.Entry(row, textvariable=v, font=f_mono, width=10
                             ).pack(side=tk.LEFT, padx=(int(2 * S), int(14 * S)))
            tk.Frame(roi_frame, bg='#F5F5F5', height=int(4 * S)
                     ).pack(fill=tk.X)
        else:
            tk.Label(roi_frame,
                     text="✗ 未画框（请点下方「重新画框」进入游戏框选）",
                     bg='#F5F5F5', fg='#B71C1C', font=f_hint, anchor='w'
                     ).pack(fill=tk.X, padx=int(8 * S), pady=int(8 * S))

        def do_redraw():
            if idx is None:
                messagebox.showinfo(
                    "提示",
                    "新增的规则需要先点「确定」保存后，\n"
                    "再从列表里点「画框」进入框选。",
                    parent=dlg)
                return
            # 先把当前编辑内容保存到 rules，避免丢失
            self.rules[list_name][idx]["name"] = (
                e_name.get().strip() or "未命名")
            self.rules[list_name][idx]["ocr_text"] = \
                t_text.get("1.0", "end-1c").strip()
            self.rules[list_name][idx]["exclude_text"] = \
                t_excl.get("1.0", "end-1c").strip()
            self.rules[list_name][idx]["note"] = \
                t_note.get("1.0", "end-1c").strip()
            self.rules[list_name][idx]["match_mode"] = mode_var.get()
            # 顺便把用户改过的 ROI 也存一下
            if self._roi_vars:
                try:
                    for k, v in self._roi_vars.items():
                        self.rules[list_name][idx][k] = round(
                            float(v.get().strip()), 4)
                except Exception:
                    pass
            dlg.destroy()
            self._on_draw(list_name, idx)

        tk.Button(roi_frame, text="🎯 重新画框（替换现有 ROI）",
                  command=do_redraw,
                  bg='#E3F2FD', fg='#0D47A1', font=f_text,
                  relief='flat', padx=int(10 * S), pady=int(4 * S)
                  ).pack(pady=(0, int(8 * S)))

        # ---- 规则名字 ----
        tk.Label(dlg, text="规则名字（方便自己看懂这条规则干嘛用）",
                 bg='white', font=f_title, fg='#1976D2',
                 anchor='w').pack(fill=tk.X, padx=pad,
                                  pady=(int(10 * S), int(2 * S)))
        e_name = tk.Entry(dlg, font=f_text)
        e_name.pack(fill=tk.X, padx=pad)
        e_name.insert(0, r.get("name", ""))
        try: e_name.focus_set()
        except Exception: pass

        # ---- 期望文字 ----
        tk.Label(dlg, text="期望文字 / 正则（可多行，自动换行）",
                 bg='white', font=f_title, fg='#1976D2',
                 anchor='w').pack(fill=tk.X, padx=pad,
                                  pady=(int(8 * S), int(2 * S)))
        t_text = tk.Text(dlg, font=f_mono, height=4, wrap='char',
                         relief='solid', bd=1)
        t_text.pack(fill=tk.X, padx=pad)
        t_text.insert("1.0", r.get("ocr_text", ""))

        # ---- 否定词 ----
        tk.Label(dlg,
                 text='否定词（可选，命中则跳过本规则 · 例如 \\d+赛季 排除 "12赛季"）',
                 bg='white', font=f_title, fg='#C62828',
                 anchor='w').pack(fill=tk.X, padx=pad,
                                  pady=(int(8 * S), int(2 * S)))
        t_excl = tk.Text(dlg, font=f_mono, height=2, wrap='char',
                         relief='solid', bd=1)
        t_excl.pack(fill=tk.X, padx=pad)
        t_excl.insert("1.0", r.get("exclude_text", ""))

        # ---- 备注 ----
        tk.Label(dlg, text="备注（说明这条规则干什么用，可留空）",
                 bg='white', font=f_title, fg='#1976D2',
                 anchor='w').pack(fill=tk.X, padx=pad,
                                  pady=(int(8 * S), int(2 * S)))
        t_note = tk.Text(dlg, font=f_text, height=3, wrap='char',
                         relief='solid', bd=1)
        t_note.pack(fill=tk.X, padx=pad)
        t_note.insert("1.0", r.get("note", ""))

        # ---- 匹配模式 ----
        tk.Label(dlg, text="匹配模式", bg='white', font=f_title,
                 fg='#1976D2', anchor='w').pack(fill=tk.X, padx=pad,
                                                pady=(int(8 * S), int(2 * S)))
        mode_var = tk.StringVar(value=r.get("match_mode", "contains"))
        mode_frame = tk.Frame(dlg, bg='white')
        mode_frame.pack(anchor='w', padx=pad)
        for val, label in [("contains", "包含"), ("equals", "完全相等"),
                           ("regex", "正则")]:
            tk.Radiobutton(mode_frame, text=label, variable=mode_var,
                           value=val, bg='white', font=f_text,
                           activebackground='white').pack(side=tk.LEFT,
                                                          padx=int(4 * S))

        # ---- 断网秒数（每规则覆盖） ----
        tk.Label(dlg,
                 text="断网秒数（留空 = OCR 默认；填了 = 用填的秒数）",
                 bg='white', font=f_title, fg='#1976D2',
                 anchor='w').pack(fill=tk.X, padx=pad,
                                  pady=(int(8 * S), int(2 * S)))
        bt_val = ""
        if isinstance(r.get("block_time"), (int, str)) and r.get("block_time") != "":
            bt_val = str(r.get("block_time"))
        self._bt_var = tk.StringVar(value=bt_val)
        bt_row = tk.Frame(dlg, bg='white')
        bt_row.pack(fill=tk.X, padx=pad)
        tk.Entry(bt_row, textvariable=self._bt_var, font=f_mono, width=8
                 ).pack(side=tk.LEFT)
        tk.Label(bt_row,
                 text="  秒（留空 = 用 OCR 默认秒数；填数字 = 用填的）",
                 bg='white', fg='#888', font=f_hint).pack(side=tk.LEFT)

        # ---- 提示 ----
        hint_frame = tk.Frame(dlg, bg='#FFF3E0',
                              highlightbackground='#FFB74D',
                              highlightthickness=1)
        hint_frame.pack(fill=tk.X, padx=pad, pady=(int(10 * S), 0))
        tk.Label(hint_frame,
                 text="💡 看不懂位置？浏览备注吧\n"
                      "✅ 觉得调整的 OK 的话，就把 OCR 调试窗口框关闭"
                      "（主窗口 ⏱ → 取消勾选「显示调试框」）",
                 bg='#FFF3E0', fg='#E65100', font=f_hint,
                 justify='left', anchor='w',
                 wraplength=int(600 * S)).pack(fill=tk.X, padx=int(8 * S),
                                               pady=int(6 * S))

        # ---- 保存 ----
        def on_ok():
            name = e_name.get().strip() or "未命名"
            text = t_text.get("1.0", "end-1c").strip()
            excl = t_excl.get("1.0", "end-1c").strip()
            note = t_note.get("1.0", "end-1c").strip()
            mode = mode_var.get()
            # 断网秒数：空/非法 → None（用全局）
            bt_raw = self._bt_var.get().strip()
            bt_val = None
            if bt_raw:
                try:
                    bt_val = int(bt_raw)
                    if bt_val < 1 or bt_val > 600:
                        raise ValueError("断网秒数应在 1~600 之间")
                except ValueError as e:
                    messagebox.showerror("断网秒数错误", str(e), parent=dlg)
                    return
            # ROI 数值校验
            new_roi = {}
            if idx is not None and self._roi_vars:
                try:
                    for k, v in self._roi_vars.items():
                        fv = float(v.get().strip())
                        if not (0.0 <= fv <= 1.0):
                            raise ValueError(f"{k} 应在 0~1 之间")
                        new_roi[k] = round(fv, 4)
                    if new_roi["x1"] >= new_roi["x2"]:
                        raise ValueError("x1 必须小于 x2")
                    if new_roi["y1"] >= new_roi["y2"]:
                        raise ValueError("y1 必须小于 y2")
                except ValueError as e:
                    messagebox.showerror("ROI 数值错误", str(e), parent=dlg)
                    return
            if idx is None:
                new_rule = {
                    "name": name, "x1": None, "y1": None,
                    "x2": None, "y2": None,
                    "ocr_text": text, "match_mode": mode,
                    "note": note, "exclude_text": excl,
                    "_source": "exact",
                }
                if bt_val is not None:
                    new_rule["block_time"] = bt_val
                self.rules[list_name].append(new_rule)
            else:
                self.rules[list_name][idx]["name"] = name
                self.rules[list_name][idx]["ocr_text"] = text
                self.rules[list_name][idx]["match_mode"] = mode
                self.rules[list_name][idx]["note"] = note
                self.rules[list_name][idx]["exclude_text"] = excl
                if new_roi:
                    for k, v in new_roi.items():
                        self.rules[list_name][idx][k] = v
                # 断网秒数：None → 删掉该字段（用全局）
                if bt_val is None:
                    if "block_time" in self.rules[list_name][idx]:
                        del self.rules[list_name][idx]["block_time"]
                else:
                    self.rules[list_name][idx]["block_time"] = bt_val
                # 用户主动编辑过 → 标为专用，应用时写回本分辨率
                self.rules[list_name][idx]["_source"] = "exact"
            dlg.destroy()
            self._refresh_lists()

        def on_cancel():
            dlg.destroy()

        btn = tk.Frame(dlg, bg='white')
        btn.pack(side=tk.BOTTOM, fill=tk.X, padx=pad, pady=int(12 * S))
        alpha_state = {"alpha": 1.0}
        def toggle_alpha():
            if alpha_state["alpha"] >= 1.0:
                try: dlg.attributes('-alpha', 0.35)
                except Exception: pass
                alpha_state["alpha"] = 0.35
                btn_alpha.config(text="�� 恢复不透明")
            else:
                try: dlg.attributes('-alpha', 1.0)
                except Exception: pass
                alpha_state["alpha"] = 1.0
                btn_alpha.config(text="👁 半透明看游戏")
        btn_alpha = tk.Button(btn, text="👁 半透明看游戏", command=toggle_alpha,
                              font=f_text, bg='#E3F2FD', fg='#0D47A1',
                              relief='flat', padx=int(10 * S), pady=int(5 * S))
        btn_alpha.pack(side=tk.LEFT)
        tk.Button(btn, text="✓ 确定", command=on_ok, font=f_text,
                  bg='#4CAF50', fg='white', relief='flat',
                  padx=int(14 * S), pady=int(5 * S)
                  ).pack(side=tk.RIGHT, padx=int(4 * S))
        tk.Button(btn, text="✕ 取消", command=on_cancel, font=f_text,
                  bg='#F44336', fg='white', relief='flat',
                  padx=int(14 * S), pady=int(5 * S)
                  ).pack(side=tk.RIGHT)
        dlg.bind("<Escape>", lambda e: on_cancel())

    def _on_adjust(self, list_name, idx):
        """智能调整：有框 → 编辑框；无框 → 画新框"""
        lst = self.rules.get(list_name, [])
        if not (0 <= idx < len(lst)): return
        r = lst[idx]
        if rule_has_roi(r):
            self._on_edit_roi(list_name, idx)
        else:
            self._on_draw(list_name, idx)

    def _on_edit_roi(self, list_name, idx):
        """在游戏画面上拖动/缩放现有 ROI"""
        lst = self.rules.get(list_name, [])
        if not (0 <= idx < len(lst)): return
        r = lst[idx]
        if not rule_has_roi(r):
            self._on_draw(list_name, idx); return
        rule_name = r.get("name", "")
        roi = (float(r["x1"]), float(r["y1"]),
               float(r["x2"]), float(r["y2"]))

        def restore():
            try:
                if self.dlg is not None and self.dlg.winfo_exists():
                    self.dlg.deiconify()
                    self.dlg.lift()
                    self.dlg.focus_force()
            except Exception as e:
                print(f"恢复规则管理窗口失败: {e}", flush=True)
            try: self._refresh_lists()
            except Exception: pass

        def cb(new_roi):
            try:
                if new_roi is None:
                    return
                r["x1"], r["y1"], r["x2"], r["y2"] = new_roi
                r["_source"] = "exact"
                print(f"✏️ 规则「{rule_name}」ROI 已更新："
                      f"x[{new_roi[0]:.4f},{new_roi[2]:.4f}] "
                      f"y[{new_roi[1]:.4f},{new_roi[3]:.4f}]", flush=True)
                self._refresh_lists()
            finally:
                # 无论成功失败都要把规则管理窗口唤回来
                restore()

        self.dlg.withdraw()
        self.app.edit_roi_with_callback(
            roi, cb,
            hint_text=f"调整「{rule_name}」的框：拖框内移动 · 拖四角缩放",
            on_restore=restore)

    def _on_draw(self, list_name, idx):
        lst = self.rules.get(list_name, [])
        if not (0 <= idx < len(lst)): return
        r = lst[idx]
        rule_name = r.get("name", "")

        def cb(roi):
            if roi is None: return
            r["x1"], r["y1"], r["x2"], r["y2"] = roi
            r["_source"] = "exact"
            print(f"📷 规则「{rule_name}」已框选：x[{roi[0]:.4f},{roi[2]:.4f}] "
                  f"y[{roi[1]:.4f},{roi[3]:.4f}]", flush=True)
            self._post_draw_ocr(r, rule_name)
            self._refresh_lists()

        def restore():
            try:
                self.dlg.deiconify(); self.dlg.lift(); self.dlg.focus_force()
            except Exception: pass
            self._refresh_lists()

        self.dlg.withdraw()
        self.app.enter_region_select_mode_with_callback(
            cb, hint_text=f"框选「{rule_name}」区域", on_done_restore=restore)

    def _on_note(self, list_name, idx):
        """查看/提示这条规则的备注"""
        lst = self.rules.get(list_name, [])
        if not (0 <= idx < len(lst)): return
        r = lst[idx]
        name = r.get("name", "未命名") or "未命名"
        note = (r.get("note") or "").strip()
        if not note:
            messagebox.showinfo(
                f"规则备注 - {name}",
                f"「{name}」暂无备注。\n\n"
                "点「编辑」可以填写备注，写下这条规则干什么用。",
                parent=self.dlg)
        else:
            messagebox.showinfo(f"规则备注 - {name}", note, parent=self.dlg)

    def _on_preview(self, list_name, idx):
        """点击预览：在游戏客户区对应 ROI 上闪烁 1.5 秒"""
        lst = self.rules.get(list_name, [])
        if not (0 <= idx < len(lst)): return
        r = lst[idx]
        if not rule_has_roi(r):
            messagebox.showinfo("提示", "该规则还没有画框", parent=self.dlg)
            return
        exe_name = self.app.get_target_exe_name()
        if not exe_name:
            messagebox.showerror("错误", "无有效断网目标", parent=self.dlg); return
        pid = get_pid_by_exe_name(exe_name)
        if pid is None:
            messagebox.showwarning("提示", "目标游戏未运行", parent=self.dlg); return
        hwnd = get_hwnd_by_pid(pid)
        if not hwnd or not is_window_alive(hwnd):
            messagebox.showwarning("提示", "找不到游戏窗口", parent=self.dlg); return
        if (not is_window_visible(hwnd) or is_window_minimized(hwnd)
                or is_window_cloaked(hwnd)):
            messagebox.showwarning("提示", "请先把游戏窗口显示出来",
                                   parent=self.dlg); return
        l, t, rr, bb = get_client_rect_screen(hwnd)
        cw, ch = rr - l, bb - t
        if cw <= 0 or ch <= 0:
            messagebox.showwarning("提示", "游戏客户区无效", parent=self.dlg); return
        x1 = l + int(cw * float(r["x1"]))
        y1 = t + int(ch * float(r["y1"]))
        x2 = l + int(cw * float(r["x2"]))
        y2 = t + int(ch * float(r["y2"]))
        self._start_preview_flash(x1, y1, x2, y2)

    def _start_preview_flash(self, x1, y1, x2, y2,
                             duration_ms=1500, interval_ms=150):
        if getattr(self, "_preview_top", None) is not None:
            try: self._preview_top.destroy()
            except Exception: pass
            self._preview_top = None
        try:
            top = tk.Toplevel(self.dlg)
            top.overrideredirect(True)
            top.attributes('-topmost', True)
            top.configure(bg='#FE01FE')
            try: top.attributes('-transparentcolor', '#FE01FE')
            except Exception: pass
            pad = 6
            w = max(20, (x2 - x1) + pad * 2)
            h = max(20, (y2 - y1) + pad * 2)
            top.geometry(f"{w}x{h}+{x1 - pad}+{y1 - pad}")
            cvs = tk.Canvas(top, bg='#FE01FE', highlightthickness=0, bd=0)
            cvs.pack(fill=tk.BOTH, expand=True)
            rect = cvs.create_rectangle(pad, pad, pad + (x2 - x1),
                                         pad + (y2 - y1),
                                         outline='#FFEB3B', width=4, fill='')
            try:
                raw = top.winfo_id()
                hwnd = _user32.GetAncestor(raw, GA_ROOT) or raw
                set_window_capture_exclude(hwnd)
            except Exception:
                pass
            self._preview_top = top
            total_ticks = max(2, int(duration_ms / interval_ms))
            state = {"n": 0}

            def tick():
                if not top.winfo_exists():
                    return
                state["n"] += 1
                if state["n"] > total_ticks:
                    try: top.destroy()
                    except Exception: pass
                    self._preview_top = None
                    return
                color = '#FFEB3B' if state["n"] % 2 == 0 else '#F44336'
                try: cvs.itemconfig(rect, outline=color)
                except Exception: pass
                top.after(interval_ms, tick)

            tick()
        except Exception as e:
            print(f"预览闪烁失败: {e}", flush=True)

    def _post_draw_ocr(self, rule, rule_name):
        if not is_ocr_available():
            print("ℹ️ OCR 未安装，跳过预览", flush=True)
            return
        pid = get_pid_by_exe_name(self.app.get_target_exe_name())
        if pid is None: return
        hwnd = get_hwnd_by_pid(pid)
        if not hwnd or not is_window_alive(hwnd): return
        bgra, _ = capture_roi_bgra(hwnd, (rule["x1"], rule["y1"],
                                          rule["x2"], rule["y2"]))
        if bgra is None or bgra.size == 0:
            print("ℹ️ 框选区域截图失败", flush=True); return
        text = ocr_recognize(bgra)
        print(f"🔤 框选后 OCR 识别结果：'{text}'", flush=True)

        S = self.scale
        f_text = ("微软雅黑", -max(11, int(12 * S)))
        dlg = tk.Toplevel(self.dlg)
        self._ocr_dlg = dlg
        dlg.title(f"框选结果 - {rule_name}")
        dlg.attributes('-topmost', True)
        dlg.configure(bg='white')
        w = int(480 * S); h = int(220 * S)
        dlg.update_idletasks()
        sw = dlg.winfo_screenwidth(); sh = dlg.winfo_screenheight()
        dlg.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
        try: dlg.grab_set()
        except Exception: pass
        dlg.lift(); dlg.focus_force()

        tk.Label(dlg, text=f"规则：{rule_name}", bg='white',
                 font=("微软雅黑", -max(12, int(13 * S)), "bold"),
                 fg='#1976D2').pack(pady=(int(10 * S), int(4 * S)))
        tk.Label(dlg, text=f"OCR 实际识别到：{text or '（无）'}", bg='white',
                 fg='#555', font=f_text,
                 wraplength=int(440 * S), justify='left').pack(padx=int(10 * S))
        tk.Label(dlg, text="⬇ 用识别结果作为期望文字（可编辑）⬇", bg='#FFF3E0',
                 fg='#E65100', font=("微软雅黑", -max(10, int(11 * S)), "bold"),
                 padx=int(8 * S), pady=int(3 * S)).pack(fill=tk.X, padx=int(10 * S),
                                                        pady=(int(6 * S), 0))
        entry = tk.Entry(dlg, font=("Consolas", -max(11, int(12 * S))), width=48)
        entry.pack(pady=int(4 * S))
        entry.insert(0, text if text else rule.get("ocr_text", ""))
        entry.focus_set(); entry.select_range(0, tk.END)

        def on_apply():
            new_text = entry.get().strip()
            if new_text:
                rule["ocr_text"] = new_text
                print(f"✅ 已更新「{rule_name}」的期望文字为：'{new_text}'", flush=True)
            dlg.destroy(); self._refresh_lists()

        def on_skip():
            dlg.destroy(); self._refresh_lists()

        btn = tk.Frame(dlg, bg='white')
        btn.pack(pady=int(8 * S))
        tk.Button(btn, text="采用此文字", command=on_apply,
                  bg='#4CAF50', fg='white', font=f_text,
                  relief='flat', padx=int(10 * S), pady=int(4 * S)
                  ).pack(side=tk.LEFT, padx=int(4 * S))
        tk.Button(btn, text="保留原文字", command=on_skip,
                  bg='#FF9800', fg='white', font=f_text,
                  relief='flat', padx=int(10 * S), pady=int(4 * S)
                  ).pack(side=tk.LEFT, padx=int(4 * S))
        dlg.bind("<Return>", lambda e: on_apply())
        dlg.bind("<Escape>", lambda e: on_skip())

    def _on_apply(self):
        self.result = deep_copy(self.rules)
        # 把通用规则一起包进去
        if isinstance(self.result, dict):
            self.result["_universal"] = deep_copy(self.universal_rules)
        try:
            new_scan = bool(self.scan_all_var.get())
            if new_scan != self.initial_scan_all:
                self.app.update_scan_all(new_scan)
        except Exception as e:
            print(f"保存全量扫描开关失败: {e}", flush=True)
        try: self.dlg.destroy()
        except Exception as e:
            print(f"销毁规则管理窗口失败: {e}", flush=True)
        if self.on_apply_cb:
            try: self.on_apply_cb(self.result)
            except Exception as e:
                print(f"应用回调失败: {e}", flush=True)

    def _on_cancel(self):
        self.result = None
        try: self.dlg.destroy()
        except Exception as e:
            print(f"销毁规则管理窗口失败: {e}", flush=True)
        if self.on_cancel_cb:
            try: self.on_cancel_cb()
            except Exception as e:
                print(f"取消回调失败: {e}", flush=True)

    def show(self, nonblocking=False):
        if nonblocking:
            return None
        self.parent.wait_window(self.dlg)
        return self.result
