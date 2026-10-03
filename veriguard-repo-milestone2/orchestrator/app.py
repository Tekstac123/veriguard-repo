"""VeriGuard Agentic Compliance Advisor - supervisor workflow.
Supervisor -> Transaction Monitoring -> Risk Assessment -> Compliance Investigator -> merge -> Principal Officer approval.
Specialists call MCP servers (txn-db, kyc-service, watchlist-screening) and the Milestone 1 knowledge base (veriguard-kb)."""
import asyncio, datetime as dt, json, logging, os, time, uuid
from typing import Any, Dict, List, Optional

import pymssql
import requests
from azure.identity import ManagedIdentityCredential
from fastapi import FastAPI, Header, HTTPException
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from pydantic import BaseModel, ValidationError

import analysis

log = logging.getLogger("orchestrator")
logging.basicConfig(level=logging.INFO)
E = os.environ
FOUNDRY, CHAT = E["FOUNDRY_ENDPOINT"], E["CHAT_DEPLOYMENT"]
SEARCH, KB, KS = E["SEARCH_ENDPOINT"], E["KB_NAME"], E["KS_NAME"]
KB_API = E.get("KB_API_VERSION", "2025-11-01-preview")
URLS = {"txn-db": E["TXN_MCP_URL"], "kyc-service": E["KYC_MCP_URL"], "watchlist-screening": E["WATCH_MCP_URL"]}
API_KEY = E["API_KEY"]
APPROVAL_ROLE = E.get("APPROVAL_ROLE", "Principal Officer")
SHORT_TTL_H = int(E.get("SHORT_TERM_TTL_HOURS", "24"))
NOTES_TTL_D = int(E.get("NOTES_TTL_DAYS", "90"))
RETRIES = int(E.get("TOOL_RETRIES", "3"))
FAULTS = E.get("ALLOW_FAULT_INJECTION", "false").lower() == "true"
cred = ManagedIdentityCredential(client_id=E.get("AZURE_CLIENT_ID"))
app = FastAPI(title="VeriGuard Agentic Compliance Advisor")


class ToolUnavailable(Exception):
    def __init__(self, tool, message):
        super().__init__("%s unavailable: %s" % (tool, message))
        self.tool = tool


# ------------------------------------------------------------------ models (structured outputs)
class Alert(BaseModel):
    alert_id: str
    customer_id: str
    customer_name: str
    description: str = ""
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    case_id: Optional[str] = None


class FindingText(BaseModel):
    typology: str
    finding: str


class TxnNarrative(BaseModel):
    findings: List[FindingText]


class RiskNarrative(BaseModel):
    risk_explanation: str


class PolicyMapping(BaseModel):
    requirement: str
    policy_document: str
    section: str


class CaseNarrative(BaseModel):
    case_summary: str
    policy_mappings: List[PolicyMapping]


class PlanModel(BaseModel):
    tasks: List[str]


class Approval(BaseModel):
    decision: str
    approver: str
    approver_role: str
    comment: str = ""


# ------------------------------------------------------------------ infrastructure helpers
def check_key(k):
    if not k or k != API_KEY:
        raise HTTPException(401, "invalid or missing X-API-Key")


def db():
    return pymssql.connect(server="%s.database.windows.net" % E["SQL_SERVER"], user=E["SQL_USER"], password=E["SQL_PASSWORD"],
                           database=E["SQL_DB"], login_timeout=20, timeout=30, autocommit=True, as_dict=True)


def token(scope):
    return cred.get_token(scope).token


