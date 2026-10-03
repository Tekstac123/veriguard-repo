import os
import pymssql
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("txn-db", host="0.0.0.0", port=int(os.environ.get("PORT", "8000")),
              stateless_http=True, json_response=True)


def _err(code, message, retryable):
    return {"ok": False, "error": {"code": code, "message": message, "retryable": retryable}}


def _connect():
    return pymssql.connect(server="%s.database.windows.net" % os.environ["SQL_SERVER"],
                           user=os.environ["SQL_USER"], password=os.environ["SQL_PASSWORD"],
                           database=os.environ["SQL_DB"], login_timeout=20, timeout=30, as_dict=True)


@mcp.tool()
def query_transactions(customer_id: str, start_date: str = "", end_date: str = "") -> dict:
    """Query transactions for a customer. Optional start_date and end_date (YYYY-MM-DD, end date inclusive)."""
    try:
        if not customer_id or not customer_id.strip():
            return _err("INVALID_INPUT", "customer_id is required", False)
        sql = ("SELECT TOP 500 transaction_id, customer_id, CONVERT(VARCHAR(19), transaction_date, 120) AS transaction_date, "
               "amount, branch_id, transaction_type, geography FROM dbo.transactions WHERE customer_id = %s")
        args = [customer_id.strip()]
        if start_date:
            sql += " AND transaction_date >= %s"; args.append(start_date)
        if end_date:
            sql += " AND transaction_date < DATEADD(day, 1, CAST(%s AS DATE))"; args.append(end_date)
        sql += " ORDER BY transaction_date"
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, tuple(args))
                rows = cur.fetchall()
        for r in rows:
            r["amount"] = float(r["amount"])
        return {"ok": True, "customer_id": customer_id, "count": len(rows), "transactions": rows}
    except Exception as e:
        return _err("TOOL_FAILURE", str(e)[:200], True)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
