"""音量控制设置对话框：SoundVolumeView 路径 + 静音值"""
import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox


class VolumeSettingsDialog:
    def __init__(self, parent_app, scale=1.0):
        self.app = parent_app
        self.parent = parent_app.root
        self.scale = scale
        self.result = None
        self.dlg = None
        self._build()

    def _build(self):
        S = self.scale
        cfg = self.app.config
        iw = cfg.get("img_watch", {})
        self._initial = {
            "sound_volume_view_path": cfg.get("sound_volume_view_path", ""),
            "volume_mute_value": int(cfg.get("volume_mute_value", 0)),
            "auto_mute_when_hidden": bool(iw.get("auto_mute_when_hidden", False)),
        }
        dlg = tk.Toplevel(self.parent)
        dlg.title("音量控制设置")
        dlg.attributes('-topmost', True)
        dlg.configure(bg='#FAFAFA')
        dlg.resizable(False, False)
        w, h = int(600 * S), int(410 * S)
        dlg.update_idletasks()
        sw = dlg.winfo_screenwidth(); sh = dlg.winfo_screenheight()
        if h > sh - int(40 * S): h = sh - int(40 * S)
        dlg.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
        dlg.lift()
        dlg.focus_force()
        try:
            dlg.grab_set()
        except Exception:
            pass
        self.dlg = dlg

        pad = int(16 * S)
        f_title = ("微软雅黑", -max(13, int(15 * S)), "bold")
        f_text = ("微软雅黑", -max(11, int(12 * S)))
        f_hint = ("微软雅黑", -max(10, int(11 * S)))
        f_mono = ("Consolas", -max(11, int(12 * S)))

        tk.Label(dlg, text="🔊 音量控制设置", bg='#FAFAFA',
                 font=f_title, fg='#1976D2').pack(pady=(pad, int(2 * S)))
        tk.Label(dlg,
                 text="依赖外部工具 SoundVolumeView.exe（NirSoft 免费工具）",
                 bg='#FAFAFA', font=f_hint, fg='#888'
                 ).pack(pady=(0, int(10 * S)))

        tk.Label(dlg, text="SoundVolumeView.exe 路径",
                 bg='#FAFAFA', font=f_text, anchor='w'
                 ).pack(fill=tk.X, padx=pad)
        path_row = tk.Frame(dlg, bg='#FAFAFA')
        path_row.pack(fill=tk.X, padx=pad, pady=(int(2 * S), int(8 * S)))

        tk.Button(dlg, text="\u2b07 自动下载 SoundVolumeView",
                  command=self._on_download,
                  bg='#4CAF50', fg='white', relief='flat',
                  font=("微软雅黑", -max(11, int(12 * S)), "bold"),
                  padx=int(12 * S), pady=int(5 * S)
                  ).pack(pady=(int(4 * S), int(8 * S)))
        self.var_path = tk.StringVar(value=self._initial["sound_volume_view_path"])
        tk.Entry(path_row, textvariable=self.var_path, font=f_mono
                 ).pack(side=tk.LEFT, fill=tk.X, expand=True)

        def browse():
            p = filedialog.askopenfilename(
                title="选择 SoundVolumeView.exe",
                filetypes=[("Executable", "*.exe"), ("All files", "*.*")],
                parent=dlg)
            if p:
                self.var_path.set(p)
        tk.Button(path_row, text="浏览…", command=browse,
                  font=f_text, bg='#E3F2FD', fg='#0D47A1',
                  relief='flat', padx=int(10 * S)
                  ).pack(side=tk.LEFT, padx=(int(4 * S), 0))

        tk.Label(dlg, text="静音时把音量调到多少（0~100）",
                 bg='#FAFAFA', font=f_text, anchor='w'
                 ).pack(fill=tk.X, padx=pad)
        self.var_mute = tk.StringVar(value=str(self._initial["volume_mute_value"]))
        tk.Entry(dlg, textvariable=self.var_mute, font=f_mono, width=10
                 ).pack(anchor='w', padx=pad, pady=(int(2 * S), int(6 * S)))

        self.var_auto_mute = tk.BooleanVar(
            value=self._initial["auto_mute_when_hidden"])
        tk.Checkbutton(dlg,
                       text="游戏窗口不在画面中时自动静音（回来恢复）",
                       variable=self.var_auto_mute,
                       bg='#FAFAFA', activebackground='#FAFAFA',
                       selectcolor='#FAFAFA', font=f_text,
                       anchor='w').pack(fill=tk.X, padx=pad,
                                        pady=(int(2 * S), int(8 * S)))

        hint = tk.Frame(dlg, bg='#FFF3E0',
                        highlightbackground='#FFB74D', highlightthickness=1)
        hint.pack(fill=tk.X, padx=pad, pady=(0, int(8 * S)))
        tk.Label(hint,
                 text="💡 短按 🔊 切换静音 / 恢复\n"
                      "💡 长按 🔊 打开此设置\n"
                      "💡 路径留空 → 关闭音量功能",
                 bg='#FFF3E0', fg='#E65100', font=f_hint,
                 justify='left', anchor='w'
                 ).pack(fill=tk.X, padx=int(8 * S), pady=int(6 * S))

        btn = tk.Frame(dlg, bg='#FAFAFA')
        btn.pack(side=tk.BOTTOM, fill=tk.X, padx=pad, pady=int(12 * S))
        tk.Button(btn, text="✓ 保存", command=self._on_ok,
                  bg='#4CAF50', fg='white', font=f_text,
                  relief='flat', padx=int(20 * S), pady=int(6 * S)
                  ).pack(side=tk.RIGHT, padx=int(4 * S))
        tk.Button(btn, text="✕ 取消", command=self._on_cancel,
                  bg='#F44336', fg='white', font=f_text,
                  relief='flat', padx=int(20 * S), pady=int(6 * S)
                  ).pack(side=tk.RIGHT)

        dlg.protocol("WM_DELETE_WINDOW", self._on_cancel)
        dlg.bind("<Escape>", lambda e: self._on_cancel())

    def _on_download(self):
        """弹出下载对话框：下载 SoundVolumeView 到 soundvolumeview/"""
        from .downloader import is_installed, get_exe_path
        if is_installed():
            p = get_exe_path()
            self.var_path.set(p)
            messagebox.showinfo("已安装",
                                f"SoundVolumeView 已在：\n{p}",
                                parent=self.dlg)
            return
        if not messagebox.askyesno(
                "下载 SoundVolumeView",
                "将从 nirsoft.net 下载约 200KB，\n"
                "解压到 soundvolumeview\\ 子目录。\n\n"
                "是否继续？",
                parent=self.dlg):
            return

        S = self.scale
        prog_dlg = tk.Toplevel(self.dlg)
        prog_dlg.title("下载中...")
        prog_dlg.attributes('-topmost', True)
        prog_dlg.configure(bg='white')
        prog_dlg.resizable(False, False)
        w, h = int(420 * S), int(180 * S)
        prog_dlg.update_idletasks()
        sw = prog_dlg.winfo_screenwidth()
        sh = prog_dlg.winfo_screenheight()
        prog_dlg.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

        tk.Label(prog_dlg, text="正在下载 SoundVolumeView...",
                 bg='white',
                 font=("微软雅黑", -max(12, int(13 * S)), "bold"),
                 fg='#1976D2').pack(pady=(int(16 * S), int(4 * S)))

        status_var = tk.StringVar(value="准备中...")
        tk.Label(prog_dlg, textvariable=status_var, bg='white',
                 font=("微软雅黑", -max(10, int(11 * S))),
                 fg='#666').pack()

        bar_canvas = tk.Canvas(prog_dlg, width=int(360 * S),
                               height=int(24 * S), bg='#E0E0E0',
                               highlightthickness=1,
                               highlightbackground='#BDBDBD')
        bar_canvas.pack(pady=int(10 * S))
        bar_rect = bar_canvas.create_rectangle(
            0, 0, 0, int(24 * S), fill='#4CAF50', outline='')

        cancel_event = threading.Event()
        result = {"ok": False, "msg": "", "path": None}

        def on_progress(done, total):
            try:
                if not prog_dlg.winfo_exists():
                    return
                if total > 0:
                    pct = done / total
                    bar_canvas.coords(bar_rect, 0, 0,
                                      int(360 * S * pct), int(24 * S))
                    status_var.set(
                        f"已下载 {done // 1024} KB / {total // 1024} KB "
                        f"({pct * 100:.0f}%)")
                else:
                    status_var.set(f"已下载 {done // 1024} KB")
            except Exception:
                pass

        def worker():
            from .downloader import download_and_install
            ok, msg = download_and_install(progress_cb=on_progress,
                                           cancel_event=cancel_event)
            result["ok"] = ok
            result["msg"] = msg
            result["path"] = msg if ok else None
            try:
                prog_dlg.after(0, finish)
            except Exception:
                pass

        def finish():
            try:
                prog_dlg.destroy()
            except Exception:
                pass
            if result["ok"]:
                self.var_path.set(result["path"])
                messagebox.showinfo(
                    "下载成功",
                    f"SoundVolumeView 已安装到：\n{result['path']}",
                    parent=self.dlg)
            else:
                messagebox.showerror(
                    "下载失败",
                    f"{result['msg']}\n\n"
                    "你可以手动下载：\n"
                    "https://www.nirsoft.net/utils/"
                    "soundvolumeview-x64.zip",
                    parent=self.dlg)

        def on_close():
            cancel_event.set()
        prog_dlg.protocol("WM_DELETE_WINDOW", on_close)
        threading.Thread(target=worker, daemon=True).start()

    def _on_ok(self):
        path = self.var_path.get().strip()
        # 去掉 Windows 资源管理器"复制为路径"带来的外层引号
        for _ in range(3):
            if len(path) >= 2 and path[0] == path[-1] and path[0] in ('"', "'"):
                path = path[1:-1].strip()
            else:
                break
        try:
            mute = int(self.var_mute.get().strip())
        except ValueError:
            messagebox.showerror("错误", "静音值必须是整数 0~100", parent=self.dlg)
            return
        if not (0 <= mute <= 100):
            messagebox.showerror("错误", "静音值必须在 0~100 之间", parent=self.dlg)
            return
        # 路径非空时，做个存在性检查（不存在就警告，允许继续保存）
        if path and not os.path.exists(path):
            if not messagebox.askyesno(
                    "路径不存在",
                    f"这个路径找不到：\n{path}\n\n是否仍要保存？",
                    parent=self.dlg):
                return
        self.result = {
            "sound_volume_view_path": path,
            "volume_mute_value": mute,
            "auto_mute_when_hidden": bool(self.var_auto_mute.get()),
        }
        self.dlg.destroy()

    def _on_cancel(self):
        self.result = None
        self.dlg.destroy()

    def show(self):
        try:
            if self.dlg is not None and self.dlg.winfo_exists():
                self.parent.wait_window(self.dlg)
        except Exception:
            pass
        return self.result

