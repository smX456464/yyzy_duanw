"""鼠标框选器（双窗口：半透明遮罩 + 不透明 UI 层）"""
import tkinter as tk
from .win_utils import _user32, GA_ROOT, set_click_through


class RegionSelector:
    TRANSPARENT = "#FE01FE"
    HANDLE_SIZE = 8
    HANDLE_HIT = 14
    BTN_W = 70
    BTN_H = 34
    BTN_GAP = 12
    BTN_OFFSET = 20
    SCREEN_MARGIN = 10

    def __init__(self, root, hint_text, on_done, on_cancel=None, scale=1.0):
        self.root = root
        self.hint_text = hint_text
        self.on_done = on_done
        self.on_cancel = on_cancel
        self.scale = scale
        self.mask_top = None
        self.ui_top = None
        self.mask_canvas = None
        self.ui_canvas = None
        self.hint_id = None
        self.rect_id = None
        self.size_text_id = None
        self.handle_ids = []
        self.btn_confirm_bg = None
        self.btn_confirm_txt = None
        self.btn_cancel_bg = None
        self.btn_cancel_txt = None
        self._btn_rects = {}
        self.rect_x0 = None
        self.rect_y0 = None
        self.rect_x1 = None
        self.rect_y1 = None
        self.mode = None
        self.drag_anchor = None
        self.resize_corner = None
        self.corners_visible = False
        self.sw = 0
        self.sh = 0
        self.active = False

    def show(self):
        if self.mask_top is not None and self.mask_top.winfo_exists():
            return

        # ---- 1. 半透明遮罩（承接鼠标事件）----
        mask_top = tk.Toplevel(self.root)
        mask_top.overrideredirect(True)
        mask_top.attributes('-topmost', True)
        try:
            mask_top.attributes('-alpha', 0.15)
        except Exception:
            pass
        mask_top.configure(bg='#000000')
        self.sw = mask_top.winfo_screenwidth()
        self.sh = mask_top.winfo_screenheight()
        mask_top.geometry(f"{self.sw}x{self.sh}+0+0")
        self.mask_canvas = tk.Canvas(mask_top, bg='#000000',
                                     highlightthickness=0, bd=0)
        self.mask_canvas.pack(fill=tk.BOTH, expand=True)

        # ---- 2. 不透明 UI 层（100%，鼠标穿透）----
        ui_top = tk.Toplevel(self.root)
        ui_top.overrideredirect(True)
        ui_top.attributes('-topmost', True)
        ui_top.configure(bg=self.TRANSPARENT)
        try:
            ui_top.attributes('-transparentcolor', self.TRANSPARENT)
        except Exception:
            pass
        ui_top.geometry(f"{self.sw}x{self.sh}+0+0")
        self.ui_canvas = tk.Canvas(ui_top, bg=self.TRANSPARENT,
                                   highlightthickness=0, bd=0)
        self.ui_canvas.pack(fill=tk.BOTH, expand=True)
        try:
            ui_top.update_idletasks()
            raw = ui_top.winfo_id()
            top_hwnd = _user32.GetAncestor(raw, GA_ROOT) or raw
            set_click_through(top_hwnd)
        except Exception:
            pass

        hint_size = -max(14, int(22 * self.scale))
        self.hint_id = self.ui_canvas.create_text(
            self.sw // 2, self.sh // 2,
            text=self.hint_text, fill='#FFFFFF',
            font=("微软雅黑", hint_size, "bold"))

        # ---- 3. 事件绑定 ----
        self.mask_canvas.bind("<ButtonPress-1>", self._on_press)
        self.mask_canvas.bind("<B1-Motion>", self._on_drag)
        self.mask_canvas.bind("<ButtonRelease-1>", self._on_release)
        self.mask_canvas.bind("<Motion>", self._on_motion)
        mask_top.bind("<Escape>", lambda e: self._cancel())

        # 关键修复：确保遮罩拿到键盘/鼠标焦点
        mask_top.lift()
        mask_top.attributes('-topmost', True)
        mask_top.focus_force()
        try:
            mask_top.grab_set()
        except Exception:
            pass
        # 再强一次
        mask_top.after(50, lambda: mask_top.focus_force() if mask_top.winfo_exists() else None)

        self.mask_top = mask_top
        self.ui_top = ui_top
        self.active = True
        print("🔲 已进入框选模式（左键拖拽画框 · ESC 取消）", flush=True)

    def _inside_rect(self, x, y):
        if None in (self.rect_x0, self.rect_y0, self.rect_x1, self.rect_y1):
            return False
        x0 = min(self.rect_x0, self.rect_x1)
        x1 = max(self.rect_x0, self.rect_x1)
        y0 = min(self.rect_y0, self.rect_y1)
        y1 = max(self.rect_y0, self.rect_y1)
        return (x0 <= x <= x1) and (y0 <= y <= y1)

    def _hit_corner(self, x, y):
        if None in (self.rect_x0, self.rect_y0, self.rect_x1, self.rect_y1):
            return None
        x0 = min(self.rect_x0, self.rect_x1)
        x1 = max(self.rect_x0, self.rect_x1)
        y0 = min(self.rect_y0, self.rect_y1)
        y1 = max(self.rect_y0, self.rect_y1)
        r = self.HANDLE_HIT * self.scale
        for name, (cx, cy) in [('nw', (x0, y0)), ('ne', (x1, y0)),
                               ('sw', (x0, y1)), ('se', (x1, y1))]:
            if abs(x - cx) <= r and abs(y - cy) <= r:
                return name
        return None

    def _hit_button(self, x, y):
        if not self._btn_rects:
            return None
        for name, (bx0, by0, bx1, by1) in self._btn_rects.items():
            if bx0 <= x <= bx1 and by0 <= y <= by1:
                return name
        return None

    def _on_press(self, event):
        if not self.active:
            return
        x, y = event.x, event.y
        btn = self._hit_button(x, y)
        if btn == "confirm":
            self._confirm(); return
        elif btn == "cancel":
            self._cancel(); return
        corner = self._hit_corner(x, y)
        if corner is not None:
            self.mode = "resize"; self.resize_corner = corner
            self.drag_anchor = (x, y); return
        if self._inside_rect(x, y):
            self.mode = "move"; self.drag_anchor = (x, y); return
        self.mode = "draw"
        self.rect_x0 = x; self.rect_y0 = y
        self.rect_x1 = x; self.rect_y1 = y
        self.drag_anchor = (x, y)
        self._clear_buttons()
        self._set_corners_visible(False)

    def _on_drag(self, event):
        if not self.active:
            return
        x, y = event.x, event.y
        if self.mode == "draw":
            self.rect_x1 = x; self.rect_y1 = y
        elif self.mode == "move":
            if self.drag_anchor is None: return
            dx = x - self.drag_anchor[0]
            dy = y - self.drag_anchor[1]
            self.rect_x0 += dx; self.rect_x1 += dx
            self.rect_y0 += dy; self.rect_y1 += dy
            self.drag_anchor = (x, y)
        elif self.mode == "resize":
            if self.resize_corner == 'nw': self.rect_x0 = x; self.rect_y0 = y
            elif self.resize_corner == 'ne': self.rect_x1 = x; self.rect_y0 = y
            elif self.resize_corner == 'sw': self.rect_x0 = x; self.rect_y1 = y
            elif self.resize_corner == 'se': self.rect_x1 = x; self.rect_y1 = y
        self._redraw()

    def _on_release(self, event):
        if not self.active: return
        self.mode = None; self.drag_anchor = None; self.resize_corner = None
        self._redraw()
        if self._rect_valid():
            self._show_buttons()
            self._on_motion(event)

    def _on_motion(self, event):
        if not self.active: return
        x, y = event.x, event.y
        corner = self._hit_corner(x, y)
        new_vis = corner is not None
        if new_vis != self.corners_visible:
            self._set_corners_visible(new_vis)
        try:
            if corner in ('nw', 'se'): self.mask_canvas.config(cursor="size_nw_se")
            elif corner in ('ne', 'sw'): self.mask_canvas.config(cursor="size_ne_sw")
            elif self._inside_rect(x, y): self.mask_canvas.config(cursor="fleur")
            else: self.mask_canvas.config(cursor="crosshair")
        except Exception:
            pass

    def _rect_valid(self):
        if None in (self.rect_x0, self.rect_y0, self.rect_x1, self.rect_y1):
            return False
        return abs(self.rect_x1 - self.rect_x0) >= 8 and abs(self.rect_y1 - self.rect_y0) >= 8

    def _redraw(self):
        if None in (self.rect_x0, self.rect_y0, self.rect_x1, self.rect_y1):
            return
        x0 = min(self.rect_x0, self.rect_x1)
        y0 = min(self.rect_y0, self.rect_y1)
        x1 = max(self.rect_x0, self.rect_x1)
        y1 = max(self.rect_y0, self.rect_y1)
        if self.rect_id is None:
            self.rect_id = self.ui_canvas.create_rectangle(
                x0, y0, x1, y1, outline='#FFEB3B', width=3, fill='')
        else:
            self.ui_canvas.coords(self.rect_id, x0, y0, x1, y1)
        self._draw_handles(x0, y0, x1, y1)
        w = x1 - x0; h = y1 - y0
        text = f"{w} x {h}"
        size_font = -max(12, int(14 * self.scale))
        tx = min(self.sw - 80, x1 + 10)
        ty = min(self.sh - 20, y1 + 10)
        if self.size_text_id is None:
            self.size_text_id = self.ui_canvas.create_text(
                tx, ty, anchor='nw', text=text, fill='#FFEB3B',
                font=("Consolas", size_font, "bold"))
        else:
            self.ui_canvas.coords(self.size_text_id, tx, ty)
            self.ui_canvas.itemconfig(self.size_text_id, text=text)
        if self.btn_confirm_bg is not None:
            self._show_buttons()

    def _draw_handles(self, x0, y0, x1, y1):
        hs = self.HANDLE_SIZE * self.scale
        positions = [(x0, y0), (x1, y0), (x0, y1), (x1, y1)]
        while len(self.handle_ids) < 4:
            self.handle_ids.append(self.ui_canvas.create_rectangle(
                0, 0, 0, 0, fill='#FFEB3B', outline='#333',
                width=1, state='hidden'))
        for i, (cx, cy) in enumerate(positions):
            self.ui_canvas.coords(self.handle_ids[i],
                                  cx - hs, cy - hs, cx + hs, cy + hs)

    def _set_corners_visible(self, visible):
        self.corners_visible = visible
        state = 'normal' if visible else 'hidden'
        for item in self.handle_ids:
            try: self.ui_canvas.itemconfig(item, state=state)
            except Exception: pass

    def _clear_buttons(self):
        for item in (self.btn_confirm_bg, self.btn_confirm_txt,
                     self.btn_cancel_bg, self.btn_cancel_txt):
            if item is not None:
                try: self.ui_canvas.delete(item)
                except Exception: pass
        self.btn_confirm_bg = None; self.btn_confirm_txt = None
        self.btn_cancel_bg = None; self.btn_cancel_txt = None
        self._btn_rects = {}

    def _compute_button_position(self):
        if None in (self.rect_x0, self.rect_y0, self.rect_x1, self.rect_y1):
            return None
        x0 = min(self.rect_x0, self.rect_x1)
        x1 = max(self.rect_x0, self.rect_x1)
        y0 = min(self.rect_y0, self.rect_y1)
        y1 = max(self.rect_y0, self.rect_y1)
        S = self.scale
        bw = int(self.BTN_W * S); bh = int(self.BTN_H * S)
        gap = int(self.BTN_GAP * S); offset = int(self.BTN_OFFSET * S)
        total_w = bw * 2 + gap
        M = self.SCREEN_MARGIN
        cx_center = (x0 + x1) // 2
        cy_center = (y0 + y1) // 2
        if y1 + offset + bh <= self.sh - M:
            bx = max(M, min(self.sw - total_w - M, cx_center - total_w // 2))
            return bx, y1 + offset, 'bottom'
        if y0 - offset - bh >= M:
            bx = max(M, min(self.sw - total_w - M, cx_center - total_w // 2))
            return bx, y0 - offset - bh, 'top'
        if x1 + offset + total_w <= self.sw - M:
            by = max(M, min(self.sh - bh - M, cy_center - bh // 2))
            return x1 + offset, by, 'right'
        if x0 - offset - total_w >= M:
            by = max(M, min(self.sh - bh - M, cy_center - bh // 2))
            return x0 - offset - total_w, by, 'left'
        bx = (self.sw - total_w) // 2
        by = self.sh - bh - int(20 * S)
        return bx, by, 'fallback'

    def _show_buttons(self):
        self._clear_buttons()
        pos = self._compute_button_position()
        if pos is None: return
        bx, by, _ = pos
        S = self.scale
        bw = int(self.BTN_W * S); bh = int(self.BTN_H * S)
        gap = int(self.BTN_GAP * S)
        cx0 = bx; cx1 = bx + bw; cy0 = by; cy1 = by + bh
        self.btn_confirm_bg = self.ui_canvas.create_rectangle(
            cx0, cy0, cx1, cy1, fill='#4CAF50', outline='#2E7D32', width=2)
        self.btn_confirm_txt = self.ui_canvas.create_text(
            (cx0 + cx1) // 2, (cy0 + cy1) // 2, text="✓ 确认",
            fill='white', font=("微软雅黑", -max(12, int(13 * S)), "bold"))
        self._btn_rects['confirm'] = (cx0, cy0, cx1, cy1)
        dx0 = bx + bw + gap; dx1 = dx0 + bw; dy0 = by; dy1 = by + bh
        self.btn_cancel_bg = self.ui_canvas.create_rectangle(
            dx0, dy0, dx1, dy1, fill='#F44336', outline='#B71C1C', width=2)
        self.btn_cancel_txt = self.ui_canvas.create_text(
            (dx0 + dx1) // 2, (dy0 + dy1) // 2, text="✕ 取消",
            fill='white', font=("微软雅黑", -max(12, int(13 * self.scale)), "bold"))
        self._btn_rects['cancel'] = (dx0, dy0, dx1, dy1)

    def _confirm(self):
        if not self._rect_valid(): return
        x0 = int(min(self.rect_x0, self.rect_x1))
        y0 = int(min(self.rect_y0, self.rect_y1))
        x1 = int(max(self.rect_x0, self.rect_x1))
        y1 = int(max(self.rect_y0, self.rect_y1))
        self._close()
        if self.on_done: self.on_done(x0, y0, x1, y1)

    def _cancel(self):
        self._close()
        if self.on_cancel: self.on_cancel()

    def _close(self):
        self.active = False
        for w in (self.mask_top, self.ui_top):
            if w is not None and w.winfo_exists():
                try: w.destroy()
                except Exception: pass
        self.mask_top = None
        self.ui_top = None
