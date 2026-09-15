"""ROI 编辑器：在游戏客户区上拖动 / 缩放一个已有的 ROI 框

交互设计（精简版）：
- 框内任意位置点击拖动 → 整体移动
- 鼠标 hover 到某个角（10px 内）→ 只有那个角显示小手柄，光标变缩放箭头
- 平时只显示细边框 + 尺寸文字，不显示四角方块，视觉更干净
- Enter 确认 / ESC 取消 / 底部按钮
"""
import tkinter as tk
from .win_utils import _user32, GA_ROOT, set_window_capture_exclude


class RoiEditor:
    TRANSPARENT = "#FE01FE"
    HANDLE_SIZE = 7          # 手柄边长（像素）
    HANDLE_HIT = 10          # 命中半径（缩放后）；10px * scale
    BORDER_WIDTH = 2
    MIN_SIZE = 6

    def __init__(self, root, hwnd, client_rect, roi_ratio,
                 hint_text="", on_done=None, on_cancel=None, scale=1.0):
        self.root = root
        self.hwnd = hwnd
        self.l, self.t, self.cw, self.ch = client_rect
        self.scale = scale
        self.on_done = on_done
        self.on_cancel = on_cancel
        self.hint_text = hint_text

        self.x0 = int(self.cw * roi_ratio[0])
        self.y0 = int(self.ch * roi_ratio[1])
        self.x1 = int(self.cw * roi_ratio[2])
        self.y1 = int(self.ch * roi_ratio[3])
        self.has_rect = True

        self.top = None
        self.canvas = None
        self.rect_id = None
        self.handle_ids = []
        self.size_text_id = None
        self.hint_id = None
        self._hint_bg_id = None
        self._btn_rects = {}

        self.mode = None
        self.drag_anchor = None
        self.active = False
        self._hover_corner = None

        self._build()

    # ---------------- 构建 ----------------
    def _build(self):
        S = self.scale
        top = tk.Toplevel(self.root)
        top.overrideredirect(True)
        top.attributes('-topmost', True)
        top.configure(bg=self.TRANSPARENT)
        try:
            top.attributes('-transparentcolor', self.TRANSPARENT)
        except Exception:
            pass
        top.geometry(f"{self.cw}x{self.ch}+{self.l}+{self.t}")
        self.top = top

        canvas = tk.Canvas(top, bg=self.TRANSPARENT,
                           highlightthickness=0, bd=0,
                           cursor="crosshair")
        canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas = canvas

        # 顶部提示（带半透明底）
        hint_size = -max(12, int(14 * S))
        hint_txt = self.hint_text or ("框内拖动移动 · 拖角缩放 · "
                                       "Enter 确认 · ESC 取消")
        self.hint_id = canvas.create_text(
            self.cw // 2, int(24 * S), text=hint_txt,
            fill='#FFFFFF',
            font=("微软雅黑", hint_size, "bold"), tags="ui")
        self._hint_bg_id = None
        bbox = canvas.bbox(self.hint_id)
        if bbox:
            self._hint_bg_id = canvas.create_rectangle(
                bbox[0] - 14, bbox[1] - 6, bbox[2] + 14, bbox[3] + 6,
                fill='#000000', outline='', stipple='gray25', tags="ui")
            canvas.tag_raise(self.hint_id)

        # 底部按钮
        self._draw_buttons()

        # 事件绑定
        canvas.bind("<ButtonPress-1>", self._on_press)
        canvas.bind("<B1-Motion>", self._on_drag)
        canvas.bind("<ButtonRelease-1>", self._on_release)
        canvas.bind("<Motion>", self._on_motion)
        top.bind("<Escape>", lambda e: self._cancel())
        top.bind("<Return>", lambda e: self._confirm())
        top.bind("<KP_Enter>", lambda e: self._confirm())

        top.lift()
        top.focus_force()
        try:
            top.grab_set()
        except Exception:
            pass
        try:
            top.after(50, lambda: top.focus_force()
                      if top.winfo_exists() else None)
        except Exception:
            pass

        # 让编辑器自身从屏幕捕获中排除，避免影响 OCR
        try:
            raw = top.winfo_id()
            th = _user32.GetAncestor(raw, GA_ROOT) or raw
            set_window_capture_exclude(th)
        except Exception:
            pass

        self._redraw()
        self.active = True
        print("✏️ 进入 ROI 编辑模式（框内拖动 / 拖角缩放 / Enter 确认）",
              flush=True)

    def _draw_buttons(self):
        S = self.scale
        cvs = self.canvas
        bw = int(96 * S)
        bh = int(38 * S)
        gap = int(12 * S)
        y = self.ch - bh - int(24 * S)
        total = bw * 3 + gap * 2
        x_start = (self.cw - total) // 2

        items = [
            ("✓ 确定", "#4CAF50", "#2E7D32", "confirm"),
            ("🔄 重画", "#FF9800", "#E65100", "redraw"),
            ("✕ 取消", "#F44336", "#B71C1C", "cancel"),
        ]
        self._btn_rects = {}
        for i, (text, bg, border, key) in enumerate(items):
            x = x_start + i * (bw + gap)
            cvs.create_rectangle(
                x, y, x + bw, y + bh,
                fill=bg, outline=border, width=2, tags="ui")
            cvs.create_text(
                x + bw // 2, y + bh // 2, text=text, fill='white',
                font=("微软雅黑", -max(12, int(13 * S)), "bold"),
                tags="ui")
            self._btn_rects[key] = (x, y, x + bw, y + bh)
        cvs.tag_raise("ui")

    # ---------------- 命中检测 ----------------
    def _hit_button(self, x, y):
        for key, (bx0, by0, bx1, by1) in self._btn_rects.items():
            if bx0 <= x <= bx1 and by0 <= y <= by1:
                return key
        return None

    def _hit_corner(self, x, y):
        """返回离鼠标最近的角名（10px*scale 内），否则 None"""
        if not self.has_rect:
            return None
        r = self.HANDLE_HIT * self.scale
        pts = [('nw', (self.x0, self.y0)),
               ('ne', (self.x1, self.y0)),
               ('sw', (self.x0, self.y1)),
               ('se', (self.x1, self.y1))]
        best = None
        best_d = None
        for name, (cx, cy) in pts:
            d = max(abs(x - cx), abs(y - cy))
            if d <= r and (best is None or d < best_d):
                best = name
                best_d = d
        return best

    def _corner_coords(self, name):
        return {
            'nw': (self.x0, self.y0),
            'ne': (self.x1, self.y0),
            'sw': (self.x0, self.y1),
            'se': (self.x1, self.y1),
        }[name]

    def _inside_rect(self, x, y):
        if not self.has_rect:
            return False
        xa = min(self.x0, self.x1); xb = max(self.x0, self.x1)
        ya = min(self.y0, self.y1); yb = max(self.y0, self.y1)
        return xa <= x <= xb and ya <= y <= yb

    # ---------------- 事件 ----------------
    def _on_press(self, event):
        if not self.active:
            return
        x, y = event.x, event.y
        btn = self._hit_button(x, y)
        if btn == "confirm":
            self._confirm(); return
        elif btn == "redraw":
            self._start_redraw(); return
        elif btn == "cancel":
            self._cancel(); return

        if not self.has_rect:
            # 从无到有：开始画新框（不立即 has_rect，等真拖了才算）
            self.mode = "draw"
            self.x0 = self.x1 = x
            self.y0 = self.y1 = y
            self._hover_corner = None
            return

        # 优先判角（缩放），再判框内（移动），最后框外（画新框）
        corner = self._hit_corner(x, y)
        if corner:
            self.mode = corner
            self._redraw_handles(corner)
            return
        if self._inside_rect(x, y):
            self.mode = "move"
            self.drag_anchor = (x, y)
            return
        # 框外：开始画新框
        self.mode = "draw"
        self.x0 = self.x1 = x
        self.y0 = self.y1 = y
        self._hover_corner = None
        self._redraw()

    def _on_drag(self, event):
        if not self.active or self.mode is None:
            return
        x = max(0, min(self.cw, event.x))
        y = max(0, min(self.ch, event.y))
        if self.mode == "draw":
            self.x1 = x; self.y1 = y
            if abs(self.x1 - self.x0) >= 3 or abs(self.y1 - self.y0) >= 3:
                self.has_rect = True
        elif self.mode == "move":
            if self.drag_anchor:
                dx = x - self.drag_anchor[0]
                dy = y - self.drag_anchor[1]
                self.x0 += dx; self.x1 += dx
                self.y0 += dy; self.y1 += dy
                self.drag_anchor = (x, y)
        elif self.mode == "nw":
            self.x0 = x; self.y0 = y
        elif self.mode == "ne":
            self.x1 = x; self.y0 = y
        elif self.mode == "sw":
            self.x0 = x; self.y1 = y
        elif self.mode == "se":
            self.x1 = x; self.y1 = y
        self._redraw()
        # 拖动角时保持显示那个角的手柄
        if self.mode in ('nw', 'ne', 'sw', 'se'):
            self._redraw_handles(self.mode)

    def _on_release(self, event):
        if not self.active:
            return
        was_draw = (self.mode == "draw")
        self.mode = None
        self.drag_anchor = None
        # 如果是画框模式且框没成（用户只点了一下），保持无框状态
        if was_draw and not self.has_rect:
            self.x0 = self.x1 = 0
            self.y0 = self.y1 = 0
        self._redraw()
        self._on_motion(event)

    def _on_motion(self, event):
        if not self.active:
            return
        if self.mode is not None:
            return
        x, y = event.x, event.y
        c = self._hit_corner(x, y)
        if c != self._hover_corner:
            self._hover_corner = c
            self._redraw_handles(c)
        try:
            if c in ('nw', 'se'):
                self.canvas.config(cursor="size_nw_se")
            elif c in ('ne', 'sw'):
                self.canvas.config(cursor="size_ne_sw")
            elif self._inside_rect(x, y):
                self.canvas.config(cursor="fleur")
            else:
                self.canvas.config(cursor="crosshair")
        except Exception:
            pass

    # ---------------- 绘制 ----------------
    def _redraw(self):
        """只画边框和尺寸文字，不画手柄"""
        cvs = self.canvas
        if self.rect_id is not None:
            try: cvs.delete(self.rect_id)
            except Exception: pass
            self.rect_id = None
        if self.size_text_id is not None:
            try: cvs.delete(self.size_text_id)
            except Exception: pass
            self.size_text_id = None
        if not self.has_rect:
            cvs.tag_raise("ui")
            return

        S = self.scale
        x0 = min(self.x0, self.x1); y0 = min(self.y0, self.y1)
        x1 = max(self.x0, self.x1); y1 = max(self.y0, self.y1)
        bw = max(2, int(self.BORDER_WIDTH * S))

        self.rect_id = cvs.create_rectangle(
            x0, y0, x1, y1, outline='#FFEB3B', width=bw,
            fill='', tags="rect")

        w = x1 - x0; h = y1 - y0
        pw = (w / self.cw) * 100 if self.cw > 0 else 0
        ph = (h / self.ch) * 100 if self.ch > 0 else 0
        text = f"{w}x{h}  ({pw:.2f}%x{ph:.2f}%)"
        # 文字放在框内右下角
        tx = x1 - int(6 * S)
        ty = y1 - int(4 * S)
        self.size_text_id = cvs.create_text(
            tx, ty, anchor='se', text=text, fill='#FFEB3B',
            font=("Consolas", -max(11, int(12 * S)), "bold"),
            tags="rect")

        cvs.tag_raise("rect")
        cvs.tag_raise("ui")

        # 边框重绘会盖住之前的手柄，如果当前有 hover 角，重画它
        if self._hover_corner:
            self._redraw_handles(self._hover_corner)

    def _redraw_handles(self, corner):
        """只画 hover/拖动的那一个角的手柄"""
        cvs = self.canvas
        for h in self.handle_ids:
            try: cvs.delete(h)
            except Exception: pass
        self.handle_ids = []
        if corner is None or not self.has_rect:
            return
        S = self.scale
        cx, cy = self._corner_coords(corner)
        hs = int(self.HANDLE_SIZE * S)
        h = cvs.create_rectangle(
            cx - hs, cy - hs, cx + hs, cy + hs,
            fill='#FFEB3B', outline='#333', width=1, tags="rect")
        self.handle_ids.append(h)
        cvs.tag_raise("rect")
        cvs.tag_raise("ui")

    # ---------------- 行为 ----------------
    def _start_redraw(self):
        self.has_rect = False
        self.x0 = self.x1 = 0
        self.y0 = self.y1 = 0
        self._hover_corner = None
        self.mode = None
        self.drag_anchor = None
        self._redraw_handles(None)
        self._redraw()
        # 更新提示文字 + 强制光标为 crosshair
        try:
            if self.hint_id is not None:
                self.canvas.itemconfig(
                    self.hint_id,
                    text="🎯 拖拽画新框 · Enter 确认 · ESC 取消")
                bbox = self.canvas.bbox(self.hint_id)
                if bbox and self._hint_bg_id is not None:
                    self.canvas.coords(self._hint_bg_id,
                                       bbox[0] - 14, bbox[1] - 6,
                                       bbox[2] + 14, bbox[3] + 6)
                    self.canvas.tag_raise(self._hint_bg_id)
                    self.canvas.tag_raise(self.hint_id)
            self.canvas.config(cursor="crosshair")
        except Exception:
            pass
        print("🔄 重画模式：拖拽画新框", flush=True)

    def _confirm(self):
        if not self.has_rect:
            return
        x0 = min(self.x0, self.x1); y0 = min(self.y0, self.y1)
        x1 = max(self.x0, self.x1); y1 = max(self.y0, self.y1)
        if (x1 - x0) < self.MIN_SIZE or (y1 - y0) < self.MIN_SIZE:
            return
        ratio = (
            round(max(0.0, min(1.0, x0 / self.cw)), 4),
            round(max(0.0, min(1.0, y0 / self.ch)), 4),
            round(max(0.0, min(1.0, x1 / self.cw)), 4),
            round(max(0.0, min(1.0, y1 / self.ch)), 4),
        )
        self._close()
        if self.on_done:
            try:
                self.on_done(ratio)
            except Exception as e:
                print(f"ROI 编辑器确认回调失败: {e}", flush=True)

    def _cancel(self):
        self._close()
        if self.on_cancel:
            try:
                self.on_cancel()
            except Exception as e:
                print(f"ROI 编辑器取消失败: {e}", flush=True)

    def _close(self):
        self.active = False
        try:
            if self.top is not None and self.top.winfo_exists():
                try: self.top.grab_release()
                except Exception: pass
                self.top.destroy()
        except Exception:
            pass
        self.top = None
        self.canvas = None
        print("✏️ ROI 编辑模式已退出", flush=True)