class VolumeWizardDialog:
    """音量功能向导：路径未绑定时，短按 🔊 弹出。

    四个选项：
      1. 下载 SoundVolumeView
      2. 稍后（关闭，不做任何事）
      3. 填写本地 SoundVolumeView 路径
      4. 关闭这个功能（禁用音量按钮）
    """

    def __init__(self, parent_app, scale=1.0):
        self.app = parent_app
        self.parent = parent_app.root
        self.scale = scale
        self.action = None   # 'download' | 'later' | 'manual' | 'disable'
        self.dlg = None
        self._build()

    def _build(self):
        S = self.scale
        dlg = tk.Toplevel(self.parent)
        dlg.title("音量功能未配置")
        dlg.attributes('-topmost', True)
        dlg.configure(bg='#FAFAFA')
        dlg.resizable(False, False)
        try: dlg.grab_set()
        except Exception: pass

        w, h = int(500 * S), int(340 * S)
        dlg.update_idletasks()
        sw = dlg.winfo_screenwidth()
        sh = dlg.winfo_screenheight()
        dlg.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
        dlg.lift()
        dlg.focus_force()
        try:
            dlg.grab_set()
        except Exception:
            pass

        pad = int(18 * S)
        f_title = ("微软雅黑", -max(13, int(15 * S)), "bold")
        f_text = ("微软雅黑", -max(11, int(12 * S)))
        f_hint = ("微软雅黑", -max(10, int(11 * S)))

        tk.Label(dlg, text="🔊 音量功能尚未配置",
                 bg='#FAFAFA', font=f_title, fg='#1976D2'
                 ).pack(pady=(pad, int(6 * S)))
        tk.Label(dlg,
                 text="未找到 SoundVolumeView.exe。\n"
                      "你可以选择以下方式之一：",
                 bg='#FAFAFA', font=f_text, fg='#555',
                 justify='center').pack(pady=(0, int(14 * S)))

        # ---- 四个按钮 ----
        def make_btn(text, action, color, hover, fg='white'):
            b = tk.Button(dlg, text=text,
                          command=lambda a=action: self._choose(a),
                          bg=color, fg=fg, activebackground=hover,
                          activeforeground=fg,
                          font=("微软雅黑", -max(11, int(12 * S)), "bold"),
                          relief='flat', width=36,
                          padx=int(10 * S), pady=int(6 * S),
                          cursor='hand2')
            b.pack(pady=int(3 * S))
            return b

        make_btn("⬇  下载 SoundVolumeView", "download",
                 "#4CAF50", "#388E3C")
        make_btn("📂  填写本地 SoundVolumeView 路径", "manual",
                 "#1976D2", "#0D47A1")
        make_btn("⏰  稍后（关闭）", "later",
                 "#9E9E9E", "#757575")
        make_btn("🚫  关闭这个功能（不再提示）", "disable",
                 "#F44336", "#C62828")

        dlg.protocol("WM_DELETE_WINDOW", lambda: self._choose("later"))
        dlg.bind("<Escape>", lambda e: self._choose("later"))
        self.dlg = dlg

    def _choose(self, action):
        self.action = action
        try:
            self.dlg.grab_release()
        except Exception:
            pass
        try:
            self.dlg.destroy()
        except Exception:
            pass

    def show(self):
        try:
            if self.dlg is not None and self.dlg.winfo_exists():
                self.parent.wait_window(self.dlg)
        except Exception:
            pass
        return self.action
