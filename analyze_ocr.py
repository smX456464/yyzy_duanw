"""OCR 日志分析：手动跑

用法：
    python analyze_ocr.py              # 最近 1 天
    python analyze_ocr.py --days 7     # 最近 7 天
    python analyze_ocr.py --all        # 全部历史

分析 4 项：
    1. 每个规则的高频 got 文字 Top 20（看 OCR 稳定性）
    2. 从没命中过的规则（规则 / ROI 可能有问题）
    3. 疑似误识（同规则 got 变化 > 5 种 → 抖动大）
    4. 单帧 OCR 最慢 Top 10（性能瓶颈）

报告输出到 reports/ocr_analysis_YYYYMMDD_HHMMSS.txt
"""
import argparse
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

BASE = Path(__file__).parent
LOG_DIR = BASE / "logs"
REPORT_DIR = BASE / "reports"

# 日志行格式：HH:MM:SS | kind | rule | 'text' | hit=Y/N | xx.xms | cold/warm
LINE_RE = re.compile(
    r"^(\d{2}:\d{2}:\d{2}) \| (\w+) \| ([^|]+) \| (.+) \| "
    r"hit=([YN]) \| ([\d.]+)ms \| (\w+)$"
)


def parse_logs(days=None):
    if not LOG_DIR.exists():
        return []
    cutoff = datetime.now() - timedelta(days=days) if days else None
    records = []
    for f in sorted(LOG_DIR.glob("ocr_*.log")):
        m = re.search(r"ocr_(\d{8})\.log", f.name)
        if m and cutoff:
            try:
                if datetime.strptime(m.group(1), "%Y%m%d") < cutoff:
                    continue
            except Exception:
                pass
        try:
            with open(f, encoding="utf-8") as fh:
                for line in fh:
                    mm = LINE_RE.match(line.rstrip("\n"))
                    if not mm:
                        continue
                    records.append({
                        "ts": mm.group(1),
                        "kind": mm.group(2),
                        "rule": mm.group(3).strip(),
                        "text": mm.group(4),
                        "hit": mm.group(5) == "Y",
                        "ms": float(mm.group(6)),
                        "src": mm.group(7),
                    })
        except Exception:
            pass
    return records


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=1,
                    help="分析最近 N 天（默认 1）")
    ap.add_argument("--all", action="store_true", help="分析全部历史")
    args = ap.parse_args()

    records = parse_logs(None if args.all else args.days)

    lines = []
    def w(s=""):
        lines.append(s)
        print(s, flush=True)

    w("=" * 64)
    w("OCR 日志分析报告")
    w("=" * 64)
    w(f"  时间    : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    w(f"  范围    : {'全部' if args.all else f'最近 {args.days} 天'}")
    w(f"  记录数  : {len(records)}")
    w()

    if not records:
        w("  (无数据，先跑一段时间工具生成日志)")
        out = REPORT_DIR / f"ocr_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        REPORT_DIR.mkdir(exist_ok=True)
        out.write_text("\n".join(lines), encoding="utf-8")
        print(f"\nOK 空报告已保存：{out}")
        return

    # 按 (kind, rule) 分组
    by_rule = defaultdict(list)
    for r in records:
        by_rule[(r["kind"], r["rule"])].append(r)

    # ============ 1. 各规则 got 文字 Top 20 ============
    w("=" * 64)
    w("【1】各规则 got 文字 Top 20（看 OCR 稳定性）")
    w("=" * 64)
    for (kind, rule), items in sorted(by_rule.items()):
        tag = "白" if kind == "white" else "黑"
        n = len(items)
        hits = sum(1 for x in items if x["hit"])
        uniq = len(set(x["text"] for x in items))
        w(f"\n  [{tag}] {rule}   共 {n} 条, 命中 {hits} ({hits/n*100:.0f}%), "
          f"got 种类 {uniq}")
        for txt, cnt in Counter(x["text"] for x in items).most_common(20):
            pct = cnt / n * 100
            w(f"      {cnt:5d}  ({pct:5.1f}%)  {txt[:70]}")

    # ============ 2. 从没命中过的规则 ============
    w()
    w("=" * 64)
    w("【2】从没命中过的规则（规则 / ROI 可能有问题）")
    w("=" * 64)
    never_hit = []
    for (kind, rule), items in sorted(by_rule.items()):
        if all(not x["hit"] for x in items):
            never_hit.append((kind, rule, len(items)))
    if never_hit:
        for kind, rule, n in never_hit:
            tag = "白" if kind == "white" else "黑"
            w(f"  [{tag}] {rule}   ({n} 条，0 命中)")
    else:
        w("  (全部规则都至少命中过一次)")

    # ============ 3. 疑似误识（got 变化 > 5 种） ============
    w()
    w("=" * 64)
    w("【3】疑似误识 / OCR 抖动大（同规则 got 变化 > 5 种）")
    w("=" * 64)
    shakey = []
    for (kind, rule), items in sorted(by_rule.items()):
        uniq = len(set(x["text"] for x in items))
        if uniq > 5:
            shakey.append((kind, rule, uniq, len(items)))
    if shakey:
        for kind, rule, uniq, n in sorted(shakey, key=lambda x: -x[2]):
            tag = "白" if kind == "white" else "黑"
            w(f"  [{tag}] {rule}   {uniq} 种 got / {n} 条  "
              f"→ 建议检查 ROI 或收紧正则")
    else:
        w("  (无明显抖动，所有规则 got 种类 <= 5)")

    # ============ 4. 单帧 OCR 最慢 Top 10 ============
    w()
    w("=" * 64)
    w("【4】单帧 OCR 最慢 Top 10（性能瓶颈）")
    w("=" * 64)
    # 只统计 cold（真 OCR）
    cold_records = sorted(
        [r for r in records if r["src"] == "cold"],
        key=lambda x: -x["ms"]
    )
    if cold_records:
        for i, r in enumerate(cold_records[:10], 1):
            tag = "白" if r["kind"] == "white" else "黑"
            w(f"  #{i:2d}  {r['ms']:8.1f} ms  [{tag}] {r['rule']:16s}  "
              f"text={r['text'][:40]}")
    else:
        w("  (无冷启动记录)")

    # ============ 5. 汇总统计 ============
    w()
    w("=" * 64)
    w("【汇总】")
    w("=" * 64)
    n_cold = sum(1 for r in records if r["src"] == "cold")
    n_warm = sum(1 for r in records if r["src"] == "warm")
    n_hit = sum(1 for r in records if r["hit"])
    w(f"  总记录     : {len(records)}")
    w(f"  冷启动     : {n_cold}  ({n_cold/len(records)*100:.1f}%)")
    w(f"  热启动     : {n_warm}  ({n_warm/len(records)*100:.1f}%)")
    w(f"  命中       : {n_hit}  ({n_hit/len(records)*100:.1f}%)")
    w(f"  规则数     : {len(by_rule)}")
    w(f"  从没命中   : {len(never_hit)}")
    w(f"  疑似抖动   : {len(shakey)}")

    out = REPORT_DIR / f"ocr_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    REPORT_DIR.mkdir(exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print()
    print(f"OK 报告已保存：{out}")


if __name__ == "__main__":
    main()
