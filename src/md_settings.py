"""文本查看窗口设置对话框"""
import tkinter as tk
from tkinter import colorchooser, messagebox


class MdSettingsDialog:
    def __init__(self, parent_app, scale=1.0):
        self.app = parent_app
        self.parent = parent_app.root
        self.scale = scale
        self.result = None
        self.dlg = None
        self._build()

    def _build(self):
        S = self.scale
        mw = self.app.config.get("ui", {}).get("md_window", {})
        self._initial = {
            "width": int(mw.get("width", 400)),
            "height": int(mw.get("height", 300)),
            "font_family": mw.get("font_family", "微软雅黑"),
            "font_size": int(mw.get("font_size", 10)),
            "font_color": mw.get("font_color", "#000000"),
            "bg_color": mw.get("bg_color", "#FFFFFF"),
        }

        self.dlg = tk.Toplevel(self.parent)
        self.dlg.title("文本查看窗口设置")
        self.dlg.attributes('-topmost', True)
        self.dlg.configure(bg='#FAFAFA')
        self.dlg.resizable(False, False)
        try: self.dlg.grab_set()
        except Exception: pass

        w, h = int(440 * S), int(440 * S)
        self.dlg.update_idletasks()
        sw = self.dlg.winfo_screenwidth()
        sh = self.dlg.winfo_screenheight()
        self.dlg.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

        pad = int(16 * S)
        f_title = ("微软雅黑", -max(14, int(16 * S)), "bold")
        f_text = ("微软雅黑", -max(11, int(12 * S)))
        f_btn = ("微软雅黑", -max(11, int(12 * S)))
        f_mono = ("Consolas", -max(10, int(11 * S)))

        tk.Label(self.dlg, text="📄 文本查看窗口设置", bg='#FAFAFA',
                 font=f_title, fg='#1976D2').pack(pady=(pad, int(4 * S)))
        tk.Label(self.dlg, text="长按 📄 打开此窗口；短按 📄 打开文本",
                 bg='#FAFAFA', font=("微软雅黑", -max(10, int(11 * S))),
                 fg='#888').pack(pady=(0, int(8 * S)))

        form = tk.Frame(self.dlg, bg='#FAFAFA')
        form.pack(fill=tk.X, padx=pad)

        self.vars = {}

        def add_row(label, key, width=20):
            row = tk.Frame(form, bg='#FAFAFA')
            row.pack(fill=tk.X, pady=int(4 * S))
            tk.Label(row, text=label, bg='#FAFAFA', font=f_text,
                     width=10, anchor='w').pack(side=tk.LEFT)
            var = tk.StringVar(value=str(self._initial[key]))
            entry = tk.Entry(row, textvariable=var, font=f_mono, width=width)
            entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
            self.vars[key] = var

        add_row("宽度 px", "width")
        add_row("高度 px", "height")
        add_row("字体", "font_family")
        add_row("字号", "font_size")

        self._color_row(form, "文字颜色", "font_color", f_text, f_mono, S)
        self._color_row(form, "背景颜色", "bg_color", f_text, f_mono, S)

        btn = tk.Frame(self.dlg, bg='#FAFAFA')
        btn.pack(side=tk.BOTTOM, fill=tk.X, padx=pad, pady=int(14 * S))
        tk.Button(btn, text="✓ 保存", command=self._on_ok,
                  bg='#4CAF50', fg='white', font=f_btn,
                  relief='flat', padx=int(20 * S), pady=int(6 * S)
                  ).pack(side=tk.RIGHT, padx=int(4 * S))
        tk.Button(btn, text="✕ 取消", command=self._on_cancel,
                  bg='#F44336', fg='white', font=f_btn,
                  relief='flat', padx=int(20 * S), pady=int(6 * S)
                  ).pack(side=tk.RIGHT)

        self.dlg.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.dlg.bind("<Escape>", lambda e: self._on_cancel())

    def _color_row(self, parent, label, key, f_text, f_mono, S):
        row = tk.Frame(parent, bg='#FAFAFA')
        row.pack(fill=tk.X, pady=int(4 * S))
        tk.Label(row, text=label, bg='#FAFAFA', font=f_text,
                 width=10, anchor='w').pack(side=tk.LEFT)
        var = tk.StringVar(value=str(self._initial[key]))
        self.vars[key] = var
        entry = tk.Entry(row, textvariable=var, font=f_mono, width=12)
        entry.pack(side=tk.LEFT)
        preview = tk.Label(row, text="   ", bg=var.get(), width=3,
                           relief='solid', bd=1)
        preview.pack(side=tk.LEFT, padx=int(4 * S))

        def pick_color():
            c = colorchooser.askcolor(color=var.get(),
                                      title=f"选择{label}",
                                      parent=self.dlg)
            if c and c[1]:
                var.set(c[1])
                try: preview.config(bg=c[1])
                except Exception: pass

        tk.Button(row, text="选色", command=pick_color, font=f_text,
                  relief='flat', bg='#E3F2FD', fg='#0D47A1',
                  padx=int(6 * S)).pack(side=tk.LEFT)

        def on_change(*_):
            try: preview.config(bg=var.get())
            except Exception: pass
        var.trace_add("write", on_change)

    def _on_ok(self):
        try:
            w = int(self.vars["width"].get())
            h = int(self.vars["height"].get())
            fs = int(self.vars["font_size"].get())
        except ValueError:
            messagebox.showerror("错误", "宽、高、字号必须是整数", parent=self.dlg)
            return
        if not (100 <= w <= 2000 and 100 <= h <= 2000):
            messagebox.showerror("错误", "宽高应在 100~2000 之间", parent=self.dlg)
            return
        if not (6 <= fs <= 72):
            messagebox.showerror("错误", "字号应在 6~72 之间", parent=self.dlg)
            return

        self.result = {
            "width": w, "height": h,
            "font_family": self.vars["font_family"].get().strip() or "微软雅黑",
            "font_size": fs,
            "font_color": self.vars["font_color"].get().strip() or "#000000",
            "bg_color": self.vars["bg_color"].get().strip() or "#FFFFFF",
        }
        try: self.dlg.grab_release()
        except Exception: pass
        self.dlg.destroy()

    def _on_cancel(self):
        self.result = None
        try: self.dlg.grab_release()
        except Exception: pass
        self.dlg.destroy()

    def show(self):
        self.parent.wait_window(self.dlg)
        return self.result
