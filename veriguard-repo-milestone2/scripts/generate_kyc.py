"""Generates ~300 synthetic KYC profiles at deployment time (values are never committed to git).
Usage: python generate_kyc.py <output.csv>"""
import csv, random, string, sys
random.seed(7)
out = sys.argv[1] if len(sys.argv) > 1 else "kyc-profiles.csv"
fixed = {"C-1001": "high", "C-1002": "low", "C-1003": "high"}
with open(out, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["customer_id", "risk_category", "aadhaar", "pan", "phone", "address"])
    for i in range(1001, 1301):
        cid = "C-%d" % i
        cat = fixed.get(cid) or random.choices(["low", "medium", "high"], [60, 30, 10])[0]
        pan = "".join(random.choices(string.ascii_uppercase, k=5)) + "%04d" % random.randint(0, 9999) + random.choice(string.ascii_uppercase)
        w.writerow([cid, cat, "".join(random.choices(string.digits, k=12)), pan,
                    "+91 9%09d" % random.randint(0, 999999999), "%d, Synthetic Street %d, Test City" % (random.randint(1, 99), random.randint(1, 50))])
print("300 profiles")
