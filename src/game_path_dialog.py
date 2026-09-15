"""Game path config dialog - 自动检测系统语言"""
import locale
import os
import tkinter as tk
from tkinter import filedialog, messagebox

DEFAULT_EXE_HINT = "Night of the Full Moon.exe"
NL = chr(10)


def _detect_lang():
    try:
        lang = locale.getdefaultlocale()[0] or ""
        if lang.lower().startswith("zh"):
            return "zh"
    except Exception:
        pass
    return "en"


LANG = _detect_lang()

TEXT = {
    "zh": {
        "title_notfound": "未检测到游戏",
        "notfound_msg": "未检测到 ",
        "ask_fill": "是否要手动填写游戏路径？",
        "btn_fill": "填写路径",
        "btn_global": "整机断网",
        "btn_exit": "退出",
        "title_settings": "游戏路径设置",
        "label_exe_path": "游戏 exe 路径：",
        "btn_browse": "浏览…",
        "chk_sync": "启动时同步启动游戏（默认勾选）",
        "label_sync_path": "同步启动路径（与上方 exe 路径联动）：",
        "hint_exit_keep": "点退出不会删除已选路径，下次仍会记住",
        "ask_select_first": "请先选择游戏 exe 路径",
        "tip": "提示",
        "path_not_found": "路径不存在",
        "not_found_prefix": "这个路径找不到：",
        "save_anyway": "仍要保存吗？",
        "btn_save_launch": "保存并启动",
        "btn_save": "仅保存",
        "select_file_title": "选择游戏 exe 文件",
        "filetype_exe": "可执行文件",
        "filetype_all": "所有文件",
    },
    "en": {
        "title_notfound": "Game not found",
        "notfound_msg": "Not found: ",
        "ask_fill": "Fill game path manually?",
        "btn_fill": "Fill path",
        "btn_global": "Global block",
        "btn_exit": "Exit",
        "title_settings": "Game Path Settings",
        "label_exe_path": "Game exe path:",
        "btn_browse": "Browse…",
        "chk_sync": "Launch game on tool start",
        "label_sync_path": "Sync launch path (linked to exe path):",
        "hint_exit_keep": "Click Exit will not delete the path.",
        "ask_select_first": "Select game exe path first",
        "tip": "Tip",
        "path_not_found": "Path not found",
        "not_found_prefix": "Not found: ",
        "save_anyway": "Save anyway?",
        "btn_save_launch": "Save & Launch",
        "btn_save": "Save",
        "select_file_title": "Select game exe",
        "filetype_exe": "Executable",
        "filetype_all": "All files",
    },
}


def _t(key):
    d = TEXT.get(LANG, TEXT["en"])
    return d.get(key, TEXT["en"].get(key, ""))


