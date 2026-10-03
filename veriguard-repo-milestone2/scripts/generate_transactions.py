"""Deterministic synthetic transaction generator (5,000 rows). Run: python scripts/generate_transactions.py"""
import csv, random, datetime as dt, os
random.seed(2026)
START, END = dt.datetime(2026, 6, 1), dt.datetime(2026, 8, 31, 23, 59)
CUST = ["C-%d" % i for i in range(1001, 1301)]
CITIES = ["India-Mumbai", "India-Delhi", "India-Chennai", "India-Bengaluru", "India-Hyderabad", "India-Pune", "India-Kolkata", "India-Coimbatore"]
rows = []

def add(c, when, amt, typ, geo=None, br=None):
    rows.append([c, when, round(amt, 2), br or "BR%03d" % random.randint(1, 20), typ, geo or random.choice(CITIES)])

def rnd_time(day, hour_lo=9, hour_hi=18):
    return dt.datetime(2026, 8, day, random.randint(hour_lo, hour_hi), random.randint(0, 59), random.randint(0, 59))

# C-1001 true structuring (+ velocity)
for i in range(12):
    add("C-1001", rnd_time(3 + i % 10), random.uniform(900000, 995000), "CASH_DEPOSIT")
for i in range(16):
    add("C-1001", rnd_time(1 + i * 2 % 28), random.uniform(300, 4000), "UPI_DEBIT")
# C-1002 salary bonus false positive
for m in (6, 7, 8):
    add("C-1002", dt.datetime(2026, m, 1, 10, 0, 0), 85000, "SALARY_CREDIT")
add("C-1002", dt.datetime(2026, 8, 15, 11, 30, 0), 450000, "SALARY_CREDIT")
for i in range(6):
    add("C-1002", rnd_time(2 + i * 4), random.uniform(500, 8000), "UPI_DEBIT")
# C-1003 sanctions near-match customer with high-risk geography
for i in range(6):
    add("C-1003", rnd_time(5 + i * 3), random.uniform(20000, 90000), "NEFT_DEBIT", geo=random.choice(["Iran", "Iran", "Myanmar"]))
add("C-1003", rnd_time(2), 40000, "NEFT_CREDIT")
# other planted typologies
for k in range(10):
    for i in range(6):
        add("C-%d" % (1010 + k), rnd_time(2 + i * 2), random.uniform(900000, 990000), "CASH_DEPOSIT")
for k in range(10):
    for i in range(3):
        amt = random.uniform(600000, 800000)
        t = rnd_time(3 + i * 7, 9, 14)
        add("C-%d" % (1020 + k), t, amt, "NEFT_CREDIT")
        add("C-%d" % (1020 + k), t + dt.timedelta(hours=random.randint(2, 20)), amt * random.uniform(0.95, 0.99), "NEFT_DEBIT")
for k in range(10):
    for i in range(5):
        add("C-%d" % (1030 + k), rnd_time(4 + i * 4), random.uniform(10000, 150000), "NEFT_DEBIT", geo=random.choice(["Iran", "Myanmar", "North Korea"]))
# background activity (small amounts only, no typologies)
planted = {"C-1001", "C-1002", "C-1003"}
while len(rows) < 5000:
    c = random.choice(CUST)
    if c in planted or 1010 <= int(c[2:]) <= 1039:
        continue
    when = START + dt.timedelta(seconds=random.randint(0, int((END - START).total_seconds())))
    typ = random.choices(["UPI_DEBIT", "CARD_PAYMENT", "ATM_WITHDRAWAL", "NEFT_CREDIT", "SALARY_CREDIT"], [40, 25, 10, 15, 10])[0]
    amt = {"UPI_DEBIT": (200, 5000), "CARD_PAYMENT": (500, 20000), "ATM_WITHDRAWAL": (2000, 20000), "NEFT_CREDIT": (5000, 80000), "SALARY_CREDIT": (25000, 150000)}[typ]
    add(c, when, random.uniform(*amt), typ)
rows.sort(key=lambda r: r[1])
out = os.path.join(os.path.dirname(__file__), "..", "data", "transactions", "transactions.csv")
with open(out, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["transaction_id", "customer_id", "transaction_date", "amount", "branch_id", "transaction_type", "geography"])
    for i, r in enumerate(rows, 1):
        w.writerow(["T%06d" % i, r[0], r[1].strftime("%Y-%m-%d %H:%M:%S"), "%.2f" % r[2], r[3], r[4], r[5]])
print(len(rows), "rows")
