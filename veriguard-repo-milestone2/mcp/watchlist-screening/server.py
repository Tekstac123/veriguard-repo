import csv, io, os, re, time
from difflib import SequenceMatcher
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("watchlist-screening", host="0.0.0.0", port=int(os.environ.get("PORT", "8000")),
              stateless_http=True, json_response=True)
SUFFIXES = {"llc", "ltd", "pvt", "inc", "limited", "private", "co", "company"}
NEAR = float(os.environ.get("NEAR_MATCH_THRESHOLD", "0.85"))
_cache = {"rows": None}


def normalize(s):
    s = re.sub(r"[^a-z0-9 ]", " ", (s or "").lower())
    return " ".join(w for w in s.split() if w not in SUFFIXES)


def _rows():
    if _cache["rows"] is None:
        d = os.environ.get("LOCAL_DATA_DIR")
        if d:
            text = open(os.path.join(d, "watchlist.csv"), encoding="utf-8").read()
        else:
            from azure.identity import ManagedIdentityCredential
            from azure.storage.blob import BlobClient
            cred = ManagedIdentityCredential(client_id=os.environ.get("AZURE_CLIENT_ID"))
            url = "https://%s.blob.core.windows.net" % os.environ["STORAGE_ACCOUNT"]
            text = BlobClient(url, "watchlist", "watchlist.csv", credential=cred).download_blob().readall().decode("utf-8")
        _cache["rows"] = list(csv.DictReader(io.StringIO(text)))
    return _cache["rows"]


def _err(code, message, retryable):
    return {"ok": False, "error": {"code": code, "message": message, "retryable": retryable}}


@mcp.tool()
def screen_name(name: str) -> dict:
    """Screen a customer name against the synthetic sanctions / PEP watchlist. Returns exact and near matches."""
    try:
        if not name or not name.strip():
            return _err("INVALID_INPUT", "name is required", False)
        q = normalize(name)
        exact, near = [], []
        for r in _rows():
            key = r.get("match_key") or normalize(r["name"])
            s = SequenceMatcher(None, q, key).ratio()
            rec = {"watchlist_id": r["watchlist_id"], "name": r["name"], "category": r["category"],
                   "country": r["country"], "similarity": round(s, 3)}
            if s == 1.0:
                exact.append(rec)
            elif s >= NEAR:
                near.append(rec)
        near.sort(key=lambda x: -x["similarity"])
        return {"ok": True, "query": name, "exact_matches": exact, "near_matches": near,
                "match_count": len(exact) + len(near)}
    except Exception as e:  # structured error so the workflow can retry or fall back
        _cache["rows"] = None
        return _err("TOOL_FAILURE", str(e)[:200], True)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
