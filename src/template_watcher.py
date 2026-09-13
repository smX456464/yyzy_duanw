"""OCR 监控线程：一次截图 + 内存多处裁剪，大幅降低截图开销"""
import os
import time
from collections import OrderedDict
from threading import Thread, Event

from .config_manager import rule_has_roi, rule_roi
from .win_utils import (get_pid_by_exe_name, get_hwnd_by_pid, is_window_alive,
                        is_window_visible, is_window_minimized, is_window_cloaked,
                        has_valid_rect, is_window_foreground, is_window_covered,
                        get_client_rect_screen)
from .capture import capture_client_bgra, crop_roi_from_client
from .ocr_engine import (ocr_recognize, ocr_text_matches, ocr_rule_hits,
                         is_ocr_available)


class TemplateWatcher:
    def __init__(self, exe_path, config, templates, overlay=None,
                 on_match=None, own_hwnds_cb=None, on_highlight=None):
        self.exe_path = exe_path
        self.exe_name = os.path.basename(exe_path) if exe_path else ""
        self.cfg = config
        self.templates = templates if isinstance(templates, dict) else {}
        self.overlay = overlay
        self.on_match = on_match
        self.own_hwnds_cb = own_hwnds_cb
        self.on_highlight = on_highlight
        self.stop_event = Event()
        self.hwnd = None
        self.pid = None
        self.current_rules = None
        self.current_size_key = ""
        self.current_src = ""
        self._missing_warned = ""
        self._ocr_cache = OrderedDict()
        self._ocr_cache_max = 100
        self._offscreen_logged = False

    def start(self):
        Thread(target=self._run, daemon=True).start()

    def stop(self):
        self.stop_event.set()

    def _refresh_hwnd(self):
        pid = get_pid_by_exe_name(self.exe_name)
        if pid is None:
            self.hwnd = None; self.pid = None; return False
        if pid != self.pid or not is_window_alive(self.hwnd):
            self.pid = pid
            self.hwnd = get_hwnd_by_pid(pid)
        return self.hwnd is not None

    def _refresh_rules(self):
        if not self.hwnd or not is_window_alive(self.hwnd):
            self.current_rules = None; self.current_src = "none"; return
        try:
            l, t, r, b = get_client_rect_screen(self.hwnd)
            cw, ch = r - l, b - t
            if cw <= 0 or ch <= 0:
                self.current_rules = None; self.current_src = "invalid"; return
            size_key = f"{cw}x{ch}"
            self.current_size_key = size_key
            if size_key in self.templates:
                self.current_rules = self.templates[size_key]
                self.current_src = f"template:{size_key}"; return
            # 不再回退 default：本分辨率无专属数据 → 不扫任何规则
            self.current_rules = None
            self.current_src = f"missing:{size_key}"
        except Exception as e:
            print(f"👁 刷新规则失败: {e}", flush=True)
            self.current_rules = None; self.current_src = "error"

    def _collect_exclude(self):
        exclude = []
        if self.overlay is not None and self.overlay.hwnd:
            exclude.append(self.overlay.hwnd)
        if self.own_hwnds_cb is not None:
            try:
                own = self.own_hwnds_cb()
                if own: exclude.extend(own)
            except Exception as e:
                print(f"👁 收集自身窗口失败: {e}", flush=True)
        return list(set(exclude))

    def _ocr_cached(self, crop):
        """对同一 crop 内容用哈希缓存 OCR 结果，避免重复识别。
        缓存 key 用 crop.tobytes() 的 hash，LRU 上限 self._ocr_cache_max。
        """
        if crop is None or crop.size == 0:
            return None
        try:
            h = hash(crop.tobytes())
        except Exception:
            return ocr_recognize(crop)
        if h in self._ocr_cache:
            try: self._ocr_cache.move_to_end(h)
            except Exception: pass
            return self._ocr_cache[h]
        text = ocr_recognize(crop)
        self._ocr_cache[h] = text
        try:
            while len(self._ocr_cache) > self._ocr_cache_max:
                self._ocr_cache.popitem(last=False)
        except Exception:
            pass
        return text

    def _scan_rules(self, rules_list, full_img, cw, ch, stop_on_first=True):
        """一次截图已在外部完成，这里只做内存裁剪 + OCR"""
        if not isinstance(rules_list, list):
            return False, [], []
        hit_names = []
        hit_texts = []
        for r in rules_list:
            if not isinstance(r, dict): continue
            if not rule_has_roi(r): continue
            expected = r.get("ocr_text", "")
            if not expected: continue
            mode = r.get("match_mode", "contains")
            crop = crop_roi_from_client(full_img, rule_roi(r), cw, ch)
            if crop is None or crop.size == 0: continue
            text = self._ocr_cached(crop)
            if ocr_rule_hits(text, r):
                hit_names.append(r.get("name", ""))
                hit_texts.append(text or "")
                if stop_on_first:
                    break
        return len(hit_names) > 0, hit_names, hit_texts

    def _run(self):
        hits = 0
        last_trigger = 0.0
        covered_log_counter = 0
        fg_skip_counter = 0

        iw = self.cfg.get("img_watch", {})
        interval = float(iw.get("interval", 1.0))
        consecutive = int(iw.get("consecutive", 2))
        cooldown = float(iw.get("cooldown", 10.0))
        debug = bool(iw.get("debug_log", False))
        require_fg = bool(iw.get("require_foreground", False))
        scan_all = bool(iw.get("scan_all", False))

        if not is_ocr_available():
            print("⚠️ 未安装 rapidocr-onnxruntime，OCR 监控禁用", flush=True)

        print(f"👁 监控线程启动 间隔={interval}s 连续={consecutive} "
              f"冷却={cooldown}s 模式={'全扫' if scan_all else '短路'}", flush=True)

        while not self.stop_event.is_set():
            try:
                if not self._refresh_hwnd():
                    hits = 0
                    time.sleep(max(interval, 1.0)); continue

                if (not is_window_alive(self.hwnd)
                        or not is_window_visible(self.hwnd)
                        or is_window_minimized(self.hwnd)
                        or is_window_cloaked(self.hwnd)
                        or not has_valid_rect(self.hwnd)):
                    if not self._offscreen_logged:
                        print("👁 窗口不在屏幕上，暂停 OCR（每 2 秒检查一次）", flush=True)
                        self._offscreen_logged = True
                    hits = 0
                    time.sleep(max(2.0, interval * 2)); continue
                if self._offscreen_logged:
                    print("👁 窗口已回到屏幕，恢复 OCR", flush=True)
                    self._offscreen_logged = False

                if require_fg and not is_window_foreground(self.hwnd):
                    fg_skip_counter += 1
                    if fg_skip_counter % 20 == 1:
                        print("👁 目标窗口不在前台，跳过", flush=True)
                    hits = 0
                    time.sleep(interval); continue
                fg_skip_counter = 0

                self._refresh_rules()
                if self.current_rules is None:
                    if self._missing_warned != self.current_size_key:
                        print(f"👁 当前尺寸 {self.current_size_key or '?'} 无规则，"
                              f"请长按 👁 打开规则管理", flush=True)
                        self._missing_warned = self.current_size_key
                    hits = 0
                    time.sleep(interval); continue
                self._missing_warned = ""

                exclude = self._collect_exclude()
                if is_window_covered(self.hwnd, exclude_hwnds=exclude):
                    covered_log_counter += 1
                    if covered_log_counter % 20 == 1:
                        print("👁 窗口被遮挡，跳过检测", flush=True)
                    hits = 0
                    time.sleep(interval); continue
                covered_log_counter = 0

                # === 一次截图 ===
                result = capture_client_bgra(self.hwnd)
                if result is None:
                    hits = 0
                    time.sleep(interval); continue
                full_img, rect = result
                if full_img is None or rect is None or full_img.size == 0:
                    hits = 0
                    time.sleep(interval); continue
                l, t, cw, ch = rect

                # === 黑名单（优先）===
                bl_rules = self.current_rules.get("blacklist", [])
                bl_hit, bl_names, _ = self._scan_rules(
                    bl_rules, full_img, cw, ch, stop_on_first=not scan_all)

                if bl_hit:
                    hits = 0
                    if len(bl_names) == 1:
                        print(f"👁 黑名单「{bl_names[0]}」命中 → 抑制断网", flush=True)
                    else:
                        print(f"👁 黑名单命中 {len(bl_names)} 条 "
                              f"（{', '.join(bl_names)}）→ 抑制断网", flush=True)
                    if self.on_highlight:
                        try: self.on_highlight(bl_names, "black")
                        except Exception as e:
                            print(f"👁 黑名单高亮回调失败: {e}", flush=True)
                    time.sleep(interval); continue

                # === 白名单 ===
                wl_rules = self.current_rules.get("whitelist", [])
                wl_hit, wl_names, wl_texts = self._scan_rules(
                    wl_rules, full_img, cw, ch, stop_on_first=not scan_all)

                now = time.time()
                if debug:
                    show = (wl_texts[0] if wl_texts else "").replace("\n", " ")[:40]
                    print(f"👁 检测 src={self.current_src} BL=无 "
                          f"WL={'✓' if wl_hit else '✗'}"
                          f"({','.join(wl_names) if wl_names else '-'}) "
                          f"got='{show}' hits={hits}/{consecutive}", flush=True)

                if wl_hit:
                    hits += 1
                else:
                    hits = 0

                if hits >= consecutive and (now - last_trigger) >= cooldown:
                    last_trigger = now
                    hits = 0
                    name_str = wl_names[0] if wl_names else "?"
                    print(f"👁 白名单「{name_str}」命中 → 触发断网！", flush=True)
                    if self.on_highlight:
                        try: self.on_highlight(wl_names, "white")
                        except Exception as e:
                            print(f"👁 白名单高亮回调失败: {e}", flush=True)
                    if self.on_match:
                        self.on_match()

            except Exception as e:
                print(f"👁 OCR 监控异常: {e}", flush=True)

            time.sleep(interval)
