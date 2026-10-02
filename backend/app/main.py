from __future__ import annotations

from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pandas as pd
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from app.schemas.decision import ApprovalRequest, AnalyticsRequest, AnalyzeRequest, ProviderRequest, SheetRequest, SimulationRequest
from app.services.analytics import analyze_question
from app.services.ai_service import ai_service
from app.services.dataset import has_lead_schema, load_demo, summarize, validate_frame
from app.services.llm_service import llm_service
from app.services.scoring import DEFAULT_WEIGHTS, INACTIVE_DEFAULT_WEIGHTS, new_decision_id, normalize_weights, score_for_decision, score_inactive_leads, score_leads, serialize_lead
from app.services.storage import storage

app = FastAPI(title="DecisionOS AI", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "https://decision-os-ai.vercel.app"], allow_methods=["*"], allow_headers=["*"])
records = pd.DataFrame()
active_dataset_metadata = {"filename": "No dataset loaded", "file_type": "", "source": "none", "dataset_id": "", "sheet_names": [], "selected_sheet": None}
active_upload_bytes: bytes | None = None
last_analytics_result: dict | None = None
decisions: dict[str, dict] = {}
approvals: dict[str, dict] = {}


def _preview(frame: pd.DataFrame, limit: int = 12) -> list[dict]:
    preview = frame.head(limit).astype(object).where(pd.notna(frame.head(limit)), None)
    return [{str(column): value.isoformat() if isinstance(value, pd.Timestamp) else value.item() if hasattr(value, "item") else value for column, value in row.items()} for row in preview.to_dict(orient="records")]


@app.get("/health")
def health() -> dict:
    return {"status": "online", "records": len(records), "mode": "deterministic"}


@app.post("/api/data/demo")
def use_demo_data() -> dict:
    global records, active_dataset_metadata, active_upload_bytes, last_analytics_result
    records = load_demo()
    active_dataset_metadata = {"filename": "demo_sales_data.csv", "file_type": "csv", "source": "demo", "dataset_id": str(uuid4()), "sheet_names": [], "selected_sheet": None}
    active_upload_bytes = None
    last_analytics_result = None
    return {"message": "Demo dataset loaded", "summary": summarize(records, active_dataset_metadata), "preview": _preview(records)}


@app.post("/api/data/upload")
async def upload_data(file: UploadFile = File(...), sheet_name: str | None = Form(default=None)) -> dict:
    global records, active_dataset_metadata, active_upload_bytes, last_analytics_result
    filename = file.filename or ""
    extension = Path(filename).suffix.lower()
    if extension not in {".csv", ".xlsx", ".xls"}:
        raise HTTPException(400, "Unsupported file format. Please upload CSV, XLSX, or XLS.")
    accepted_types = {
        ".csv": {"text/csv", "application/csv", "application/vnd.ms-excel", "application/octet-stream"},
        ".xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "application/octet-stream"},
        ".xls": {"application/vnd.ms-excel", "application/octet-stream"},
    }
    if file.content_type and file.content_type not in accepted_types[extension]:
        raise HTTPException(400, "File extension and content type do not match. Please upload a valid CSV, XLSX, or XLS file.")
    content = await file.read()
    if not content:
        raise HTTPException(400, "The uploaded file contains no usable rows.")
    sheet_names: list[str] = []
    selected_sheet = None
    try:
        if extension == ".csv":
            parsed = pd.read_csv(BytesIO(content))
        else:
            engine = "openpyxl" if extension == ".xlsx" else "xlrd"
            workbook = pd.ExcelFile(BytesIO(content), engine=engine)
            sheet_names = workbook.sheet_names
            if not sheet_names:
                raise HTTPException(400, "Could not read this Excel file. Please check that the workbook is valid.")
            selected_sheet = sheet_name or sheet_names[0]
            if selected_sheet not in sheet_names:
                raise HTTPException(400, f"Sheet '{selected_sheet}' was not found. Available sheets: {', '.join(sheet_names)}.")
            parsed = pd.read_excel(workbook, sheet_name=selected_sheet)
    except HTTPException:
        raise
    except (pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeDecodeError) as error:
        message = "Could not read this Excel file. Please check that the workbook is valid." if extension != ".csv" else "Could not read this CSV file. Check the delimiter and file encoding."
        raise HTTPException(400, message) from error
    except Exception as error:
        message = "Could not read this Excel file. Please check that the workbook is valid." if extension != ".csv" else f"Could not read this CSV file: {error}"
        raise HTTPException(400, message) from error
    try:
        prepared = validate_frame(parsed)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    records = prepared
    active_upload_bytes = content
    active_dataset_metadata = {"filename": filename, "file_type": extension.removeprefix("."), "source": "upload", "dataset_id": str(uuid4()), "sheet_names": sheet_names, "selected_sheet": selected_sheet, "preprocessing": prepared.attrs.get("preprocessing", [])}
    last_analytics_result = None
    return {"message": f"{filename} uploaded and analyzed", "filename": filename, "summary": summarize(records, active_dataset_metadata), "preview": _preview(records)}


