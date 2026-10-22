"""Was the CF bet switch forced or player-chosen?

Evidence we can get from the archive:
  1. every outbound command name (is there an explicit bet-change request?)
  2. the spin-by-spin bet sequence -> where the bet changes, and what happened right before
  3. whether a LOWER bet is ever played after a higher bet was unlocked/used
     (if yes -> the ladder stays selectable, i.e. not a forced single direction)
"""
import collections
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SESS = r"D:\CashFrenzyResearch\local-only\probe\_sessions"
MAIN = os.path.join(SESS, "20260922_103131", "events.jsonl")

# ---------------------------------------------------------------- 1. command inventory
cmds = collections.Counter()
bet_cmds = collections.Counter()
for sess in sorted(os.listdir(SESS)):
    p = os.path.join(SESS, sess, "events.jsonl")
    if not os.path.exists(p):
        continue
    for line in open(p, encoding="utf-8", errors="replace"):
        try:
            o = json.loads(line)
        except Exception:
            continue
        c = o.get("command") or ""
        if c:
            cmds[c] += 1
            if any(k in c.lower() for k in ("bet", "wager", "stake")):
                bet_cmds[c] += 1

print("=== outbound/inbound commands that mention bet/wager/stake ===")
print(dict(bet_cmds) or "(none)")
print("\n=== top 25 commands overall ===")
for k, v in cmds.most_common(25):
    print("  %-40s %d" % (k, v))

# ---------------------------------------------------------------- 2. bet sequence
print("\n=== bet sequence in the main session (L6->L50) ===")
bets = []
for line in open(MAIN, encoding="utf-8", errors="replace"):
    try:
        o = json.loads(line)
    except Exception:
        continue
    if o.get("command") != "batch_spin" or o.get("kind") != "outbound":
        continue
    try:
        payload = o["stack"]["slots"]["2"]["[2]"]
    except Exception:
        continue
    bets.append(payload.get("bet"))

changes = []
prev = None
for i, b in enumerate(bets, 1):
    if b != prev:
        changes.append((i, prev, b))
        prev = b
print("  spins captured:", len(bets))
print("  bet changes (spin#, from -> to):")
for i, a, b in changes:
    print("     #%-4d  %s -> %s" % (i, a, b))

# ---------------------------------------------------------------- 3. lower bet after higher
seen_max = 0
drops = []
for i, b in enumerate(bets, 1):
    if not isinstance(b, int):
        continue
    if b > seen_max:
        seen_max = b
    elif b < seen_max:
        drops.append((i, b, seen_max))
print("\n  spins played with a bet BELOW the max already seen: %d" % len(drops))
for i, b, m in drops[:12]:
    print("     #%-4d bet=%s (max seen so far %s)" % (i, b, m))
