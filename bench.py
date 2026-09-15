"""信号变频 · 性能基准测试工具

用法：
    python bench.py                          # 按次数
    python bench.py --duration 10            # 每场景 10 秒
    python bench.py --no-wait                # 跳过倒计时
    python bench.py --rules 2880x1800
    python bench.py --duration 30 --max 1000 # 时长 + 单场景上限
"""
import argparse
import platform
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.config_manager import load_config
from src.win_utils import (get_pid_by_exe_name, get_hwnd_by_pid,
                            get_client_rect_screen)
from src.capture import capture_client_bgra
from src.template_watcher import TemplateWatcher

EXE = "Night of the Full Moon.exe"
BASE = Path(__file__).parent
BENCH_DIR = BASE / "benchmarks"


class Report:
    def __init__(self, path):
        self.path = path
        self.lines = []
        self.file = None
    def open(self):
        BENCH_DIR.mkdir(exist_ok=True)
        self.file = open(self.path, "w", encoding="utf-8", newline="\n")
    def write(self, s=""):
        self.lines.append(s)
        print(s, flush=True)
        if self.file:
            self.file.write(s + "\n")
            self.file.flush()
    def close(self):
        if self.file:
            self.file.close()
            self.file = None


def fmt_stats(name, arr):
    n = len(arr)
    if n == 0:
        return [f"  {name}: (无数据)"]
    avg = statistics.mean(arr)
    med = statistics.median(arr)
    sd = statistics.stdev(arr) if n > 1 else 0.0
    s = sorted(arr)
    p95 = s[min(int(n * 0.95), n - 1)]
    p99 = s[min(int(n * 0.99), n - 1)]
    rate = 1000.0 / avg if avg > 0 else 0
    return [
        f"  {name}",
        f"    次数 {n}  平均 {avg:8.2f}  中位 {med:8.2f}  标准差 {sd:7.2f}  (ms)",
        f"    最快 {min(arr):8.2f}  最慢 {max(arr):8.2f}  P95 {p95:8.2f}  P99 {p99:8.2f}",
        f"    速率 {rate:7.2f} 次/秒",
    ]


def env_info():
    return [
        f"  Python  : {sys.version.split()[0]}",
        f"  平台    : {platform.system()} {platform.release()} ({platform.machine()})",
        f"  处理器  : {platform.processor()}",
        f"  时间    : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
    ]


