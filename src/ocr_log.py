"""OCR 日志落盘：每次真 OCR 写一行到 logs/ocr_YYYYMMDD.log"""
import threading
from datetime import datetime
from pathlib import Path

_BASE = Path(__file__).parent.parent
LOG_DIR = _BASE / "logs"
_lock = threading.Lock()
_cur_date = None
_cur_fh = None


def _get_fh():
    global _cur_date, _cur_fh
    today = datetime.now().strftime("%Y%m%d")
    if today != _cur_date:
        if _cur_fh:
            try: _cur_fh.close()
            except Exception: pass
        LOG_DIR.mkdir(exist_ok=True)
        _cur_fh = open(LOG_DIR / f"ocr_{today}.log", "a",
                       encoding="utf-8", newline="\n")
        _cur_date = today
    return _cur_fh


def log_ocr(kind, rule_name, text, hit, ms, cold):
    """kind: 'black'/'white'; cold: True 真 OCR, False 缓存"""
    text = (text or "").replace("\n", " ").replace("|", "/").strip()
    if not hit and not text:
        return
    try:
        ts = datetime.now().strftime("%H:%M:%S")
        flag = "Y" if hit else "N"
        src = "cold" if cold else "warm"
        line = f"{ts} | {kind} | {rule_name} | {text!r} | hit={flag} | {ms:.2f}ms | {src}\n"
        with _lock:
            fh = _get_fh()
            fh.write(line)
            fh.flush()
    except Exception:
        pass
