"""通用规则列表对话框：无 ROI，只匹配文字"""
import tkinter as tk
from tkinter import messagebox

from .config_manager import deep_copy


class UniversalListDialog:
    """通用规则列表编辑器

    kind: "black" 或 "white"
    """

    def __init__(self, parent_app, kind, rules, scale=1.0, size=(660, 560)):
        self.app = parent_app
        self.parent = parent_app.root
        self.kind = kind
        self.rules = deep_copy(rules) if isinstance(rules, list) else []
        self.scale = scale
        self.dialog_size = size
        self.result = None
        self.dlg = None
        self._build()

    def _build(self):
        S = self.scale
        dlg = tk.Toplevel(self.parent)
        is_black = (self.kind == "black")
        title = "通用黑名单（抑制断网）" if is_black else "通用白名单（触发断网）"
        dlg.title(title)
        dlg.attributes('-topmost', True)
        dlg.configure(bg='#FAFAFA')
        try:
            dlg.grab_set()
        except Exception:
            pass
        dlg.update_idletasks()
        sw = dlg.winfo_screenwidth()
        sh = dlg.winfo_screenheight()
        w = int(self.dialog_size[0] * S)
        h = min(int(self.dialog_size[1] * S), sh - int(60 * S))
        dlg.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
        self.dlg = dlg

        pad = int(14 * S)
        f_title = ("微软雅黑", -max(13, int(15 * S)), "bold")
        f_hint = ("微软雅黑", -max(10, int(11 * S)))

        color = '#1565C0' if is_black else '#2E7D32'
        bg = '#E3F2FD' if is_black else '#E8F5E9'
        bd = '#90CAF9' if is_black else '#A5D6A7'

        tk.Label(dlg, text=title, bg='#FAFAFA',
                 font=f_title, fg=color).pack(pady=(pad, int(2 * S)))
        tk.Label(dlg,
                 text="通用规则不画框 · 所有分辨率都生效",
                 bg='#FAFAFA', font=f_hint, fg='#888'
                 ).pack(pady=(0, int(8 * S)))

        # 列表容器
        container = tk.Frame(dlg, bg='#FAFAFA')
        container.pack(fill=tk.BOTH, expand=True, padx=pad)

        canvas = tk.Canvas(container, bg='#FAFAFA', highlightthickness=0)
        sb = tk.Scrollbar(container, orient="vertical", command=canvas.yview)
        self.body = tk.Frame(canvas, bg='#FAFAFA')
        self.body.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.body, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self._canvas = canvas

        # 列表
        self.list_frame = tk.Frame(self.body, bg='#FFFFFF',
                                   highlightbackground=bd,
                                   highlightthickness=1)
        self.list_frame.pack(fill=tk.X, pady=(0, int(8 * S)))

        # 添加按钮
        tk.Button(self.body, text="＋ 添加通用规则",
                  command=self._on_add,
                  bg=bg, fg=color,
                  font=("微软雅黑", -max(11, int(12 * S)), "bold"),
                  relief='flat', padx=int(14 * S), pady=int(6 * S),
                  cursor='hand2').pack(pady=(0, int(8 * S)))

        # 底部按钮
        btn_frame = tk.Frame(dlg, bg='#FAFAFA')
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=pad, pady=int(10 * S))
        tk.Button(btn_frame, text="✓ 应用", command=self._on_apply,
                  bg='#4CAF50', fg='white',
                  font=("微软雅黑", -max(11, int(12 * S)), "bold"),
                  relief='flat', padx=int(20 * S), pady=int(6 * S),
                  cursor='hand2').pack(side=tk.RIGHT, padx=int(4 * S))
        tk.Button(btn_frame, text="✕ 取消", command=self._on_cancel,
                  bg='#F44336', fg='white',
                  font=("微软雅黑", -max(11, int(12 * S)), "bold"),
                  relief='flat', padx=int(20 * S), pady=int(6 * S),
                  cursor='hand2').pack(side=tk.RIGHT)

        self._refresh()
        dlg.protocol("WM_DELETE_WINDOW", self._on_cancel)
        dlg.bind("<Escape>", lambda e: self._on_cancel())

    def _refresh(self):
        S = self.scale
        f_text = ("微软雅黑", -max(10, int(11 * S)))
        f_mono = ("Consolas", -max(9, int(10 * S)))
        f_btn = ("微软雅黑", -max(9, int(10 * S)))
        f_tag = ("微软雅黑", -max(9, int(10 * S)), "bold")

        for w in self.list_frame.winfo_children():
            w.destroy()

        if not self.rules:
            tk.Label(self.list_frame,
                     text="（暂无通用规则，点下方按钮添加）",
                     bg='#FFFFFF', fg='#999', font=f_text,
                     pady=int(20 * S)).pack()
            return

        for idx, r in enumerate(self.rules):
            # 每条规则的卡片
            card = tk.Frame(self.list_frame, bg='#FFFFFF')
            card.pack(fill=tk.X, padx=int(6 * S), pady=int(4 * S))

            # 第 1 行：序号 + 名字 + 按钮
            row1 = tk.Frame(card, bg='#FFFFFF')
            row1.pack(fill=tk.X, padx=int(4 * S), pady=(int(3 * S), 0))
            tk.Label(row1, text=f"{idx+1}.",
                     bg='#FFFFFF', fg='#888',
                     font=f_text, width=3, anchor='w').pack(side=tk.LEFT)
            tk.Label(row1, text=r.get("name", "未命名"),
                     bg='#FFFFFF', fg='#333',
                     font=("微软雅黑", -max(11, int(12 * S)), "bold"),
                     anchor='w').pack(side=tk.LEFT)
            tk.Button(row1, text="删除", bg='#FFEBEE', fg='#C62828',
                      font=f_btn, relief='flat', padx=int(6 * S),
                      pady=int(1 * S), cursor='hand2',
                      command=lambda i=idx: self._on_delete(i)
                      ).pack(side=tk.RIGHT, padx=int(2 * S))
            tk.Button(row1, text="编辑", bg='#FFF3E0', fg='#E65100',
                      font=f_btn, relief='flat', padx=int(6 * S),
                      pady=int(1 * S), cursor='hand2',
                      command=lambda i=idx: self._on_edit(i)
                      ).pack(side=tk.RIGHT, padx=int(2 * S))

            # 第 2 行：匹配模式 + 断网秒数
            row2 = tk.Frame(card, bg='#FFFFFF')
            row2.pack(fill=tk.X, padx=int(4 * S))
            mode = r.get("match_mode", "contains")
            mode_label = {"contains": "包含", "equals": "相等",
                          "regex": "正则"}.get(mode, mode)
            tk.Label(row2, text=f"模式：{mode_label}",
                     bg='#FFFFFF', fg='#1565C0',
                     font=f_text, anchor='w').pack(side=tk.LEFT,
                                                    padx=(int(20 * S), 0))
            bt = r.get("block_time", None)
            if bt is not None:
                tk.Label(row2, text=f"断网：{bt} 秒",
                         bg='#FFFFFF', fg='#6A1B9A',
                         font=f_text, anchor='w').pack(side=tk.LEFT,
                                                        padx=int(8 * S))

            # 第 3 行：期望文字
            row3 = tk.Frame(card, bg='#FFFFFF')
            row3.pack(fill=tk.X, padx=int(4 * S))
            tk.Label(row3, text="期望：",
                     bg='#FFFFFF', fg='#2E7D32',
                     font=f_tag, anchor='w').pack(side=tk.LEFT,
                                                   padx=(int(20 * S), 0))
            ocr_text = r.get("ocr_text", "")
            display = ocr_text[:60] + ("…" if len(ocr_text) > 60 else "")
            tk.Label(row3, text=display if display else "（空）",
                     bg='#FFFFFF', fg='#333',
                     font=f_mono, anchor='w', justify='left'
                     ).pack(side=tk.LEFT, fill=tk.X, expand=True)

            # 第 4 行：否定词（可选）
            excl = (r.get("exclude_text") or "").strip()
            if excl:
                row4 = tk.Frame(card, bg='#FFFFFF')
                row4.pack(fill=tk.X, padx=int(4 * S))
                tk.Label(row4, text="否定：",
                         bg='#FFFFFF', fg='#C62828',
                         font=f_tag, anchor='w').pack(side=tk.LEFT,
                                                       padx=(int(20 * S), 0))
                tk.Label(row4, text=excl[:60],
                         bg='#FFFFFF', fg='#666',
                         font=f_mono, anchor='w').pack(side=tk.LEFT)

            # 第 5 行：备注（可选）
            note = (r.get("note") or "").strip()
            if note:
                row5 = tk.Frame(card, bg='#FFFFFF')
                row5.pack(fill=tk.X, padx=int(4 * S), pady=(0, int(3 * S)))
                tk.Label(row5, text="备注：",
                         bg='#FFFFFF', fg='#888',
                         font=f_tag, anchor='w').pack(side=tk.LEFT,
                                                       padx=(int(20 * S), 0))
                tk.Label(row5, text=note[:60],
                         bg='#FFFFFF', fg='#888',
                         font=f_text, anchor='w').pack(side=tk.LEFT)

            # 分隔线
            tk.Frame(card, bg='#EEEEEE', height=1).pack(
                fill=tk.X, padx=int(4 * S), pady=(int(3 * S), 0))


    def _on_add(self):
        self._show_edit(None, "添加通用规则")

    def _on_edit(self, idx):
        if 0 <= idx < len(self.rules):
            self._show_edit(idx, "编辑通用规则")

    def _on_delete(self, idx):
        if not (0 <= idx < len(self.rules)):
            return
        name = self.rules[idx].get("name", "")
        if messagebox.askyesno("确认删除",
                                f"确定删除通用规则「{name}」？",
                                parent=self.dlg):
            self.rules.pop(idx)
            self._refresh()

    def _show_edit(self, idx, title):
        S = self.scale
        f_text = ("微软雅黑", -max(11, int(12 * S)))
        f_mono = ("Consolas", -max(11, int(12 * S)))
        f_title = ("微软雅黑", -max(12, int(13 * S)), "bold")
        r = {} if idx is None else self.rules[idx]

        dlg = tk.Toplevel(self.dlg)
        dlg.title(title)
        dlg.attributes('-topmost', True)
        dlg.configure(bg='white')
        try:
            dlg.grab_set()
        except Exception:
            pass
        dlg.update_idletasks()
        sw = dlg.winfo_screenwidth()
        sh = dlg.winfo_screenheight()
        w = int(560 * S)
        h = min(int(620 * S), sh - int(60 * S))
        dlg.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
        dlg.lift()

        pad = int(14 * S)

        tk.Label(dlg, text="规则名字",
                 bg='white', font=f_title, fg='#6A1B9A', anchor='w'
                 ).pack(fill=tk.X, padx=pad, pady=(pad, 0))
        e_name = tk.Entry(dlg, font=f_text)
        e_name.pack(fill=tk.X, padx=pad, pady=(0, int(6 * S)))
        e_name.insert(0, r.get("name", ""))
        try:
            e_name.focus_set()
        except Exception:
            pass

        tk.Label(dlg, text="期望文字 / 正则",
                 bg='white', font=f_title, fg='#6A1B9A', anchor='w'
                 ).pack(fill=tk.X, padx=pad)
        t_text = tk.Text(dlg, font=f_mono, height=3, wrap='char',
                         relief='solid', bd=1)
        t_text.pack(fill=tk.X, padx=pad, pady=(0, int(6 * S)))
        t_text.insert("1.0", r.get("ocr_text", ""))

        tk.Label(dlg, text="否定词（可选）",
                 bg='white', font=f_title, fg='#C62828', anchor='w'
                 ).pack(fill=tk.X, padx=pad)
        t_excl = tk.Text(dlg, font=f_mono, height=2, wrap='char',
                         relief='solid', bd=1)
        t_excl.pack(fill=tk.X, padx=pad, pady=(0, int(6 * S)))
        t_excl.insert("1.0", r.get("exclude_text", ""))

        tk.Label(dlg, text="备注（可选）",
                 bg='white', font=f_title, fg='#6A1B9A', anchor='w'
                 ).pack(fill=tk.X, padx=pad)
        t_note = tk.Text(dlg, font=f_text, height=2, wrap='char',
                         relief='solid', bd=1)
        t_note.pack(fill=tk.X, padx=pad, pady=(0, int(6 * S)))
        t_note.insert("1.0", r.get("note", ""))

        tk.Label(dlg, text="匹配模式",
                 bg='white', font=f_title, fg='#6A1B9A', anchor='w'
                 ).pack(fill=tk.X, padx=pad)
        mode_var = tk.StringVar(value=r.get("match_mode", "contains"))
        mode_frame = tk.Frame(dlg, bg='white')
        mode_frame.pack(anchor='w', padx=pad, pady=(0, int(6 * S)))
        for val, label in [("contains", "包含"), ("equals", "完全相等"),
                            ("regex", "正则")]:
            tk.Radiobutton(mode_frame, text=label, variable=mode_var,
                            value=val, bg='white', font=f_text,
                            activebackground='white'
                            ).pack(side=tk.LEFT, padx=int(4 * S))

        tk.Label(dlg, text="断网秒数（留空 = OCR 默认秒数）",
                 bg='white', font=f_title, fg='#6A1B9A', anchor='w'
                 ).pack(fill=tk.X, padx=pad)
        bt_val = ""
        if isinstance(r.get("block_time"), (int, str))                 and r.get("block_time") != "":
            bt_val = str(r.get("block_time"))
        bt_var = tk.StringVar(value=bt_val)
        tk.Entry(dlg, textvariable=bt_var, font=f_mono, width=8
                 ).pack(anchor='w', padx=pad, pady=(0, int(8 * S)))

        def on_ok():
            name = e_name.get().strip() or "未命名"
            text = t_text.get("1.0", "end-1c").strip()
            excl = t_excl.get("1.0", "end-1c").strip()
            note = t_note.get("1.0", "end-1c").strip()
            mode = mode_var.get()
            bt_raw = bt_var.get().strip()
            bt = None
            if bt_raw:
                try:
                    bt = int(bt_raw)
                    if not (1 <= bt <= 1000):
                        raise ValueError
                except ValueError:
                    messagebox.showerror("错误", "断网秒数应为 1-1000",
                                          parent=dlg)
                    return
            new_r = {
                "name": name, "ocr_text": text,
                "match_mode": mode, "note": note,
                "exclude_text": excl,
            }
            if bt is not None:
                new_r["block_time"] = bt
            if idx is None:
                self.rules.append(new_r)
            else:
                self.rules[idx] = new_r
            dlg.destroy()
            self._refresh()

        def on_cancel():
            dlg.destroy()

        btn = tk.Frame(dlg, bg='white')
        btn.pack(side=tk.BOTTOM, fill=tk.X, padx=pad, pady=int(12 * S))
        tk.Button(btn, text="✓ 确定", command=on_ok, font=f_text,
                  bg='#4CAF50', fg='white', relief='flat',
                  padx=int(14 * S), pady=int(5 * S)
                  ).pack(side=tk.RIGHT, padx=int(4 * S))
        tk.Button(btn, text="✕ 取消", command=on_cancel, font=f_text,
                  bg='#F44336', fg='white', relief='flat',
                  padx=int(14 * S), pady=int(5 * S)
                  ).pack(side=tk.RIGHT)
        dlg.bind("<Escape>", lambda e: on_cancel())

    def _on_apply(self):
        self.result = deep_copy(self.rules)
        try:
            self.dlg.grab_release()
        except Exception:
            pass
        self.dlg.destroy()

    def _on_cancel(self):
        self.result = None
        try:
            self.dlg.grab_release()
        except Exception:
            pass
        self.dlg.destroy()

    def show(self):
        self.parent.wait_window(self.dlg)
        return self.result