@app.get("/api/data/summary")
def data_summary() -> dict:
    return {"summary": summarize(records, active_dataset_metadata), "preview": _preview(records)}


@app.get("/api/data/profile")
def data_profile() -> dict:
    return summarize(records, active_dataset_metadata)


@app.get("/api/data/preview")
def data_preview(limit: int = 50) -> dict:
    return {"filename": active_dataset_metadata["filename"], "rows": _preview(records, max(1, min(limit, 500))), "total_rows": len(records)}


@app.get("/api/llm/providers")
def llm_providers() -> dict:
    return llm_service.provider_status()


@app.post("/api/llm/provider")
def select_llm_provider(request: ProviderRequest) -> dict:
    return llm_service.set_provider(request.provider)


@app.post("/api/data/select-sheet")
def select_sheet(request: SheetRequest) -> dict:
    global records, active_dataset_metadata, last_analytics_result
    if active_dataset_metadata.get("file_type") not in {"xlsx", "xls"} or not active_upload_bytes:
        raise HTTPException(400, "Upload an Excel workbook before selecting a sheet.")
    if request.sheet_name not in active_dataset_metadata.get("sheet_names", []):
        raise HTTPException(400, f"Sheet '{request.sheet_name}' was not found.")
    try:
        engine = "openpyxl" if active_dataset_metadata["file_type"] == "xlsx" else "xlrd"
        parsed = pd.read_excel(BytesIO(active_upload_bytes), sheet_name=request.sheet_name, engine=engine)
        prepared = validate_frame(parsed)
    except Exception as error:
        raise HTTPException(400, "Could not read this Excel sheet. Please check that the workbook is valid.") from error
    records = prepared
    active_dataset_metadata = {**active_dataset_metadata, "selected_sheet": request.sheet_name, "dataset_id": str(uuid4()), "preprocessing": prepared.attrs.get("preprocessing", [])}
    last_analytics_result = None
    return {"summary": summarize(records, active_dataset_metadata), "preview": _preview(records)}


@app.post("/api/analytics/query")
def analytics_query(request: AnalyticsRequest) -> dict:
    global last_analytics_result
    result = analyze_question(records, request.question, last_analytics_result)
    result["filename"] = active_dataset_metadata["filename"]
    result["dataset_source"] = active_dataset_metadata["source"]
    result["dataset_id"] = active_dataset_metadata["dataset_id"]
    last_analytics_result = result
    return result


@app.post("/api/chat")
def chat_query(request: AnalyticsRequest) -> dict:
    return analytics_query(request)


