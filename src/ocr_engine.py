"""OCR 引擎封装：使用 RapidOCR 默认模型"""
_ocr_engine = None
_OCR_AVAILABLE = False

try:
    from rapidocr_onnxruntime import RapidOCR as _RapidOCR
    _OCR_AVAILABLE = True
except ImportError:
    _RapidOCR = None
    _OCR_AVAILABLE = False


def is_ocr_available():
    return _OCR_AVAILABLE


def is_using_int8():
    return False


def _get_ocr_engine():
    global _ocr_engine
    if _ocr_engine is None:
        if not _OCR_AVAILABLE:
            _ocr_engine = False
            return False
        try:
            print("🔤 正在初始化 OCR 引擎（首次约 1~3 秒）...", flush=True)
            _ocr_engine = _RapidOCR()
            print("🔤 OCR 引擎就绪", flush=True)
        except Exception as e:
            print(f"❌ OCR 引擎初始化失败: {e}", flush=True)
            _ocr_engine = False
    return _ocr_engine


def ocr_recognize(bgra):
    engine = _get_ocr_engine()
    if not engine:
        return None
    try:
        rgb = bgra[:, :, [2, 1, 0]].copy()
        result, _ = engine(rgb)
        if result:
            texts = []
            for item in result:
                try:
                    texts.append(str(item[1]))
                except Exception:
                    pass
            return " ".join(texts)
        return ""
    except Exception as e:
        print(f"❌ OCR 识别失败: {e}", flush=True)
        return None


def ocr_rule_hits(text_now, rule):
    """检查一条规则是否命中（含否定词检查）。
    规则先按 ocr_text / match_mode 判定正命中，
    再用 exclude_text（正则或纯文本）检查否定词：
    如果 OCR 识别到的文字里出现否定词 → 本条规则不算命中。
    """
    import re
    if not isinstance(rule, dict) or text_now is None:
        return False
    expected = (rule.get("ocr_text") or "").strip()
    if not expected:
        return False
    mode = rule.get("match_mode", "contains")
    if not ocr_text_matches(text_now, expected, mode):
        return False
    excl = (rule.get("exclude_text") or "").strip()
    if excl:
        try:
            if re.search(excl, text_now):
                return False
        except Exception:
            # 正则无效时退化成普通子串匹配
            if excl in text_now:
                return False
    return True


def ocr_recognize_with_boxes(bgra, is_rgb=False):
    """OCR 并返回带 y 位置的结果：[(text, y_center), ...]
    用于拼接图，按 y 坐标把文字切回各 ROI。
    is_rgb=True 表示输入已经是 RGB（跳过 BGRA→RGB 转换）
    """
    engine = _get_ocr_engine()
    if not engine:
        return []
    try:
        if is_rgb:
            rgb = bgra
        else:
            rgb = bgra[:, :, [2, 1, 0]].copy()
        result, _ = engine(rgb)
        if not result:
            return []
        items = []
        for item in result:
            try:
                box = item[0]
                text = str(item[1])
                if not text:
                    continue
                ys = [float(p[1]) for p in box]
                y_center = int(sum(ys) / len(ys))
                items.append((text, y_center))
            except Exception:
                pass
        return items
    except Exception as e:
        print(f"OCR 批量识别失败: {e}", flush=True)
        return []


def ocr_text_matches(text_now, expected, mode="contains"):
    import re
    if text_now is None or expected is None:
        return False
    expected = expected.strip()
    if not expected:
        return False
    if mode == "equals":
        return text_now.strip() == expected
    if mode == "regex":
        try:
            return bool(re.search(expected, text_now))
        except Exception:
            return False
    return expected in text_now