class GamePathDialog:
    def __init__(self, root, scale=1.0, exe_hint=DEFAULT_EXE_HINT,
                 draft_path="", draft_sync=True):
        self.root = root
        self.scale = scale
        self.exe_hint = exe_hint
        self.result = None
        self._selected_path = draft_path or ""
        self._draft_sync = bool(draft_sync)
        self.dlg = None

    def show(self):
        act = self._ask_confirm()
        if act is None or act == "exit":
            return None
        if act == "global_mode":
            return {"path": "", "sync_launch": False, "sync_path": "",
                    "action": "global_mode"}
        return self._show_full()

    def _ask_confirm(self):
        S = self.scale
        dlg = tk.Toplevel(self.root)
        dlg.title(_t("title_notfound"))
        dlg.attributes('-topmost', True)
        dlg.resizable(False, False)
        dlg.configure(bg='white')
        try:
            dlg.grab_set()
        except Exception:
            pass
        pad = int(20 * S)
        f_title = ("Microsoft YaHei", -max(13, int(15 * S)), "bold")
        f_text = ("Microsoft YaHei", -max(11, int(12 * S)))
        f_btn = ("Microsoft YaHei", -max(11, int(12 * S)), "bold")
        tk.Label(dlg, text="!", bg='#FF9800', fg='white',
                 font=("Arial", -max(20, int(22 * S)), "bold"),
                 width=2, height=1).pack(pady=(pad, 0))
        tk.Label(dlg, text=_t("notfound_msg") + self.exe_hint,
                 bg='white', fg='#333', font=f_title).pack(pady=(int(8 * S), 0))
        tk.Frame(dlg, bg='#E0E0E0', height=1).pack(
            fill=tk.X, padx=pad, pady=int(8 * S))
        tk.Label(dlg, text=_t("ask_fill"),
                 bg='white', fg='#666', font=f_text).pack(pady=(0, int(12 * S)))
        btn_row = tk.Frame(dlg, bg='white')
        btn_row.pack(pady=(0, pad))
        chosen = {"v": None}

        def pick():
            chosen["v"] = "pick"
            dlg.destroy()

        def global_mode():
            chosen["v"] = "global_mode"
            dlg.destroy()

        def exit_app():
            chosen["v"] = "exit"
            dlg.destroy()

        tk.Button(btn_row, text=_t("btn_fill"), command=pick, bg='#4CAF50',
                  fg='white', font=f_btn, relief='flat',
                  padx=int(20 * S), pady=int(6 * S)
                  ).pack(side=tk.LEFT, padx=int(6 * S))
        tk.Button(btn_row, text=_t("btn_global"), command=global_mode,
                  bg='#FF9800', fg='white', font=f_btn, relief='flat',
                  padx=int(20 * S), pady=int(6 * S)
                  ).pack(side=tk.LEFT, padx=int(6 * S))
        tk.Button(btn_row, text=_t("btn_exit"), command=exit_app, bg='#9E9E9E',
                  fg='white', font=f_btn, relief='flat',
                  padx=int(20 * S), pady=int(6 * S)
                  ).pack(side=tk.LEFT)
        dlg.protocol("WM_DELETE_WINDOW", exit_app)
        dlg.bind("<Escape>", lambda e: exit_app())
        dlg.update_idletasks()
        w = dlg.winfo_reqwidth()
        h = dlg.winfo_reqheight()
        sw = dlg.winfo_screenwidth()
        sh = dlg.winfo_screenheight()
        dlg.geometry(str(w) + "x" + str(h) + "+" +
                     str((sw - w) // 2) + "+" + str((sh - h) // 2))
        self.root.wait_window(dlg)
        return chosen["v"] or "exit"

    def _pick_file(self, initial=""):
        try:
            kwargs = {
                "title": _t("select_file_title"),
                "filetypes": [(_t("filetype_exe"), "*.exe"),
                              (_t("filetype_all"), "*.*")],
                "parent": self.root,
            }
            if initial and os.path.isdir(os.path.dirname(initial)):
                kwargs["initialdir"] = os.path.dirname(initial)
                kwargs["initialfile"] = os.path.basename(initial)
            path = filedialog.askopenfilename(**kwargs)
        except Exception:
            path = ""
        return path or ""

    def _show_full(self):
        S = self.scale
        dlg = tk.Toplevel(self.root)
        dlg.title(_t("title_settings"))
        dlg.attributes('-topmost', True)
        dlg.configure(bg='white')
        try:
            dlg.grab_set()
        except Exception:
            pass
        pad = int(16 * S)
        f_title = ("Microsoft YaHei", -max(12, int(14 * S)), "bold")
        f_label = ("Microsoft YaHei", -max(10, int(11 * S)))
        f_hint = ("Microsoft YaHei", -max(9, int(10 * S)))
        f_path = ("Consolas", -max(9, int(10 * S)))
        f_btn = ("Microsoft YaHei", -max(10, int(11 * S)), "bold")

        title_bar = tk.Frame(dlg, bg='#1976D2')
        title_bar.pack(fill=tk.X)
        tk.Label(title_bar, text="  " + _t("title_settings"), bg='#1976D2',
                 fg='white', font=f_title, anchor='w'
                 ).pack(side=tk.LEFT, padx=int(10 * S), pady=int(6 * S))

        body = tk.Frame(dlg, bg='white')
        body.pack(fill=tk.BOTH, expand=True, padx=pad, pady=pad)

        tk.Label(body, text=_t("label_exe_path"), bg='white',
                 font=f_label, fg='#333', anchor='w').pack(fill=tk.X)
        path_frame = tk.Frame(body, bg='white')
        path_frame.pack(fill=tk.X, pady=(2, int(8 * S)))
        path_var = tk.StringVar(value=self._selected_path)
        tk.Entry(path_frame, textvariable=path_var, font=f_path,
                 relief='solid', bd=1).pack(side=tk.LEFT, fill=tk.X, expand=True)

        def browse_main():
            p = self._pick_file(initial=path_var.get().strip())
            if p:
                path_var.set(p)
                self._selected_path = p

        tk.Button(path_frame, text=_t("btn_browse"), command=browse_main,
                  font=f_label, bg='#E3F2FD', fg='#0D47A1',
                  relief='flat', padx=int(8 * S)
                  ).pack(side=tk.LEFT, padx=(int(4 * S), 0))

        tk.Frame(body, bg='#E0E0E0', height=1).pack(fill=tk.X, pady=int(6 * S))

        sync_var = tk.BooleanVar(value=self._draft_sync)
        tk.Checkbutton(body, text=_t("chk_sync"),
                       variable=sync_var, bg='white',
                       activebackground='white', selectcolor='white',
                       font=f_label, anchor='w', bd=0,
                       highlightthickness=0).pack(fill=tk.X)
        tk.Frame(body, bg='white', height=int(6 * S)).pack(fill=tk.X)

        tk.Label(body, text=_t("label_sync_path"),
                 bg='white', font=f_label, fg='#333', anchor='w'
                 ).pack(fill=tk.X, pady=(int(4 * S), 0))
        sync_path_frame = tk.Frame(body, bg='white')
        sync_path_frame.pack(fill=tk.X, pady=(2, int(8 * S)))
        sync_path_var = tk.StringVar(value=self._selected_path)
        sync_entry = tk.Entry(sync_path_frame, textvariable=sync_path_var,
                              font=f_path, relief='solid', bd=1)
        sync_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        state = {"sync_overridden": False}

        def on_sync_path_key(*_):
            state["sync_overridden"] = True

        def on_path_change(*_):
            if not state["sync_overridden"]:
                sync_path_var.set(path_var.get())

        sync_path_var.trace_add("write", on_sync_path_key)
        path_var.trace_add("write", on_path_change)

        def browse_sync():
            p = self._pick_file(initial=sync_path_var.get().strip())
            if p:
                state["sync_overridden"] = True
                sync_path_var.set(p)

        tk.Button(sync_path_frame, text=_t("btn_browse"), command=browse_sync,
                  font=f_label, bg='#E3F2FD', fg='#0D47A1',
                  relief='flat', padx=int(8 * S)
                  ).pack(side=tk.LEFT, padx=(int(4 * S), 0))

        def on_sync_toggle(*_):
            if sync_var.get():
                sync_entry.config(state='normal', bg='white',
                                   disabledbackground='white')
            else:
                sync_entry.config(state='disabled',
                                   disabledbackground='#EEEEEE')

        sync_var.trace_add("write", on_sync_toggle)

        tk.Label(body, text=_t("hint_exit_keep"),
                 bg='white', fg='#999', font=f_hint, anchor='w'
                 ).pack(fill=tk.X, pady=(int(4 * S), 0))

        btn_frame = tk.Frame(dlg, bg='#FAFAFA')
        btn_frame.pack(fill=tk.X, side=tk.BOTTOM)
        tk.Frame(btn_frame, bg='#E0E0E0', height=1).pack(fill=tk.X)
        btn_inner = tk.Frame(btn_frame, bg='#FAFAFA')
        btn_inner.pack(fill=tk.X, padx=pad, pady=int(8 * S))

        self.dlg = dlg

        def _clean_path(s):
            return s.strip().strip('"').strip("'").strip()

        def validate_main():
            p = _clean_path(path_var.get())
            if not p:
                messagebox.showwarning(_t("tip"), _t("ask_select_first"),
                                        parent=dlg)
                return None
            if not os.path.isfile(p):
                msg = _t("not_found_prefix") + NL + p + NL + NL + _t("save_anyway")
                if not messagebox.askyesno(_t("path_not_found"), msg, parent=dlg):
                    return None
            return p

        def do_save_and_launch():
            p = validate_main()
            if p is None:
                return
            self._selected_path = p
            self.result = {"path": p, "sync_launch": bool(sync_var.get()),
                           "sync_path": _clean_path(sync_path_var.get()) or p,
                           "action": "save_and_launch"}
            dlg.destroy()

        def do_save():
            p = validate_main()
            if p is None:
                return
            self._selected_path = p
            self.result = {"path": p, "sync_launch": bool(sync_var.get()),
                           "sync_path": _clean_path(sync_path_var.get()) or p,
                           "action": "save"}
            dlg.destroy()

        def do_exit():
            self.result = {"path": "", "sync_launch": bool(sync_var.get()),
                           "sync_path": "", "action": "exit",
                           "draft_path": _clean_path(path_var.get()),
                           "draft_sync": bool(sync_var.get())}
            dlg.destroy()

        tk.Button(btn_inner, text=_t("btn_exit"), command=do_exit, font=f_btn,
                  width=6, relief='flat', bg='#9E9E9E', fg='white',
                  activebackground='#757575'
                  ).pack(side=tk.RIGHT, padx=(int(4 * S), 0))
        tk.Button(btn_inner, text=_t("btn_save"), command=do_save, font=f_btn,
                  width=8, relief='flat', bg='#1976D2', fg='white',
                  activebackground='#0D47A1'
                  ).pack(side=tk.RIGHT, padx=(int(4 * S), 0))
        tk.Button(btn_inner, text=_t("btn_save_launch"),
                  command=do_save_and_launch, font=f_btn, width=12,
                  relief='flat', bg='#4CAF50', fg='white',
                  activebackground='#388E3C'
                  ).pack(side=tk.RIGHT)

        dlg.protocol("WM_DELETE_WINDOW", do_exit)
        dlg.update_idletasks()
        w = min(dlg.winfo_reqwidth() + int(8 * S),
                dlg.winfo_screenwidth() - int(40 * S))
        h = min(dlg.winfo_reqheight() + int(8 * S),
                dlg.winfo_screenheight() - int(60 * S))
        sw = dlg.winfo_screenwidth()
        sh = dlg.winfo_screenheight()
        dlg.geometry(str(w) + "x" + str(h) + "+" +
                     str((sw - w) // 2) + "+" + str((sh - h) // 2))
        self.root.wait_window(dlg)
        return self.result