@app.post("/api/decision/analyze")
def analyze(request: AnalyzeRequest) -> dict:
    if not has_lead_schema(records):
        raise HTTPException(422, "Lead decision scoring requires the PS-04 sales lead columns. Use Ask DecisionOS for general analytics on this active dataset.")
    intent = ai_service.extract_intent(request.question)
    if intent == "ambiguous":
        raise HTTPException(422, "Please clarify your business question. Ask about lead prioritization, customer inactivity, revenue, or sales opportunities.")
    if intent == "historical_performance":
        raise HTTPException(422, "Insufficient evidence: this dataset has no historical sales performance measure to compare.")
    source = records.copy()
    inactive_query = intent == "customer_inactivity"
    revenue_query = intent == "revenue_opportunity"
    weights = INACTIVE_DEFAULT_WEIGHTS.copy() if inactive_query else DEFAULT_WEIGHTS.copy()
    if inactive_query:
        source = source[source["lead_status"].fillna("").str.lower().isin(["inactive", "nurture"])]
    elif revenue_query:
        weights = {"revenue": 0.75, "engagement": 0.10, "recency": 0.05, "purchases": 0.05, "status": 0.05}
    if source.empty:
        raise HTTPException(404, "No matching business records were found.")
    conflicts = (source.groupby("lead_id", dropna=False)[["company", "industry", "lead_value", "engagement_score", "previous_purchases", "last_contact_date", "lead_status", "sales_activity", "customer_segment", "region", "sales_rep"]].nunique(dropna=False) > 1).any(axis=1)
    if conflicts.any():
        raise HTTPException(409, "Conflicting data detected. Review the source records before making a decision.")
    useful_values = source[["lead_value", "engagement_score", "previous_purchases", "last_contact_date", "lead_status"]].notna().any(axis=1).sum()
    if useful_values == 0:
        raise HTTPException(422, "Insufficient evidence: matching records contain no usable decision fields.")
    scoring_method = "weighted inactivity recovery score" if inactive_query else "weighted five-factor lead score"
    ranked = (score_inactive_leads(source, weights) if inactive_query else score_leads(source, weights)).head(request.limit)
    leads = [serialize_lead(row, intent) for _, row in ranked.iterrows()]
    if not leads:
        raise HTTPException(422, "Insufficient evidence: no records have enough scoring data.")
    decision_id = new_decision_id()
    evidence = [{"lead_id": lead["lead_id"], "company": lead["company"], "source": "loaded business dataset", "fields": {"lead_value": lead["lead_value"], "engagement_score": lead["engagement_score"], "previous_purchases": lead["previous_purchases"], "last_contact_date": lead["last_contact_date"], "days_since_contact": lead["days_since_contact"], "lead_status": lead["lead_status"]}, "contributions": lead["contributions"]} for lead in leads]
    gap = leads[0]["score"] - (leads[1]["score"] if len(leads) > 1 else 0)
    recommendation = "Re-engage the longest-inactive customers with the strongest recoverable signals." if inactive_query else "Prioritize the highest-value revenue opportunities." if revenue_query else "Prioritize high-value, highly engaged leads with recent activity."
    impact = "Focus outreach on customers whose inactivity creates the greatest recoverable opportunity." if inactive_query else "Focus sales effort on the highest-potential opportunities first."
    trace_details = {
        "dataset_id": active_dataset_metadata["dataset_id"],
        "dataset_filename": active_dataset_metadata["filename"],
        "records_considered": int(len(source)),
        "records_ranked": len(leads),
        "scoring_method": scoring_method,
        "weights": weights,
        "evidence_records": len(evidence),
    }
    trace = [
        f"User question received: {request.question}",
        f"Dataset selected: {active_dataset_metadata['filename']} ({active_dataset_metadata['dataset_id']})",
        f"{len(source)} relevant records retrieved from the active dataset",
        f"Scoring method: {scoring_method}",
        f"Records compared using weights: {weights}",
        f"{len(leads)} leads ranked and recommendation created: {recommendation}",
        f"{len(evidence)} source evidence records attached",
    ]
    result = {"id": decision_id, "dataset_id": active_dataset_metadata["dataset_id"], "question": request.question, "intent": "customer_inactivity" if inactive_query else "revenue_opportunity" if revenue_query else "lead_prioritization", "recommendation": recommendation, "confidence": min(95, 65 + round(max(0, gap) * 0.8)), "confidence_method": "Prototype heuristic based on the top-two score margin; not a measured accuracy probability.", "expected_impact": impact, "weights": weights, "retrieved_record_ids": source["lead_id"].astype(str).tolist(), "leads": leads, "evidence": evidence, "trace": trace, "trace_details": trace_details, "explanation": ai_service.explain(request.question, evidence), "created_at": pd.Timestamp.now(tz="UTC").isoformat()}
    decisions[decision_id] = result
    storage.save_decision(result)
    return result


