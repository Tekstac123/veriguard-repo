"""Deterministic, explainable investigation logic used by the VeriGuard specialist agents.
All evidence comes from tool output; nothing here invents data."""
import datetime as dt
import re
from difflib import SequenceMatcher

STRUCT_MIN, STRUCT_MAX, STRUCT_COUNT, STRUCT_DAYS = 900000.0, 999999.99, 3, 7
RAPID_MIN_CREDIT, RAPID_RATIO, RAPID_HOURS, RAPID_PAIRS = 500000.0, 0.9, 24, 2
HIGH_RISK_GEOS = {"iran", "myanmar", "north korea"}
VELOCITY_COUNT = 25
CREDITS = {"NEFT_CREDIT", "CASH_DEPOSIT", "UPI_CREDIT", "SALARY_CREDIT"}
DEBITS = {"NEFT_DEBIT", "UPI_DEBIT", "ATM_WITHDRAWAL", "CARD_PAYMENT"}
KYC_POINTS = {"low": 5, "medium": 15, "high": 25}
TYPOLOGY_POINTS = {"structuring": 45, "rapid_in_out": 30, "high_risk_geography": 20}
WATCH_POINTS = {"exact": 60, "near": 40}
VELOCITY_POINTS = 10
ESCALATE_AT = 70
MONITOR_AT = 30
SUFFIXES = {"llc", "ltd", "pvt", "inc", "limited", "private", "co", "company"}


def normalize_name(s):
    s = re.sub(r"[^a-z0-9 ]", " ", (s or "").lower())
    return " ".join(w for w in s.split() if w not in SUFFIXES)


def similarity(a, b):
    return SequenceMatcher(None, normalize_name(a), normalize_name(b)).ratio()


def _ts(t):
    return dt.datetime.fromisoformat(str(t)[:19])


def detect_typologies(txns):
    txns = sorted(txns, key=lambda t: _ts(t["transaction_date"]))
    found = {}
    # structuring: repeated cash deposits just under the INR 10 lakh reporting threshold
    cash = [t for t in txns if t["transaction_type"] == "CASH_DEPOSIT" and STRUCT_MIN <= float(t["amount"]) <= STRUCT_MAX]
    ids = set()
    for i, t in enumerate(cash):
        end = _ts(t["transaction_date"]) + dt.timedelta(days=STRUCT_DAYS)
        win = [x for x in cash[i:] if _ts(x["transaction_date"]) <= end]
        if len(win) >= STRUCT_COUNT:
            ids.update(x["transaction_id"] for x in win)
    if ids:
        n = len(ids)
        found["structuring"] = {"evidence": sorted(ids), "confidence": round(min(0.99, 0.6 + 0.04 * n), 2),
                                "detail": "%d cash deposits between INR 9,00,000 and 9,99,999 within %d-day windows" % (n, STRUCT_DAYS)}
    # rapid in-out: large credit followed by a near-equal debit within 24 hours
    used, pairs, ev = set(), 0, []
    for c in [t for t in txns if t["transaction_type"] in CREDITS and float(t["amount"]) >= RAPID_MIN_CREDIT]:
        cd = _ts(c["transaction_date"])
        for d in txns:
            if d["transaction_id"] in used or d["transaction_type"] not in DEBITS:
                continue
            dd = _ts(d["transaction_date"])
            if cd < dd <= cd + dt.timedelta(hours=RAPID_HOURS) and float(d["amount"]) >= RAPID_RATIO * float(c["amount"]):
                used.add(d["transaction_id"]); pairs += 1
                ev += [c["transaction_id"], d["transaction_id"]]
                break
    if pairs >= RAPID_PAIRS:
        found["rapid_in_out"] = {"evidence": ev, "confidence": round(min(0.99, 0.6 + 0.1 * pairs), 2),
                                 "detail": "%d large credits withdrawn within %d hours" % (pairs, RAPID_HOURS)}
    geo = [t for t in txns if str(t["geography"]).lower() in HIGH_RISK_GEOS]
    if geo:
        found["high_risk_geography"] = {"evidence": [t["transaction_id"] for t in geo][:10], "confidence": 0.9,
                                        "detail": "%d transactions in high-risk geographies (%s)" % (len(geo), ", ".join(sorted({t["geography"] for t in geo})))}
    return found


def score_risk(kyc_category, typologies, watch_status, txn_count):
    factors = []
    cat = (kyc_category or "").lower()
    factors.append({"factor": "kyc_risk_category", "points": KYC_POINTS.get(cat, 0), "detail": "KYC category: %s" % cat})
    for name, info in typologies.items():
        factors.append({"factor": name, "points": TYPOLOGY_POINTS.get(name, 0), "detail": info["detail"]})
    if watch_status in WATCH_POINTS:
        factors.append({"factor": "watchlist_%s_match" % watch_status, "points": WATCH_POINTS[watch_status], "detail": "Watchlist %s match" % watch_status})
    if txn_count >= VELOCITY_COUNT:
        factors.append({"factor": "transaction_velocity", "points": VELOCITY_POINTS, "detail": "%d transactions in the review window" % txn_count})
    return min(100, sum(f["points"] for f in factors)), factors


def disposition_for(score, watch_status):
    if score >= ESCALATE_AT or watch_status in WATCH_POINTS:
        return "escalate"
    return "monitor" if score >= MONITOR_AT else "close_false_positive"


def policy_queries(typology_names, watch_status):
    q = []
    if "structuring" in typology_names:
        q += ["internal deadline for suspicious transaction reporting", "internal cash transaction reporting threshold"]
    if "rapid_in_out" in typology_names:
        q += ["internal deadline for suspicious transaction reporting"]
    if "high_risk_geography" in typology_names:
        q += ["review cycle for high-risk customers"]
    if watch_status in WATCH_POINTS:
        q += ["sanctions screening timing", "approval required to retain a customer after a failed review"]
    return list(dict.fromkeys(q))
