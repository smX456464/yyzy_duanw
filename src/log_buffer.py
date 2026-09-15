"""日志系统：环形缓冲 + 多监听者 + 可覆盖行"""
from collections import deque
import io
import sys

_REPLACEABLE_PREFIXES = [
    ("👁 ROI=", "roi_per_frame"),
    ("👁 检测", "detect_per_frame"),
]

def _auto_tag(text):
    for prefix, tag in _REPLACEABLE_PREFIXES:
        if text.startswith(prefix):
            return tag
    return None

class LogBuffer:
    def __init__(self, maxlen=3000):
        self.buffer = deque(maxlen=maxlen)
        self.listeners = []

    def append(self, text, tag=None):
        if tag is None:
            tag = _auto_tag(text)
        if tag is not None and self.buffer and self.buffer[-1][0] == tag:
            self.buffer[-1] = (tag, text)
            for cb in list(self.listeners):
                try: cb("REPLACE", text)
                except: pass
        else:
            self.buffer.append((tag, text))
            for cb in list(self.listeners):
                try: cb("APPEND", text)
                except: pass

    def add_listener(self, cb):
        if cb not in self.listeners:
            self.listeners.append(cb)

    def remove_listener(self, cb):
        try: self.listeners.remove(cb)
        except ValueError: pass

    def snapshot(self):
        return "".join(t for _, t in self.buffer)

    def clear(self):
        self.buffer.clear()

LOG_BUFFER = LogBuffer()

class BufferedWriter:
    def __init__(self, original, buffer):
        self.original = original
        self.buffer = buffer
        self._partial = ""

    def write(self, s):
        if not s: return
        self._partial += s
        while "\n" in self._partial:
            line, self._partial = self._partial.split("\n", 1)
            full = line + "\n"
            self.buffer.append(full, tag=_auto_tag(full))
        if self.original:
            try: self.original.write(s)
            except: pass

    def flush(self):
        if self._partial:
            self.buffer.append(self._partial, tag=_auto_tag(self._partial))
            self._partial = ""
        if self.original:
            try: self.original.flush()
            except: pass

class SafeWriter:
    def write(self, s):
        if s: LOG_BUFFER.append(s, tag=_auto_tag(s))
    def flush(self): pass

def setup_stdout():
    original = None
    try:
        if sys.stdout is not None and getattr(sys.stdout, "buffer", None) is not None:
            original = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    except:
        original = None
    sys.stdout = BufferedWriter(original, LOG_BUFFER)

class LogTextHandler:
    def __init__(self, widget):
        self.widget = widget
        self._mark_name = f"replace_mark_{id(self)}"

    def __call__(self, action, text):
        try:
            w = self.widget
            # 插入前：判断是否在底部（1.0 表示到底）
            try:
                at_bottom = w.yview()[1] >= 0.999
            except Exception:
                at_bottom = True   # 拿不到就默认在底部，保证兼容
            w.configure(state="normal")
            if action == "REPLACE":
                try: w.delete(self._mark_name, "end")
                except Exception: pass
            start_index = w.index("end-1c")
            w.insert("end", text)
            try:
                w.mark_set(self._mark_name, start_index)
                w.mark_gravity(self._mark_name, "left")
            except Exception: pass
            # 只在用户原本就在底部时才跟到底，否则不打断浏览
            if at_bottom:
                try:
                    w.see("end")
                except Exception:
                    pass
            w.configure(state="disabled")
        except:
            pass
