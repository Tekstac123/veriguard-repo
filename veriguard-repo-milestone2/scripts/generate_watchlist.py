"""Deterministic synthetic sanctions / PEP watchlist. Run: python scripts/generate_watchlist.py"""
import csv, os, random, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "orchestrator"))
from analysis import normalize_name
random.seed(11)
first = ["Arman", "Bashir", "Cyrus", "Dmitri", "Elena", "Farid", "Gideon", "Hamza", "Ivan", "Jamal", "Karim", "Leila", "Marat", "Nadir", "Omar", "Pavel", "Qasim", "Rustam", "Samir", "Tariq"]
last = ["Volkov", "Haddad", "Petrenko", "Zaman", "Karimov", "Nasser", "Orlov", "Sultanov", "Barakat", "Ivanov", "Darwish", "Kazmi"]
rows = [("Mohamed Al Rashed Trading", "Sanctions", "Iran")]
rows += [("Hamid Reza Imports", "Sanctions", "Iran"), ("Zhong Wei Logistics", "Sanctions", "North Korea"), ("Aung Min Holdings", "Sanctions", "Myanmar")]
while len(rows) < 60:
    n = "%s %s" % (random.choice(first), random.choice(last))
    if n not in [r[0] for r in rows]:
        rows.append((n, random.choice(["Sanctions", "PEP"]), random.choice(["Russia", "Iran", "Syria", "Belarus", "Myanmar", "Libya"])))
out = os.path.join(os.path.dirname(__file__), "..", "data", "watchlist", "watchlist.csv")
with open(out, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["watchlist_id", "name", "category", "country", "match_key"])
    for i, (n, c, k) in enumerate(rows, 1):
        w.writerow(["WL-%04d" % i, n, c, k, normalize_name(n)])
print(len(rows), "rows")
