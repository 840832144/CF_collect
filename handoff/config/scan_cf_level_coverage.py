"""Scan every CF capture file for the levels it actually covers, and the bets used at each level.

Goal: answer "the first ten levels — what bet was actually being played, and how many spins".
"""
import csv, json, os, re, sys, collections

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOTS = [
    r"D:\CashFrenzyResearch\local-only",
    r"D:\CashFrenzy-DS-Lab",
    r"D:\CashFrenzy_collect",
    r"D:\cr_design\Collector\collectors\cash_frenzy",
]

cand = []
for root in ROOTS:
    for dirpath, _, files in os.walk(root):
        for f in files:
            p = os.path.join(dirpath, f)
            low = f.lower()
            if not low.endswith((".csv", ".jsonl", ".json")):
                continue
            if os.path.getsize(p) < 200:
                continue
            if not any(k in low for k in ("spin", "level", "event", "session", "capture", "record")):
                continue
            cand.append(p)

print("candidate files:", len(cand))

report = []
for p in cand:
    try:
        if p.lower().endswith(".csv"):
            with open(p, encoding="utf-8-sig", errors="replace", newline="") as fh:
                rd = csv.DictReader(fh)
                head = rd.fieldnames or []
                if "level" not in head and "level_after" not in head:
                    continue
                col = "level" if "level" in head else "level_after"
                bets = "bet" if "bet" in head else ("dominant_bet" if "dominant_bet" in head else None)
                per = collections.defaultdict(lambda: [0, collections.Counter()])
                for row in rd:
                    try:
                        lv = int(float(row.get(col) or 0))
                    except Exception:
                        continue
                    if lv <= 0:
                        continue
                    per[lv][0] += 1
                    if bets:
                        try:
                            per[lv][1][int(float(row.get(bets) or 0))] += 1
                        except Exception:
                            pass
                if per:
                    lvls = sorted(per)
                    report.append((p, "csv", lvls[0], lvls[-1], len(per), per, head[:8]))
        else:
            per = collections.defaultdict(lambda: [0, collections.Counter()])
            with open(p, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if '"level"' not in line:
                        continue
                    m = re.search(r'"level"\s*:\s*(\d+)', line)
                    if not m:
                        continue
                    lv = int(m.group(1))
                    if lv <= 0 or lv > 5000:
                        continue
                    per[lv][0] += 1
                    mb = re.search(r'"bet"\s*:\s*(\d+)', line)
                    if mb:
                        per[lv][1][int(mb.group(1))] += 1
            if per:
                lvls = sorted(per)
                report.append((p, "jsonl", lvls[0], lvls[-1], len(per), per, []))
    except Exception as exc:
        print("  skip", os.path.basename(p), exc)
        continue

report.sort(key=lambda r: r[2])
print("\n%-70s %-6s %-6s %-6s %s" % ("file", "kind", "minL", "maxL", "levels"))
for p, kind, lo, hi, n, per, head in report:
    print("%-70s %-6s %-6d %-6d %d" % (os.path.relpath(p, r"D:\\"), kind, lo, hi, n))

print("\n=== files that cover low levels (<=5) ===")
for p, kind, lo, hi, n, per, head in report:
    if lo <= 5:
        print("\n##", p, " (L%d-%d)" % (lo, hi))
        for lv in range(lo, min(hi, 12) + 1):
            if lv not in per:
                continue
            cnt, bets = per[lv]
            top = ", ".join("%s×%d" % ("{:,}".format(b), c) for b, c in bets.most_common(3))
            print("   L%-3d spins=%-5d bets: %s" % (lv, cnt, top or "-"))
        if head:
            print("   header:", head)
