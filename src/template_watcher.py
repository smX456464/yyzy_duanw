"""OCR 监控线程：一次截图 + 内存多处裁剪，大幅降低截图开销"""
import os
import time
from collections import OrderedDict
import numpy as np
from threading import Thread, Event, Lock

from .config_manager import (rule_has_roi, rule_roi,
                              get_builtin_templates)
from .win_utils import (get_pid_by_exe_name, get_hwnd_by_pid, is_window_alive,
                        is_window_visible, is_window_minimized, is_window_cloaked,
                        has_valid_rect, is_window_foreground, is_window_covered,
                        get_client_rect_screen)
from .capture import capture_client_bgra, crop_roi_from_client
from .ocr_engine import (ocr_recognize, ocr_recognize_with_boxes,
                         ocr_text_matches, ocr_rule_hits,
                         is_ocr_available)
from .perceptual_hash import perceptual_hash, hamming
from .ocr_log import log_ocr


OCR_MAX_W = 736   # 与 RapidOCR 的 det_limit_side_len 一致，避免双重缩放


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
        self._last_bl_log = ""
        # 最近一次扫描结果（供断网线程动态判断）
        self._scan_lock = Lock()
        self.last_scan_result = None  # {'bl_hit','wl_hit','ts'}
        # 自适应扫描
        iw = config.get("img_watch", {}) if isinstance(config, dict) else {}
        self.adaptive_scan = bool(iw.get("adaptive_scan", False))
        self.adaptive_skip_rounds = max(2, int(iw.get("adaptive_skip_rounds", 3)))
        self._rule_stats = {}   # {rule_name: {"ever_text": bool}}
        self._round_counter = 0

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
            self.current_rules = None
            self.current_src = "none"
            return
        try:
            l, t, r, b = get_client_rect_screen(self.hwnd)
            cw, ch = r - l, b - t
            if cw <= 0 or ch <= 0:
                self.current_rules = None
                self.current_src = "invalid"
                return
            size_key = f"{cw}x{ch}"
            self.current_size_key = size_key

            # 1. 用户模板优先
            if size_key in self.templates:
                self.current_rules = self.templates[size_key]
                self.current_src = f"user:{size_key}"
                return

            # 2. 内置硬编码精确匹配
            try:
                builtin = get_builtin_templates()
            except Exception:
                builtin = {}
            if size_key in builtin:
                self.current_rules = builtin[size_key]
                self.current_src = f"builtin:{size_key}"
                return

            # 3. 通用兑底
            fallback_key = "1920x1080"
            if fallback_key in builtin:
                self.current_rules = builtin[fallback_key]
                self.current_src = f"fallback({fallback_key})"
                if getattr(self, "_fallback_logged_key", None) != size_key:
                    print(f"\U0001f441 分辨率 {size_key} 无专属规则，用通用模板 {fallback_key} 顶替", flush=True)
                    self._fallback_logged_key = size_key
                return

            self.current_rules = None
            self.current_src = f"missing:{size_key}"
        except Exception as e:
            print(f"\U0001f441 刷新规则失败: {e}", flush=True)
            self.current_rules = None
            self.current_src = "error"


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

    def _cache_lookup(self, ph):
        """查感知哈希缓存。命中返回 text，未命中返回 None"""
        for key in list(self._ocr_cache.keys()):
            if hamming(ph, key) <= 6:
                try: self._ocr_cache.move_to_end(key)
                except Exception: pass
                return self._ocr_cache[key]
        return None

    def _cache_store(self, ph, text):
        """写入感知哈希缓存，超过上限时踢掉最旧"""
        self._ocr_cache[ph] = text
        try:
            while len(self._ocr_cache) > self._ocr_cache_max:
                self._ocr_cache.popitem(last=False)
        except Exception:
            pass

    def _ocr_cached(self, crop):
        """单 crop 版本（保留，供别处使用）"""
        if crop is None or crop.size == 0:
            return None
        ph = perceptual_hash(crop)
        cached = self._cache_lookup(ph)
        if cached is not None:
            return cached
        text = ocr_recognize(crop)
        self._cache_store(ph, text)
        return text

    def _scan_rules(self, rules_list, full_img, cw, ch, stop_on_first=True):
        """批量扫描：先查缓存，未命中的拼成一张图一次 OCR。
        相比"每个 ROI 单独 OCR"的线性方案，能省 5~8 倍时间。
        """
        if not isinstance(rules_list, list):
            return False, [], []

        # 1. 收集有效规则 + crop + 感知哈希
        items = []
        for r in rules_list:
            if not isinstance(r, dict): continue
            if not rule_has_roi(r): continue
            expected = r.get("ocr_text", "")
            if not expected: continue
            crop = crop_roi_from_client(full_img, rule_roi(r), cw, ch)
            if crop is None or crop.size == 0: continue
            ph = perceptual_hash(crop)
            items.append({"rule": r, "crop": crop, "ph": ph})

        if not items:
            return False, [], []

        # 2. 逐条查缓存
        texts = [None] * len(items)
        for i, item in enumerate(items):
            cached = self._cache_lookup(item["ph"])
            if cached is not None:
                texts[i] = cached

        # 3. 未命中的拼成一张竖图，一次 OCR
        miss_indices = [i for i, t in enumerate(texts) if t is None]
        if miss_indices:
            PAD = 8
            PAD_RGBA = (235, 235, 235, 255)
            crops = [items[i]["crop"] for i in miss_indices]
            max_w = max(c.shape[1] for c in crops)
            y_offset = 0
            y_ranges = []
            for c, i in zip(crops, miss_indices):
                h = c.shape[0]
                y_ranges.append((y_offset, y_offset + h, i))
                y_offset += h + PAD
            total_h = y_offset - PAD
            canvas = np.full((total_h, max_w, 4), PAD_RGBA, dtype=np.uint8)
            y = 0
            for c in crops:
                h, w = c.shape[:2]
                canvas[y:y + h, :w] = c
                y += h + PAD

            ocr_items = ocr_recognize_with_boxes(canvas)
            for i in miss_indices:
                texts[i] = ""
            for text, yc in ocr_items:
                for ys, ye, i in y_ranges:
                    if ys <= yc < ye:
                        if texts[i]:
                            texts[i] = texts[i] + " " + text
                        else:
                            texts[i] = text
                        break
            for i in miss_indices:
                self._cache_store(items[i]["ph"], texts[i] or "")

        # 4. 逐条判断命中
        hit_names = []
        hit_texts = []
        for i, item in enumerate(rules_list and items):
            r = item["rule"]
            text = texts[i] or ""
            if ocr_rule_hits(text, r):
                hit_names.append(r.get("name", ""))
                hit_texts.append(text)
                if stop_on_first:
                    break
        return len(hit_names) > 0, hit_names, hit_texts

    def _should_skip_rule(self, rule, kind):
        """本轮是否跳过某条规则（自适应扫描）。
        黑名单永不跳过（安全）；白名单从未出过文字的降频。
        """
        if not self.adaptive_scan:
            return False
        if kind == "bl":
            return False
        name = rule.get("name", "")
        stats = self._rule_stats.get(name)
        if not stats:
            return False
        if stats.get("ever_text"):
            return False
        # 从未出现过文字 → 按 skip_rounds 跳
        return (self._round_counter % self.adaptive_skip_rounds) != 0

    def _update_rule_stats(self, rule_name, text):
        """更新某规则的统计：是否曾经出现过文字"""
        s = self._rule_stats.setdefault(rule_name, {"ever_text": False})
        if text:
            s["ever_text"] = True

    def _scan_all_rules(self, bl_rules, wl_rules, full_img, cw, ch,
                        stop_on_first=True):
        """合并扫描：白黑名单所有 ROI 拼成一张图一次 OCR。

        返回 dict：
          bl_hit, bl_names              黑名单命中结果
          wl_hit, wl_names, wl_texts    白名单命中结果
        """
        # 轮次计数（自适应扫描用）
        self._round_counter += 1
        _t_start = time.perf_counter()

        def collect(rules_list, kind):
            out = []
            if not isinstance(rules_list, list): return out
            for r in rules_list:
                if not isinstance(r, dict): continue
                if not rule_has_roi(r): continue
                expected = r.get("ocr_text", "")
                if not expected: continue
                # 自适应扫描：本轮跳过？
                if self._should_skip_rule(r, kind):
                    continue
                crop = crop_roi_from_client(full_img, rule_roi(r), cw, ch)
                if crop is None or crop.size == 0: continue
                ph = perceptual_hash(crop)
                out.append({"rule": r, "crop": crop, "ph": ph, "kind": kind})
            return out

        items = collect(bl_rules, "bl") + collect(wl_rules, "wl")
        _t_crop_done = time.perf_counter()
        result = {"bl_hit": False, "bl_names": [], "bl_texts": [],
                  "wl_hit": False, "wl_names": [], "wl_texts": []}
        if not items:
            return result

        # 查缓存
        texts = [None] * len(items)
        for i, item in enumerate(items):
            cached = self._cache_lookup(item["ph"])
            if cached is not None:
                texts[i] = cached

        # 未命中的拼图
        miss_indices = [i for i, t in enumerate(texts) if t is None]
        if miss_indices:
            PAD = 8
            PAD_RGBA = (235, 235, 235, 255)
            crops = [items[i]["crop"] for i in miss_indices]
            max_w = max(c.shape[1] for c in crops)
            y_offset = 0
            y_ranges = []
            for c, i in zip(crops, miss_indices):
                h = c.shape[0]
                y_ranges.append((y_offset, y_offset + h, i))
                y_offset += h + PAD
            total_h = y_offset - PAD
            canvas = np.full((total_h, max_w, 4), PAD_RGBA, dtype=np.uint8)
            y = 0
            for c in crops:
                h, w = c.shape[:2]
                canvas[y:y + h, :w] = c
                y += h + PAD

            # 等比缩放（超过 OCR_MAX_W）
            scale_y = 1.0
            canvas_for_ocr = canvas
            is_rgb = False
            if canvas.shape[1] > OCR_MAX_W:
                try:
                    from PIL import Image
                    scale = OCR_MAX_W / canvas.shape[1]
                    new_h = max(1, int(canvas.shape[0] * scale))
                    # BGRA -> RGB
                    rgb = np.ascontiguousarray(canvas[:, :, [2, 1, 0]])
                    pil = Image.fromarray(rgb)
                    pil = pil.resize((OCR_MAX_W, new_h), Image.LANCZOS)
                    canvas_for_ocr = np.asarray(pil)
                    is_rgb = True
                    scale_y = scale
                except Exception as e:
                    print(f"缩放失败，用原图: {e}", flush=True)
                    canvas_for_ocr = canvas
                    is_rgb = False
                    scale_y = 1.0

            ocr_items = ocr_recognize_with_boxes(canvas_for_ocr, is_rgb=is_rgb)
            for i in miss_indices:
                texts[i] = ""
            for text, yc in ocr_items:
                # 缩放后 y_center 还原到原 canvas 坐标
                if scale_y != 1.0:
                    yc = int(yc / scale_y)
                for ys, ye, i in y_ranges:
                    if ys <= yc < ye:
                        if texts[i]:
                            texts[i] = texts[i] + " " + text
                        else:
                            texts[i] = text
                        break
            for i in miss_indices:
                self._cache_store(items[i]["ph"], texts[i] or "")

        # 计算每条规则的耗时（真 OCR 平摊，缓存命中给 0.05）
        _t_ocr_done = time.perf_counter()
        _ocr_total_ms = (_t_ocr_done - _t_crop_done) * 1000.0
        _n_miss = len(miss_indices) if miss_indices else 0
        _per_miss_ms = _ocr_total_ms / _n_miss if _n_miss > 0 else 0.0
        _item_ms = []
        _miss_set = set(miss_indices)
        for _i in range(len(items)):
            if _i in _miss_set:
                _item_ms.append(_per_miss_ms)
            else:
                _item_ms.append(0.05)

        # 更新统计（自适应扫描）
        if self.adaptive_scan:
            for i, item in enumerate(items):
                try:
                    self._update_rule_stats(
                        item["rule"].get("name", ""), texts[i] or "")
                except Exception:
                    pass

        # 拿通用规则
        uni = self.templates.get("universal", {}) if isinstance(self.templates, dict) else {}
        uni_bl = uni.get("blacklist", []) if isinstance(uni, dict) else []
        if not isinstance(uni_bl, list):
            uni_bl = []
        uni_wl = uni.get("whitelist", []) if isinstance(uni, dict) else []
        if not isinstance(uni_wl, list):
            uni_wl = []

        # 先判黑名单（通用 + 专用）
        # 通用黑名单：用所有 text 匹配
        for i, item in enumerate(items):
            text = texts[i] or ""
            if not text:
                continue
            for ur in uni_bl:
                if not isinstance(ur, dict):
                    continue
                if ocr_rule_hits(text, ur):
                    _uname = "[\u901a\u7528]" + ur.get("name", "")
                    result["bl_names"].append(_uname)
                    result["bl_texts"].append(text)
                    if stop_on_first:
                        result["bl_hit"] = True
                        try:
                            with self._scan_lock:
                                self.last_scan_result = {
                                    "bl_hit": True, "wl_hit": False,
                                    "block_time": ur.get("block_time"),
                                    "rule_name": _uname,
                                    "ts": time.time(),
                                }
                        except Exception:
                            pass
                        return result

        # 专用黑名单
        for i, item in enumerate(items):
            if item["kind"] != "bl": continue
            text = texts[i] or ""
            hit = ocr_rule_hits(text, item["rule"])
            if hit or text:
                _ms = _item_ms[i] if i < len(_item_ms) else 0.0
                _cold = i in _miss_set
                log_ocr("black", item["rule"].get("name", ""), text, hit, _ms, _cold)
            if hit:
                result["bl_names"].append(item["rule"].get("name", ""))
                result["bl_texts"].append(text)
                if stop_on_first:
                    result["bl_hit"] = True
                    _bl_name = item["rule"].get("name", "")
                    try:
                        with self._scan_lock:
                            self.last_scan_result = {
                                "bl_hit": True, "wl_hit": False,
                                "block_time": None,
                                "rule_name": _bl_name,
                                "ts": time.time(),
                            }
                    except Exception:
                        pass
                    return result
        if result["bl_names"]:
            result["bl_hit"] = True
            try:
                with self._scan_lock:
                    self.last_scan_result = {
                        "bl_hit": True, "wl_hit": False,
                        "block_time": None, "rule_name": "",
                        "ts": time.time(),
                    }
            except Exception:
                pass
            return result

        # 通用白名单：用所有 text 匹配
        _hit_wl_rule_bt = None
        _hit_wl_rule_name = ""
        for i, item in enumerate(items):
            text = texts[i] or ""
            if not text:
                continue
            for ur in uni_wl:
                if not isinstance(ur, dict):
                    continue
                if ocr_rule_hits(text, ur):
                    _uname = "[\u901a\u7528]" + ur.get("name", "")
                    result["wl_names"].append(_uname)
                    result["wl_texts"].append(text)
                    _hit_wl_rule_name = _uname
                    _bt = ur.get("block_time", None)
                    if _bt is not None:
                        try: _hit_wl_rule_bt = int(_bt)
                        except Exception: pass
                    break
            if result["wl_names"] and stop_on_first:
                break

        # 再判专用白名单
        for i, item in enumerate(items):
            if item["kind"] != "wl": continue
            text = texts[i] or ""
            hit = ocr_rule_hits(text, item["rule"])
            if hit or text:
                _ms = _item_ms[i] if i < len(_item_ms) else 0.0
                _cold = i in _miss_set
                log_ocr("white", item["rule"].get("name", ""), text, hit, _ms, _cold)
            if hit:
                result["wl_names"].append(item["rule"].get("name", ""))
                result["wl_texts"].append(text)
                if stop_on_first:
                    _hit_wl_rule_name = item["rule"].get("name", "")
                    _bt = item["rule"].get("block_time", None)
                    if _bt is not None:
                        try: _hit_wl_rule_bt = int(_bt)
                        except Exception: pass
                    break
        result["wl_hit"] = len(result["wl_names"]) > 0
        # 保存最近一次扫描结果（线程安全）
        try:
            with self._scan_lock:
                self.last_scan_result = {
                    "bl_hit": bool(result.get("bl_hit")),
                    "wl_hit": bool(result.get("wl_hit")),
                    "block_time": _hit_wl_rule_bt,
                    "rule_name": _hit_wl_rule_name,
                    "ts": time.time(),
                }
        except Exception:
            pass
        return result

    def get_last_scan_result(self):
        """线程安全地读取最近一次扫描结果（供断网线程用）"""
        try:
            with self._scan_lock:
                return self.last_scan_result
        except Exception:
            return None

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

                # === 合并扫描（白黑名单一次 OCR）===
                bl_rules = self.current_rules.get("blacklist", [])
                wl_rules = self.current_rules.get("whitelist", [])
                scan_result = self._scan_all_rules(
                    bl_rules, wl_rules, full_img, cw, ch,
                    stop_on_first=not scan_all)
                bl_hit = scan_result["bl_hit"]
                bl_names = scan_result["bl_names"]
                wl_hit = scan_result["wl_hit"]
                wl_names = scan_result["wl_names"]
                wl_texts = scan_result["wl_texts"]

                if bl_hit:
                    hits = 0
                    cur_bl = ",".join(bl_names) if bl_names else ""
                    # 只在规则名变化时打印，避免刷屏
                    if cur_bl and cur_bl != self._last_bl_log:
                        if len(bl_names) == 1:
                            print(f"👁 黑名单「{bl_names[0]}」命中 → 抑制断网",
                                  flush=True)
                        else:
                            print(f"👁 黑名单命中 {len(bl_names)} 条 "
                                  f"（{', '.join(bl_names)}）→ 抑制断网",
                                  flush=True)
                        self._last_bl_log = cur_bl
                    if self.on_highlight:
                        try:
                            # 传 (names, kind, texts)
                            bl_texts = scan_result.get("bl_texts", [])
                            self.on_highlight(bl_names, "black", bl_texts)
                        except Exception as e:
                            print(f"👁 黑名单高亮回调失败: {e}", flush=True)
                    time.sleep(interval); continue
                else:
                    self._last_bl_log = ""

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
                        try:
                            self.on_highlight(wl_names, "white", wl_texts)
                        except Exception as e:
                            print(f"👁 白名单高亮回调失败: {e}", flush=True)
                    if self.on_match:
                        self.on_match()

            except Exception as e:
                print(f"👁 OCR 监控异常: {e}", flush=True)

            time.sleep(interval)