@app.delete("/api/dataset/{dataset_id}")
@app.delete("/api/data/{dataset_id}")
def delete_dataset(dataset_id: str) -> dict:
    global records, active_dataset_metadata, active_upload_bytes, last_analytics_result, decisions
    is_active = active_dataset_metadata.get("dataset_id") == dataset_id
    stored_count = storage.count_decisions_for_dataset(dataset_id)
    if not is_active and stored_count == 0 and not storage.is_dataset_deleted(dataset_id):
        raise HTTPException(404, "Dataset not found.")

    storage.delete_dataset_records(dataset_id)
    for dec_id, dec in list(decisions.items()):
        if dec.get("dataset_id") == dataset_id:
            decisions.pop(dec_id, None)
            approvals.pop(dec_id, None)

    if is_active:
        records = pd.DataFrame()
        active_dataset_metadata = {
            "filename": "No dataset loaded",
            "file_type": "",
            "source": "none",
            "dataset_id": "",
            "sheet_names": [],
            "selected_sheet": None,
        }
        active_upload_bytes = None
        last_analytics_result = None

    return {"status": "deleted", "dataset_id": dataset_id}


@app.get("/api/decision/latest")
def latest_decision() -> dict:
    decision = storage.get_latest_decision()
    if decision is None or decision.get("status") == "invalidated" or storage.is_dataset_deleted(decision.get("dataset_id", "")):
        raise HTTPException(404, "No decision has been created yet.")
    decisions[decision["id"]] = decision
    return {"decision": decision, "approval": storage.get_approval(decision["id"])}


@app.get("/api/decision/{decision_id}")
def get_decision(decision_id: str) -> dict:
    result = decisions.get(decision_id) or storage.get_decision(decision_id)
    if result is None:
        raise HTTPException(404, "Decision not found.")
    if result.get("status") == "invalidated" or storage.is_dataset_deleted(result.get("dataset_id", "")):
        raise HTTPException(404, "This decision is no longer available because its source dataset was deleted.")
    decisions[decision_id] = result
    return result


@app.get("/api/decision/{decision_id}/approval")
def get_approval(decision_id: str) -> dict:
    decision = decisions.get(decision_id) or storage.get_decision(decision_id)
    if decision is None or decision.get("status") == "invalidated" or storage.is_dataset_deleted(decision.get("dataset_id", "")):
        raise HTTPException(404, "Decision not found.")
    return {"decision_id": decision_id, "approval": storage.get_approval(decision_id)}


@app.get("/api/decision/{decision_id}/evidence")
def get_evidence(decision_id: str) -> dict:
    decision = get_decision(decision_id)
    if decision.get("dataset_id") and decision["dataset_id"] != active_dataset_metadata["dataset_id"]:
        raise HTTPException(409, "This decision belongs to a previous dataset. Please analyze the current dataset again.")
    return {"decision_id": decision_id, "dataset_id": decision.get("dataset_id"), "evidence": decision["evidence"], "trace": decision["trace"], "trace_details": decision.get("trace_details", {})}