def chat_json(system, user, max_tokens=700):
    r = requests.post("%s/openai/deployments/%s/chat/completions?api-version=2024-10-21" % (FOUNDRY, CHAT),
                      headers={"Authorization": "Bearer " + token("https://cognitiveservices.azure.com/.default")},
                      json={"messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                            "temperature": 0, "max_tokens": max_tokens, "response_format": {"type": "json_object"}}, timeout=90)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def structured(model, system, user, fallback):
    """Validate LLM output against the schema; retry once, then use the deterministic fallback."""
    for _ in range(2):
        try:
            return model.model_validate_json(chat_json(system, user)), False
        except (ValidationError, requests.RequestException, KeyError, ValueError) as e:
            log.warning("structured output retry: %s", str(e)[:200])
    return fallback(), True


def call_tool(label, tool, args, fault):
    """MCP tool call with retry; raises ToolUnavailable instead of inventing data."""
    async def once():
        async with streamablehttp_client(URLS[label]) as (r, w, _):
            async with ClientSession(r, w) as s:
                await s.initialize()
                return await s.call_tool(tool, args)
    last = ""
    for attempt in range(1, RETRIES + 1):
        try:
            if fault == label:
                raise RuntimeError("simulated tool failure")
            res = asyncio.run(once())
            data = json.loads(res.content[0].text)
            if data.get("ok") is False and data.get("error", {}).get("retryable"):
                raise RuntimeError(data["error"]["message"])
            return data
        except Exception as e:
            last = str(e)[:200]
            log.warning("%s attempt %d failed: %s", label, attempt, last)
            if attempt < RETRIES:
                time.sleep(2 ** attempt)
    raise ToolUnavailable(label, last)


def kb_retrieve(query):
    body = {"intents": [{"type": "semantic", "search": query}], "retrievalReasoningEffort": {"kind": "minimal"},
            "outputMode": "extractiveData",
            "knowledgeSourceParams": [{"knowledgeSourceName": KS, "kind": "searchIndex", "includeReferences": True, "includeReferenceSourceData": True}]}
    last = ""
    for attempt in range(1, RETRIES + 1):
        try:
            r = requests.post("%s/knowledgebases/%s/retrieve?api-version=%s" % (SEARCH, KB, KB_API),
                              headers={"Authorization": "Bearer " + token("https://search.azure.com/.default")}, json=body, timeout=90)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last = str(e)[:200]
            time.sleep(2 ** attempt if attempt < RETRIES else 0)
    raise ToolUnavailable("veriguard-kb", last)


# ------------------------------------------------------------------ case-scoped memory (isolated by case_id, with TTL)
def mem_put(case_id, key, value, mtype="short_term"):
    ttl = dt.timedelta(hours=SHORT_TTL_H) if mtype == "short_term" else dt.timedelta(days=NOTES_TTL_D)
    exp = dt.datetime.utcnow() + ttl
    v = value if isinstance(value, str) else json.dumps(value)
    with db() as c, c.cursor() as cur:
        cur.execute("DELETE FROM dbo.case_memory WHERE expires_at < SYSUTCDATETIME()")
        cur.execute("""MERGE dbo.case_memory AS t USING (SELECT %s AS case_id, %s AS mem_key, %s AS mem_type) AS s
            ON t.case_id = s.case_id AND t.mem_key = s.mem_key AND t.mem_type = s.mem_type
            WHEN MATCHED THEN UPDATE SET mem_value = %s, expires_at = %s
            WHEN NOT MATCHED THEN INSERT (case_id, mem_key, mem_type, mem_value, expires_at) VALUES (%s, %s, %s, %s, %s);""",
                    (case_id, key, mtype, v, exp, case_id, key, mtype, v, exp))


def mem_get(case_id, key, mtype="short_term"):
    with db() as c, c.cursor() as cur:
        cur.execute("SELECT mem_value FROM dbo.case_memory WHERE case_id = %s AND mem_key = %s AND mem_type = %s AND expires_at > SYSUTCDATETIME()",
                    (case_id, key, mtype))
        row = cur.fetchone()
    return row["mem_value"] if row else None


def save_result(case_id, alert_id, res):
    with db() as c, c.cursor() as cur:
        cur.execute("""MERGE dbo.case_results AS t USING (SELECT %s AS case_id) AS s ON t.case_id = s.case_id
            WHEN MATCHED THEN UPDATE SET status = %s, result = %s, updated_at = SYSUTCDATETIME()
            WHEN NOT MATCHED THEN INSERT (case_id, alert_id, status, result) VALUES (%s, %s, %s, %s);""",
                    (case_id, res["status"], json.dumps(res), case_id, alert_id, res["status"], json.dumps(res)))


def load_result(case_id):
    with db() as c, c.cursor() as cur:
        cur.execute("SELECT result FROM dbo.case_results WHERE case_id = %s", (case_id,))
        row = cur.fetchone()
    return json.loads(row["result"]) if row else None


# ------------------------------------------------------------------ specialist agents
def supervisor_plan(alert):
    allowed = ["transaction_monitoring", "risk_assessment", "compliance_investigation"]
    fb = lambda: PlanModel(tasks=allowed)
    plan, used_fb = structured(PlanModel, "You are the VeriGuard supervisor. Return JSON {\"tasks\": [...]} choosing from " + json.dumps(allowed) +
                               ". Include every task needed to investigate a suspicious-activity alert.", json.dumps(alert.model_dump()), fb)
    tasks = [t for t in allowed if t in plan.tasks] or allowed
    return tasks if len(tasks) == 3 else allowed, used_fb


def transaction_agent(alert, fault):
    data = call_tool("txn-db", "query_transactions", {"customer_id": alert.customer_id, "start_date": alert.start_date or "", "end_date": alert.end_date or ""}, fault)
    if not data.get("ok"):
        raise ToolUnavailable("txn-db", data.get("error", {}).get("message", "error"))
    txns = data["transactions"]
    found = analysis.detect_typologies(txns)
    facts = {k: {"detail": v["detail"], "evidence": v["evidence"][:8]} for k, v in found.items()}
    fb = lambda: TxnNarrative(findings=[FindingText(typology=k, finding=v["detail"]) for k, v in found.items()])
    narr, used_fb = (structured(TxnNarrative, "You are a transaction monitoring analyst. Using ONLY the facts provided, return JSON "
                                "{\"findings\": [{\"typology\": str, \"finding\": str}]} with one concise sentence per typology. Do not add facts.",
                                json.dumps(facts), fb) if found else (TxnNarrative(findings=[]), False))
    text = {f.typology: f.finding for f in narr.findings}
    findings = [{"typology": k, "evidence": v["evidence"], "finding": text.get(k) or v["detail"], "confidence": v["confidence"]} for k, v in found.items()]
    return {"transaction_count": len(txns), "findings": findings, "llm_fallback": used_fb}, found


def risk_agent(alert, txn_report, found, fault):
    kyc = call_tool("kyc-service", "get_kyc_profile", {"customer_id": alert.customer_id}, fault)
    if not kyc.get("ok"):
        raise ToolUnavailable("kyc-service", kyc.get("error", {}).get("message", "KYC profile unavailable"))
    wl = call_tool("watchlist-screening", "screen_name", {"name": alert.customer_name}, fault)
    if not wl.get("ok"):
        raise ToolUnavailable("watchlist-screening", wl.get("error", {}).get("message", "screening unavailable"))
    status = "exact" if wl["exact_matches"] else ("near" if wl["near_matches"] else "none")
    score, factors = analysis.score_risk(kyc["risk_category"], found, status, txn_report["transaction_count"])
    disposition = analysis.disposition_for(score, status)
    fb = lambda: RiskNarrative(risk_explanation="Risk score %d from: %s." % (score, "; ".join("%s (+%d)" % (f["factor"], f["points"]) for f in factors if f["points"])))
    narr, used_fb = structured(RiskNarrative, "You explain a customer risk score. Using ONLY the factors provided, return JSON {\"risk_explanation\": str} in two sentences.",
                               json.dumps({"risk_score": score, "factors": factors, "watchlist_status": status}), fb)
    return {"risk_score": score, "risk_factors": factors,
            "watchlist_result": {"status": status, "matches": wl["exact_matches"] + wl["near_matches"]},
            "risk_explanation": narr.risk_explanation, "recommended_disposition": disposition, "llm_fallback": used_fb}, status


def compliance_agent(alert, txn_report, risk, found, watch_status, disposition):
    queries = analysis.policy_queries(list(found), watch_status)
    refs = []
    for q in queries:
        refs += [(x.get("sourceData") or {}) for x in kb_retrieve(q).get("references", [])]
    seen, current = set(), []
    for s in refs:  # only current, effective versions may support a policy claim
        if str(s.get("is_current")).lower() == "true":
            k = (s.get("document"), s.get("version"), s.get("section"))
            if k not in seen:
                seen.add(k); current.append(s)
    current = current[:6]
    citations = [{"document": s.get("document"), "version": s.get("version"), "section": s.get("section"), "page": s.get("page")} for s in current]
    action = {"escalate": "escalate_to_principal_officer", "monitor": "continue_monitoring", "close_false_positive": "close_as_false_positive"}[disposition]
    summary_fb = "Alert %s for customer %s: risk score %d, disposition %s." % (alert.alert_id, alert.customer_id, risk["risk_score"], disposition)
    if not queries:
        return {"case_summary": summary_fb + " No suspicious typology or watchlist match required policy mapping.", "findings": txn_report["findings"],
                "policy_mappings": [], "citations": [], "recommended_action": action, "evidence_status": "not_applicable"}
    if not current:
        return {"case_summary": summary_fb + " No supporting policy evidence was retrieved; human review is required.", "findings": txn_report["findings"],
                "policy_mappings": [], "citations": [], "recommended_action": "human_review", "evidence_status": "insufficient_evidence"}
    ctx = [{"document": s.get("document"), "section": s.get("section"), "text": s.get("content")} for s in current]
    fb = lambda: CaseNarrative(case_summary=summary_fb, policy_mappings=[PolicyMapping(requirement=c["text"], policy_document=c["document"], section=c["section"]) for c in ctx[:3]])
    narr, used_fb = structured(CaseNarrative, "You assemble a compliance case file. Use ONLY the policy evidence provided. Return JSON {\"case_summary\": str, \"policy_mappings\": "
                               "[{\"requirement\": str, \"policy_document\": str, \"section\": str}]}. Every mapping must reuse a document and section from the evidence. "
                               "Do not make policy claims that the evidence does not support.",
                               json.dumps({"alert": alert.model_dump(), "findings": txn_report["findings"], "risk_score": risk["risk_score"], "disposition": disposition, "policy_evidence": ctx}), fb)
    allowed = {(c["document"], c["section"]) for c in ctx}
    mappings = [m.model_dump() for m in narr.policy_mappings if (m.policy_document, m.section) in allowed]
    if not mappings:
        mappings = [m.model_dump() for m in fb().policy_mappings]
    return {"case_summary": narr.case_summary, "findings": txn_report["findings"], "policy_mappings": mappings, "citations": citations,
            "recommended_action": action, "evidence_status": "supported", "llm_fallback": used_fb}


# ------------------------------------------------------------------ routes
@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/investigate")
def investigate(alert: Alert, x_api_key: Optional[str] = Header(None), x_simulate_tool_failure: Optional[str] = Header(None)):
    check_key(x_api_key)
    fault = x_simulate_tool_failure if FAULTS else None
    case_id = alert.case_id or "CASE-%s-%s" % (alert.alert_id, uuid.uuid4().hex[:6])
    res: Dict[str, Any] = {"case_id": case_id, "alert_id": alert.alert_id, "customer_id": alert.customer_id, "status": "in_progress",
                           "requires_approval": False, "approval": None, "action_executed": False, "errors": [], "trace": []}
    try:
        mem_put(case_id, "alert", alert.model_dump())
        tasks, plan_fb = supervisor_plan(alert)
        res["trace"].append({"step": "supervisor_plan", "tasks": tasks, "llm_fallback": plan_fb})
        txn_report, found = transaction_agent(alert, fault)
        mem_put(case_id, "transaction_report", txn_report)          # handoff via case-scoped memory
        res["trace"].append({"step": "transaction_monitoring", "typologies": list(found)})
        txn_report = json.loads(mem_get(case_id, "transaction_report"))
        risk, watch_status = risk_agent(alert, txn_report, found, fault)
        mem_put(case_id, "risk_assessment", risk)
        res["trace"].append({"step": "risk_assessment", "risk_score": risk["risk_score"], "watchlist": watch_status})
        case_file = compliance_agent(alert, txn_report, risk, found, watch_status, risk["recommended_disposition"])
        mem_put(case_id, "case_file", case_file)
        res["trace"].append({"step": "compliance_investigation", "evidence_status": case_file["evidence_status"]})
        res.update({"transaction_report": txn_report, "risk_assessment": risk, "case_file": case_file,
                    "risk_score": risk["risk_score"], "disposition": risk["recommended_disposition"]})
        high_risk = risk["risk_score"] >= analysis.ESCALATE_AT or case_file["recommended_action"] in ("escalate_to_principal_officer", "report")
        if high_risk:
            res["status"], res["requires_approval"] = "pending_approval", True   # pause before any high-risk action completes
        else:
            res["status"] = "closed_false_positive" if risk["recommended_disposition"] == "close_false_positive" else "monitoring"
    except ToolUnavailable as e:
        res["status"] = "human_review_required"      # controlled fallback: never invent missing evidence
        res["errors"].append({"tool": e.tool, "message": str(e)})
    except Exception as e:
        log.exception("investigation failed")
        res["status"] = "human_review_required"
        res["errors"].append({"tool": "orchestrator", "message": str(e)[:300]})
    save_result(case_id, alert.alert_id, res)
    return res


def execute_action(res):
    """The only code path that completes a high-risk action. It refuses to run without a recorded approval."""
    if res.get("status") != "approved" or not res.get("approval") or res["approval"]["decision"] != "approve":
        raise PermissionError("high-risk action requires Principal Officer approval")
    return True


@app.post("/cases/{case_id}/approval")
def approval(case_id: str, body: Approval, x_api_key: Optional[str] = Header(None)):
    check_key(x_api_key)
    res = load_result(case_id)
    if not res:
        raise HTTPException(404, "case not found")
    if res["status"] != "pending_approval":
        raise HTTPException(409, "case is not awaiting approval (status: %s)" % res["status"])
    if body.approver_role != APPROVAL_ROLE:
        raise HTTPException(403, "only the %s may decide" % APPROVAL_ROLE)
    if body.decision not in ("approve", "reject"):
        raise HTTPException(422, "decision must be approve or reject")
    with db() as c, c.cursor() as cur:
        cur.execute("INSERT INTO dbo.case_approvals (case_id, decision, approver, approver_role, comment) VALUES (%s, %s, %s, %s, %s)",
                    (case_id, body.decision, body.approver, body.approver_role, body.comment))
    res["approval"] = {"decision": body.decision, "approver": body.approver, "approver_role": body.approver_role, "comment": body.comment,
                       "decided_at": dt.datetime.utcnow().isoformat() + "Z"}
    if body.decision == "approve":
        res["status"] = "approved"
        res["action_executed"] = execute_action(res)
        mem_put(case_id, "approved_note", "Approved by %s: %s" % (body.approver, res["case_file"]["case_summary"]), "investigator_note")
    else:
        res["status"], res["action_executed"] = "rejected", False
    save_result(case_id, res["alert_id"], res)
    return res


@app.get("/cases/{case_id}")
def get_case(case_id: str, x_api_key: Optional[str] = Header(None)):
    check_key(x_api_key)
    res = load_result(case_id)
    if not res:
        raise HTTPException(404, "case not found")
    return res


class MemoryValue(BaseModel):
    value: str
    memory_type: str = "short_term"


@app.put("/cases/{case_id}/memory/{key}")
def put_memory(case_id: str, key: str, body: MemoryValue, x_api_key: Optional[str] = Header(None)):
    check_key(x_api_key)
    if body.memory_type not in ("short_term", "investigator_note"):
        raise HTTPException(422, "memory_type must be short_term or investigator_note")
    mem_put(case_id, key, body.value, body.memory_type)
    return {"case_id": case_id, "key": key, "stored": True}


@app.get("/cases/{case_id}/memory/{key}")
def get_memory(case_id: str, key: str, memory_type: str = "short_term", x_api_key: Optional[str] = Header(None)):
    check_key(x_api_key)
    v = mem_get(case_id, key, memory_type)   # always filtered by case_id: no cross-case reads
    return {"case_id": case_id, "key": key, "found": v is not None, "value": v}
