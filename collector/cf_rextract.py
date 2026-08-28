#!/usr/bin/env python3
# cf_rextract.py — 从 events.jsonl 用修正逻辑重新生成 spin_records.jsonl
# 复用 cf_probe.extract_spin（要求出现赢字段才算 spin 结果）。
# 用法：python cf_rextract.py <session_dir>
from __future__ import annotations

import argparse
import json
from pathlib import Path
from collections import Counter

from cf_probe import extract_spin  # 直接复用修正后的提取逻辑


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("session_dir", type=Path)
    args = ap.parse_args()

    events = args.session_dir / "events.jsonl"
    out = args.session_dir / "spin_records.jsonl"
    if not events.exists():
        print(f"no events.jsonl in {args.session_dir}")
        return

    coverage = Counter()
    seq = 0
    with events.open(encoding="utf-8") as f, out.open("w", encoding="utf-8") as o:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if rec.get("kind") != "lua-pcall-args":
                continue
            sp = extract_spin(rec)
            if not sp:
                continue
            seq += 1
            sp["seq"] = seq
            o.write(json.dumps(sp, ensure_ascii=False, separators=(",", ":")) + "\n")
            for key in ("base_win", "bonus_base_win", "total_win", "coins",
                        "win_lines_count", "win_pos_list_count", "feature", "result"):
                if key in sp:
                    coverage[key] += 1

    print(f"spin_results={seq}")
    print("coverage=" + json.dumps(dict(sorted(coverage.items())), ensure_ascii=False))


if __name__ == "__main__":
    main()