@app.post("/api/simulation/run")
def simulate(request: SimulationRequest) -> dict:
    decision = decisions.get(request.decision_id) or storage.get_decision(request.decision_id)
    if not decision:
        raise HTTPException(404, "Decision not found.")
    if decision.get("status") == "invalidated" or storage.is_dataset_deleted(decision.get("dataset_id", "")):
        raise HTTPException(409, "This decision is no longer available because its source dataset was deleted.")
    if decision.get("dataset_id") and decision["dataset_id"] != active_dataset_metadata["dataset_id"]:
        raise HTTPException(409, "This decision belongs to a different dataset. Please run a new analysis.")
    try:
        weights_after = normalize_weights(request.weights)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    source_ids = decision.get("retrieved_record_ids", [lead["lead_id"] for lead in decision["leads"]])
    source = records[records["lead_id"].astype(str).isin(source_ids)]
    current = score_for_decision(decision, source, decision["weights"])
    simulated = score_for_decision(decision, source, weights_after)
    current_ids = [str(value) for value in current["lead_id"].tolist()]
    simulated_ids = [str(value) for value in simulated["lead_id"].tolist()]
    current_ranking = [serialize_lead(row, decision["intent"]) for _, row in current.head(10).iterrows()]
    simulated_ranking = [serialize_lead(row, decision["intent"]) for _, row in simulated.head(10).iterrows()]
    changed = sum(left != right for left, right in zip(current_ids[:10], simulated_ids[:10]))
    old_positions = {lead["lead_id"]: index + 1 for index, lead in enumerate(current_ranking)}
    new_positions = {lead["lead_id"]: index + 1 for index, lead in enumerate(simulated_ranking)}
    changed_leads = [
        {"lead_id": lead_id, "from_rank": old_positions.get(lead_id), "to_rank": new_positions.get(lead_id)}
        for lead_id in old_positions.keys() | new_positions.keys()
        if old_positions.get(lead_id) != new_positions.get(lead_id)
    ]
    explanation = "Ranking is recalculated from the same retrieved records using your adjusted factor weights." if changed else "Ranking unchanged under these assumptions. Scores were recalculated from the same retrieved records."
    trace = [
        f"Decision {request.decision_id} re-scored against dataset {active_dataset_metadata['dataset_id']}.",
        f"{len(source)} retrieved records recalculated using {decision.get('trace_details', {}).get('scoring_method', 'the original scoring model')}.",
        f"Normalized weights before: {decision['weights']}.",
        f"Normalized weights after: {weights_after}.",
        f"{changed} rank positions changed across the top 10.",
    ]
    return {"decision_id": request.decision_id, "dataset_id": active_dataset_metadata["dataset_id"], "current_ranking": current_ranking, "simulated_ranking": simulated_ranking, "changed_positions": changed, "changed_leads": changed_leads, "weights_before": normalize_weights(decision["weights"]), "weights_after": weights_after, "explanation": explanation, "trace": trace}


@app.post("/api/approval")
def approve(request: ApprovalRequest) -> dict:
    decision = decisions.get(request.decision_id) or storage.get_decision(request.decision_id)
    if decision is None:
        raise HTTPException(404, "Decision not found.")
    if decision.get("status") == "invalidated" or storage.is_dataset_deleted(decision.get("dataset_id", "")):
        raise HTTPException(409, "This decision is no longer available because its source dataset was deleted.")
    if decision.get("dataset_id") and decision["dataset_id"] != active_dataset_metadata["dataset_id"]:
        raise HTTPException(409, "The active dataset changed after this decision. Analyze again before approving it.")
    if request.action not in {"approve", "modify", "reject"}:
        raise HTTPException(400, "Action must be approve, modify, or reject.")
    if request.action == "reject" and not request.note.strip():
        raise HTTPException(400, "A rejection reason is required.")
    if request.action == "modify" and not (request.modified_recommendation or "").strip():
        raise HTTPException(400, "A modified recommendation is required.")
    approval = {"decision_id": request.decision_id, "action": request.action, "note": request.note, "recommendation": request.modified_recommendation, "timestamp": pd.Timestamp.now(tz="UTC").isoformat()}
    approvals[request.decision_id] = approval
    storage.save_approval(approval)
    return {"status": "recorded", "approval": approval}


@app.get("/api/evaluation")
def evaluation() -> dict:
    cases = [
        ("Lead prioritization", "Rank by evidence-backed score", "Deterministic ranking", "Source fields"),
        ("Revenue analysis", "Rank revenue opportunities", "Lead value weighted", "Lead value"),
        ("Customer inactivity", "Surface inactive and nurture records", "Status-filtered ranking", "Status and contact date"),
        ("Opportunity identification", "Surface top potential records", "Combined priority ranking", "Five score factors"),
        ("Ambiguous question", "Request clarification", "422 clarification", "Not applicable"),
        ("Missing data", "Do not invent missing values", "Missing factors score conservatively", "Null source fields"),
        ("Duplicate data", "Flag data quality issue", "Duplicate count surfaced", "Lead ID"),
        ("No matching records", "Return no-match response", "404 no matching records", "No records"),
    ]
    return {"label": "Prototype demo metrics; not measured production results", "metrics": {"evaluation_cases": "8 cases", "answer_accuracy": "Demo metric", "decision_accuracy": "Demo metric", "evidence_accuracy": "Demo metric", "average_response_time": "Demo metric", "failure_rate": "Demo metric"}, "baseline_minutes": 15, "target_minutes": 3, "cases": [{"test_case": row[0], "expected_decision": row[1], "system_decision": row[2], "evidence_match": row[3], "status": "Ready"} for row in cases]}