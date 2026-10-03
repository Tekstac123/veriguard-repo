import csv, io, os
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("kyc-service", host="0.0.0.0", port=int(os.environ.get("PORT", "8000")),
              stateless_http=True, json_response=True)
_cache = {"rows": None}


def _rows():
    if _cache["rows"] is None:
        d = os.environ.get("LOCAL_DATA_DIR")
        if d:
            text = open(os.path.join(d, "kyc-profiles.csv"), encoding="utf-8").read()
        else:
            from azure.identity import ManagedIdentityCredential
            from azure.storage.blob import BlobClient
            cred = ManagedIdentityCredential(client_id=os.environ.get("AZURE_CLIENT_ID"))
            url = "https://%s.blob.core.windows.net" % os.environ["STORAGE_ACCOUNT"]
            text = BlobClient(url, "kyc-profiles", "kyc-profiles.csv", credential=cred).download_blob().readall().decode("utf-8")
        _cache["rows"] = {r["customer_id"]: r for r in csv.DictReader(io.StringIO(text))}
    return _cache["rows"]


def _err(code, message, retryable):
    return {"ok": False, "error": {"code": code, "message": message, "retryable": retryable}}


@mcp.tool()
def get_kyc_profile(customer_id: str) -> dict:
    """Get the KYC risk information for a customer. Only the risk category is returned; identity values are never exposed."""
    try:
        rec = _rows().get((customer_id or "").strip())
        if not rec:
            return _err("NOT_FOUND", "No KYC profile for the supplied customer_id", False)
        return {"ok": True, "customer_id": rec["customer_id"], "risk_category": rec["risk_category"]}
    except Exception as e:
        _cache["rows"] = None
        return _err("TOOL_FAILURE", str(e)[:200], True)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
