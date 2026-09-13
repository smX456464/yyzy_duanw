"""ROI 调试叠加框：白名单绿框、黑名单蓝框
关键：使用 SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)
     让本窗口对 mss 截图不可见（人眼可见），避免遮挡 OCR
"""
import tkinter as tk
from .win_utils import _user32, GA_ROOT, set_window_capture_exclude
from .config_manager import rule_has_roi, rule_roi
from .win_utils import (get_pid_by_exe_name, get_hwnd_by_pid, is_window_alive,
                        is_window_visible, is_window_minimized, is_window_cloaked,
                        get_client_rect_screen)


class RoiOverlay:
    TRANSPARENT = "#FE01FE"

    def __init__(self, root, exe_name, scale=1.0, get_rules_cb=None,
                 show_labels=False):
        self.root = root
        self.exe_name = exe_name
        self.scale = scale
        self.get_rules_cb = get_rules_cb
        self.show_labels = bool(show_labels)
        self.top = None
        self.canvas = None
        self.hwnd = None
        self._job = None
        self._items = []

    def show(self):
        if self.top is not None and self.top.winfo_exists():
            self.top.deiconify()
            self.top.lift()
            return
        top = tk.Toplevel(self.root)
        top.overrideredirect(True)
        top.attributes('-topmost', True)
        top.configure(bg=self.TRANSPARENT)
        try:
            top.attributes('-transparentcolor', self.TRANSPARENT)
        except Exception:
            pass
        self.canvas = tk.Canvas(top, bg=self.TRANSPARENT,
                                highlightthickness=0, bd=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.top = top
        try:
            raw = top.winfo_id()
            self.hwnd = _user32.GetAncestor(raw, GA_ROOT) or raw
        except Exception:
            self.hwnd = None

        # 关键：让本窗口从屏幕捕获中排除
        if self.hwnd:
            ok = set_window_capture_exclude(self.hwnd)
            if ok:
                print(f"👁 调试叠加框已显示 hwnd={self.hwnd}（已从屏幕捕获排除）",
                      flush=True)
            else:
                print(f"👁 调试叠加框已显示 hwnd={self.hwnd}"
                      f"（当前系统不支持捕获排除，OCR 可能受遮挡影响）",
                      flush=True)
        else:
            print("👁 调试叠加框已显示（无 hwnd，无法设置捕获排除）", flush=True)
        self._tick_update()

    def hide(self):
        if self._job:
            try: self.root.after_cancel(self._job)
            except Exception: pass
            self._job = None
        if self.top is not None and self.top.winfo_exists():
            try: self.top.destroy()
            except Exception: pass
        self.top = None
        self.hwnd = None
        self._items = []

    def _tick_update(self):
        if self.top is None or not self.top.winfo_exists():
            return
        try:
            pid = get_pid_by_exe_name(self.exe_name)
            hwnd = get_hwnd_by_pid(pid) if pid else None
            shown = False
            if (hwnd and is_window_alive(hwnd)
                    and is_window_visible(hwnd)
                    and not is_window_minimized(hwnd)
                    and not is_window_cloaked(hwnd)):
                l, t, r, b = get_client_rect_screen(hwnd)
                cw, ch = r - l, b - t
                if cw > 0 and ch > 0:
                    size_key = f"{cw}x{ch}"
                    rules = self._find_rules_for_size(size_key)
                    if rules:
                        self._draw_all(l, t, cw, ch, rules)
                        shown = True
            if not shown:
                self._clear_all()
        except Exception as e:
            print(f"👁 调试叠加框刷新失败: {e}", flush=True)
        self._job = self.root.after(300, self._tick_update)

    def _clear_all(self):
        try: self.top.geometry("1x1+0+0")
        except Exception: pass
        for item in self._items:
            for it in item:
                try: self.canvas.delete(it)
                except Exception: pass
        self._items = []

    def _draw_all(self, base_x, base_y, cw, ch, rules):
        boxes = []
        wl = rules.get("whitelist", [])
        if isinstance(wl, list):
            for r in wl:
                if not rule_has_roi(r): continue
                x1, y1, x2, y2 = rule_roi(r)
                boxes.append({
                    "bx": base_x + int(cw * x1),
                    "by": base_y + int(ch * y1),
                    "bw": max(4, int(cw * (x2 - x1))),
                    "bh": max(4, int(ch * (y2 - y1))),
                    "color": "#4CAF50",
                    "label": f"WL:{r.get('name','')}",
                })
        bl = rules.get("blacklist", [])
        if isinstance(bl, list):
            for r in bl:
                if not rule_has_roi(r): continue
                x1, y1, x2, y2 = rule_roi(r)
                boxes.append({
                    "bx": base_x + int(cw * x1),
                    "by": base_y + int(ch * y1),
                    "bw": max(4, int(cw * (x2 - x1))),
                    "bh": max(4, int(ch * (y2 - y1))),
                    "color": "#2196F3",
                    "label": f"BL:{r.get('name','')}",
                })
        if not boxes:
            self._clear_all(); return

        min_x = min(b["bx"] for b in boxes)
        min_y = min(b["by"] for b in boxes)
        max_x = max(b["bx"] + b["bw"] for b in boxes)
        max_y = max(b["by"] + b["bh"] for b in boxes)
        pad = max(3, int(4 * self.scale))
        try:
            self.top.geometry(
                f"{max_x - min_x + pad * 2}x{max_y - min_y + pad * 2}"
                f"+{min_x - pad}+{min_y - pad}")
        except Exception:
            return

        bw_line = max(2, int(2 * self.scale))
        lbl_font = ("微软雅黑", -max(10, int(11 * self.scale)), "bold")

        while len(self._items) < len(boxes):
            rect_id = self.canvas.create_rectangle(
                0, 0, 0, 0, outline='#FF3B30', width=bw_line, fill='')
            lbl_bg_id = self.canvas.create_rectangle(
                0, 0, 0, 0, fill='#FFFFFF', outline='#333', width=1)
            lbl_txt_id = self.canvas.create_text(
                0, 0, text='', anchor='nw', fill='#333', font=lbl_font)
            self._items.append((rect_id, lbl_bg_id, lbl_txt_id))

        for i, b in enumerate(boxes):
            rx0 = b["bx"] - (min_x - pad)
            ry0 = b["by"] - (min_y - pad)
            rx1 = rx0 + b["bw"]
            ry1 = ry0 + b["bh"]
            rect_id, lbl_bg_id, lbl_txt_id = self._items[i]
            self.canvas.coords(rect_id, rx0, ry0, rx1, ry1)
            self.canvas.itemconfig(rect_id, outline=b["color"], state='normal')

            if self.show_labels:
                self.canvas.itemconfig(lbl_txt_id, text=b["label"],
                                       fill=b["color"], state='normal')
                self.canvas.coords(lbl_txt_id, rx0 + int(4 * self.scale),
                                   ry0 - int(16 * self.scale))
                bbox = self.canvas.bbox(lbl_txt_id)
                if bbox:
                    bx0, by0, bx1, by1 = bbox
                    self.canvas.coords(lbl_bg_id, bx0 - 2, by0 - 1, bx1 + 2, by1 + 1)
                    self.canvas.itemconfig(lbl_bg_id, fill='#FFFFFF',
                                           outline=b["color"], width=1, state='normal')
                else:
                    self.canvas.itemconfig(lbl_bg_id, state='hidden')
                self.canvas.tag_raise(lbl_bg_id)
                self.canvas.tag_raise(lbl_txt_id)
            else:
                self.canvas.itemconfig(lbl_txt_id, state='hidden')
                self.canvas.itemconfig(lbl_bg_id, state='hidden')

        for i in range(len(boxes), len(self._items)):
            for it in self._items[i]:
                try: self.canvas.itemconfig(it, state='hidden')
                except Exception: pass

    def _find_rules_for_size(self, size_key):
        if self.get_rules_cb is None: return None
        try:
            rules_all = self.get_rules_cb()
            if not isinstance(rules_all, dict): return None
            # 只精确匹配，不回退 default
            if size_key in rules_all: return rules_all[size_key]
        except Exception:
            pass
        return None