def run_scenario(fn, by_count, duration_s, max_n):
    """统一执行入口：
    by_count > 0  → 按次数跑 by_count 次（每次清缓存由 fn 自己管）
    by_count == 0 → 按时长跑 duration_s 秒，但不超过 max_n 次
    """
    ts = []
    if by_count > 0:
        for _ in range(by_count):
            t0 = time.perf_counter()
            fn()
            ts.append((time.perf_counter() - t0) * 1000)
    else:
        t_end = time.perf_counter() + duration_s
        while time.perf_counter() < t_end and len(ts) < max_n:
            t0 = time.perf_counter()
            fn()
            ts.append((time.perf_counter() - t0) * 1000)
    return ts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait", type=int, default=8)
    ap.add_argument("--no-wait", action="store_true")
    ap.add_argument("--rules", default="2880x1800")
    ap.add_argument("--cold", type=int, default=30)
    ap.add_argument("--warm", type=int, default=100)
    ap.add_argument("--mixed", type=int, default=50)
    ap.add_argument("--shots", type=int, default=30)
    ap.add_argument("--duration", type=int, default=0,
                    help="按秒跑（每场景 N 秒）；0 = 按次数")
    ap.add_argument("--max", type=int, default=500,
                    help="按时长模式时，每场景最多测 N 次（默认 500）")
    args = ap.parse_args()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    rep_path = BENCH_DIR / f"bench_{ts}.txt"
    rep = Report(rep_path)
    rep.open()

    rep.write("=" * 64)
    rep.write("信号变频 · 性能基准测试报告")
    rep.write("=" * 64)
    rep.write()
    rep.write("【环境信息】")
    for ln in env_info():
        rep.write(ln)
    rep.write()

    cfg, tpl, st = load_config()

    pid = get_pid_by_exe_name(EXE)
    if pid is None:
        rep.write(f"ERROR: 游戏未运行（{EXE}）")
        rep.close(); sys.exit(1)
    hwnd = get_hwnd_by_pid(pid)
    if not hwnd:
        rep.write("ERROR: 找不到游戏窗口")
        rep.close(); sys.exit(1)

    l, t, r, b = get_client_rect_screen(hwnd)
    cw, ch = r - l, b - t
    rep.write("【游戏信息】")
    rep.write(f"  客户区 : {cw}x{ch}")
    rep.write(f"  窗口句柄 : {hwnd}")
    rep.write()

    key = args.rules
    if key not in tpl:
        key = next(iter(tpl.keys()))
        rep.write(f"  规则集 {args.rules} 不存在，用 {key} 代替")
    rules = tpl[key]
    wl = rules.get("whitelist", []) or []
    bl = rules.get("blacklist", []) or []
    rep.write(f"【规则集】{key}")
    rep.write(f"  白名单 {len(wl)} 条，黑名单 {len(bl)} 条")
    if args.duration > 0:
        rep.write(f"  模式：按时长（每场景 {args.duration} 秒，上限 {args.max} 次）")
    else:
        rep.write(f"  模式：按次数（冷{args.cold} 热{args.warm} 混{args.mixed} 截{args.shots}）")
    rep.write()

    if not args.no_wait:
        rep.write(f"请在 {args.wait} 秒内切到游戏窗口...")
        for i in range(args.wait, 0, -1):
            rep.write(f"  {i}...")
            time.sleep(1)
        rep.write("开始测量！")
        rep.write()

    w = TemplateWatcher(exe_path=EXE, config=cfg, templates=tpl)
    w.hwnd = hwnd; w.pid = pid
    w.current_rules = rules; w.current_size_key = key

    # ---------- 1. 截图 ----------
    if args.duration > 0:
        rep.write(f"== 截图（{args.duration} 秒，上限 {args.max} 次）==")
    else:
        rep.write(f"== 截图 × {args.shots} ==")
    def do_shot():
        capture_client_bgra(hwnd)
    shot = run_scenario(do_shot,
                        args.shots if args.duration == 0 else 0,
                        args.duration, args.max)
    for ln in fmt_stats("截图", shot):
        rep.write(ln)
    rep.write()

    result = capture_client_bgra(hwnd)
    if result is None:
        rep.write("ERROR: 截图失败，游戏可能被遮挡")
        rep.close(); sys.exit(1)
    full_img, rect = result

    # ---------- 2. 冷启动 ----------
    if args.duration > 0:
        rep.write(f"== 冷启动（每次清缓存，真 OCR，{args.duration} 秒，上限 {args.max} 次）==")
    else:
        rep.write(f"== 冷启动（每次清缓存，真 OCR）× {args.cold} ==")
    def do_cold():
        w._ocr_cache.clear()
        w._scan_all_rules(bl, wl, full_img, cw, ch, stop_on_first=False)
    cold = run_scenario(do_cold,
                        args.cold if args.duration == 0 else 0,
                        args.duration, args.max)
    for ln in fmt_stats("冷启动（全部）", cold):
        rep.write(ln)
    cold_pure = cold[3:] if len(cold) > 3 else cold
    if len(cold_pure) < len(cold):
        rep.write("  -- 剔除前 3 次（含初始化） --")
        for ln in fmt_stats("冷启动（纯）", cold_pure):
            rep.write(ln)
    rep.write()

    # ---------- 3. 热启动 ----------
    if args.duration > 0:
        rep.write(f"== 热启动（缓存全命中，{args.duration} 秒，上限 {args.max} 次）==")
    else:
        rep.write(f"== 热启动（缓存全命中）× {args.warm} ==")
    def do_warm():
        w._scan_all_rules(bl, wl, full_img, cw, ch, stop_on_first=False)
    warm = run_scenario(do_warm,
                        args.warm if args.duration == 0 else 0,
                        args.duration, args.max)
    for ln in fmt_stats("热启动", warm):
        rep.write(ln)
    rep.write()

    # ---------- 4. 混合 ----------
    if args.duration > 0:
        rep.write(f"== 混合（每 5 次清缓存，{args.duration} 秒，上限 {args.max} 次）==")
    else:
        rep.write(f"== 混合（每 5 次清缓存）× {args.mixed} ==")
    _mixed_n = [0]
    def do_mixed():
        if _mixed_n[0] % 5 == 0:
            w._ocr_cache.clear()
        _mixed_n[0] += 1
        w._scan_all_rules(bl, wl, full_img, cw, ch, stop_on_first=False)
    mixed = run_scenario(do_mixed,
                         args.mixed if args.duration == 0 else 0,
                         args.duration, args.max)
    for ln in fmt_stats("混合", mixed):
        rep.write(ln)
    rep.write()

    # ---------- 汇总 ----------
    avg_s = statistics.mean(shot)
    avg_c = statistics.mean(cold_pure)
    avg_w = statistics.mean(warm)
    avg_m = statistics.mean(mixed)

    rep.write("=" * 64)
    rep.write("【汇总】")
    rep.write("=" * 64)
    rep.write(f"  截图             : {avg_s:8.2f} ms")
    rep.write(f"  冷启动扫描       : {avg_c:8.2f} ms  (真 OCR)")
    rep.write(f"  热启动扫描       : {avg_w:8.2f} ms  (缓存命中)")
    rep.write(f"  混合扫描         : {avg_m:8.2f} ms  (含清缓存)")
    rep.write()
    rep.write(f"  完整一轮（截图 + 热启动）: {avg_s + avg_w:8.2f} ms  →  {1000/(avg_s+avg_w):.2f} 次/秒")
    rep.write(f"  完整一轮（截图 + 冷启动）: {avg_s + avg_c:8.2f} ms  →  {1000/(avg_s+avg_c):.2f} 次/秒")
    if avg_w > 0:
        rep.write(f"  冷热加速比       : {avg_c/avg_w:.1f}x")
    rep.write()
    rep.write(f"报告已保存：{rep_path}")
    rep.write("=" * 64)

    rep.close()
    print()
    print(f"OK 报告已生成：{rep_path}")


if __name__ == "__main__":
    main()