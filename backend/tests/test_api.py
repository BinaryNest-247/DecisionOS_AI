from fastapi.testclient import TestClient
from pathlib import Path
from io import BytesIO

import pandas as pd
import xlwt

from app import main
from app.main import app
from app.services.scoring import score_inactive_leads
from app.services.storage import DecisionStorage

client = TestClient(app)

GENERIC_CSV = b"Product,Region,Revenue,Quantity,Order Date,Customer,Purchase Amount\nAlpha,North,100,2,2024-01-02,Acme,100\nAlpha,South,200,3,2024-02-12,Beacon,200\nBeta,North,50,1,2024-02-20,Acme,50\n"


def upload_csv(content=GENERIC_CSV, filename="customer_sales.csv"):
    return client.post("/api/data/upload", files={"file": (filename, content, "text/csv")})


def test_demo_analysis_evidence_simulation_and_approval():
    client.post("/api/data/demo")
    assert client.get("/health").json()["status"] == "online"
    response = client.post("/api/decision/analyze", json={"question": "Which 10 leads should our sales team contact first this week?"})
    assert response.status_code == 200
    decision = response.json()
    assert len(decision["leads"]) == 10
    assert decision["leads"][0]["contributions"]["revenue"] >= 0
    assert client.get(f"/api/decision/{decision['id']}").json()["id"] == decision["id"]
    assert len(client.get(f"/api/decision/{decision['id']}/evidence").json()["evidence"]) == 10
    simulation = client.post("/api/simulation/run", json={"decision_id": decision["id"], "weights": {"revenue": 0.05, "engagement": 0.05, "recency": 0.8, "purchases": 0.05, "status": 0.05}})
    assert simulation.status_code == 200
    assert len(simulation.json()["simulated_ranking"]) == 10
    simulation_result = simulation.json()
    current_scores = {lead["lead_id"]: lead["score"] for lead in simulation_result["current_ranking"]}
    simulated_scores = {lead["lead_id"]: lead["score"] for lead in simulation_result["simulated_ranking"]}
    assert any(current_scores[key] != simulated_scores[key] for key in current_scores.keys() & simulated_scores.keys())
    assert simulation_result["weights_after"]["recency"] == 0.8
    assert simulation_result["changed_positions"] == sum(
        old["lead_id"] != new["lead_id"]
        for old, new in zip(simulation_result["current_ranking"], simulation_result["simulated_ranking"])
    )
    approval = client.post("/api/approval", json={"decision_id": decision["id"], "action": "approve"})
    assert approval.json()["approval"]["action"] == "approve"


def test_latest_decision_evidence_and_persisted_approval_routes(monkeypatch, tmp_path):
    isolated_storage = DecisionStorage(tmp_path / "decisions.sqlite3")
    monkeypatch.setattr(main, "storage", isolated_storage)
    client.post("/api/data/demo")
    created = client.post("/api/decision/analyze", json={"question": "Which 10 leads should our sales team contact first this week?"}).json()

    latest = client.get("/api/decision/latest")
    assert latest.status_code == 200
    assert latest.json()["decision"]["id"] == created["id"]
    assert latest.json()["approval"] is None
    assert latest.json()["decision"]["trace_details"]["dataset_filename"] == "demo_sales_data.csv"
    assert latest.json()["decision"]["trace_details"]["evidence_records"] == len(created["evidence"])

    evidence = client.get(f"/api/decision/{created['id']}/evidence").json()
    assert evidence["dataset_id"] == created["dataset_id"]
    assert evidence["trace_details"] == created["trace_details"]
    assert len(evidence["evidence"]) == len(created["leads"])
    assert client.get(f"/api/decision/{created['id']}/approval").json()["approval"] is None

    approved = client.post("/api/approval", json={"decision_id": created["id"], "action": "approve", "note": "Reviewed."})
    assert approved.status_code == 200
    assert client.get(f"/api/decision/{created['id']}/approval").json()["approval"]["action"] == "approve"

    modified = client.post("/api/approval", json={"decision_id": created["id"], "action": "modify", "modified_recommendation": "Contact after review", "note": "Wait for a call window."})
    assert modified.status_code == 200
    assert client.get(f"/api/decision/{created['id']}/approval").json()["approval"]["recommendation"] == "Contact after review"
    assert client.get("/api/decision/latest").json()["approval"]["action"] == "modify"
    assert client.post("/api/approval", json={"decision_id": created["id"], "action": "modify", "modified_recommendation": "  "}).status_code == 400


def test_latest_decision_returns_clear_404_when_storage_is_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "storage", DecisionStorage(tmp_path / "empty.sqlite3"))

    response = client.get("/api/decision/latest")

    assert response.status_code == 404
    assert response.json()["detail"] == "No decision has been created yet."


def test_application_starts_with_no_dataset_loaded():
    main.records = pd.DataFrame()
    main.active_dataset_metadata = {"filename": "No dataset loaded", "file_type": "", "source": "none", "dataset_id": "", "sheet_names": [], "selected_sheet": None}

    response = client.get("/api/data/summary")

    assert response.status_code == 200
    assert response.json()["summary"]["filename"] == "No dataset loaded"
    assert response.json()["summary"]["dataset_id"] == ""
    assert response.json()["summary"]["rows"] == 0
    assert response.json()["summary"]["data_quality"] == 0


def test_delete_dataset_clears_associated_state_and_not_other_dataset(monkeypatch, tmp_path):
    isolated_storage = DecisionStorage(tmp_path / "decisions.sqlite3")
    monkeypatch.setattr(main, "storage", isolated_storage)
    client.post("/api/data/demo")
    deleted = client.post("/api/decision/analyze", json={"question": "Which leads should our sales team contact first?"}).json()
    client.post("/api/approval", json={"decision_id": deleted["id"], "action": "approve"})

    client.post("/api/data/demo")
    retained = client.post("/api/decision/analyze", json={"question": "Which leads should our sales team contact first?"}).json()
    response = client.delete(f"/api/dataset/{deleted['dataset_id']}")

    assert response.status_code == 200
    assert client.get(f"/api/decision/{deleted['id']}").status_code == 404
    assert client.get(f"/api/decision/{deleted['id']}/approval").status_code == 404
    assert client.post("/api/simulation/run", json={"decision_id": deleted["id"], "weights": deleted["weights"]}).status_code == 404
    assert client.get("/api/decision/latest").json()["decision"]["id"] == retained["id"]
    assert isolated_storage.get_approval(deleted["id"]) is None

    active_id = main.active_dataset_metadata["dataset_id"]
    assert active_id != deleted["dataset_id"]
    cleared = client.delete(f"/api/dataset/{active_id}")
    assert cleared.status_code == 200
    summary = client.get("/api/data/summary").json()["summary"]
    assert summary["filename"] == "No dataset loaded"
    assert summary["dataset_id"] == ""
    assert summary["rows"] == 0
    assert client.get("/api/decision/latest").status_code == 404


def test_inactivity_simulation_uses_adjustable_inactivity_scoring_and_normalized_weights():
    client.post("/api/data/demo")
    decision = client.post("/api/decision/analyze", json={"question": "Which inactive customers should we re-engage?"}).json()
    assert decision["intent"] == "customer_inactivity"
    source_ids = decision["retrieved_record_ids"]
    source = main.records[main.records["lead_id"].astype(str).isin(source_ids)]
    baseline = score_inactive_leads(source, decision["weights"]).head(10)
    scenario_weights = {"revenue": 40, "engagement": 10, "recency": 10, "purchases": 10, "status": 30}

    simulated = client.post("/api/simulation/run", json={"decision_id": decision["id"], "weights": scenario_weights})

    assert simulated.status_code == 200
    payload = simulated.json()
    assert payload["decision_id"] == decision["id"]
    assert [lead["lead_id"] for lead in payload["current_ranking"]] == baseline["lead_id"].astype(str).tolist()
    assert len(payload["simulated_ranking"]) == 10
    assert payload["weights_after"] == {"revenue": 0.4, "engagement": 0.1, "recency": 0.1, "purchases": 0.1, "status": 0.3}
    assert sum(payload["weights_after"].values()) == 1
    assert payload["changed_positions"] == sum(
        old["lead_id"] != new["lead_id"]
        for old, new in zip(payload["current_ranking"], payload["simulated_ranking"])
    )

    unchanged = client.post("/api/simulation/run", json={"decision_id": decision["id"], "weights": decision["weights"]}).json()
    assert unchanged["changed_positions"] == 0
    assert "unchanged" in unchanged["explanation"].lower()
    assert client.post("/api/simulation/run", json={"decision_id": decision["id"], "weights": {"revenue": -1}}).status_code == 422
    assert client.post("/api/simulation/run", json={"decision_id": decision["id"], "weights": {"revenue": 0}}).status_code == 422


def test_old_dataset_decision_is_rejected_by_evidence_simulation_and_approval():
    client.post("/api/data/demo")
    decision = client.post("/api/decision/analyze", json={"question": "Which leads should our sales team contact first?"}).json()
    upload_csv()

    evidence = client.get(f"/api/decision/{decision['id']}/evidence")
    simulation = client.post("/api/simulation/run", json={"decision_id": decision["id"], "weights": decision["weights"]})
    approval = client.post("/api/approval", json={"decision_id": decision["id"], "action": "approve"})

    assert evidence.status_code == simulation.status_code == approval.status_code == 409
    client.post("/api/data/demo")


def test_ambiguous_question_requests_clarification():
    client.post("/api/data/demo")
    response = client.post("/api/decision/analyze", json={"question": "What should I do?"})
    assert response.status_code == 422
    assert "clarify" in response.json()["detail"].lower()


def test_rejection_requires_reason():
    client.post("/api/data/demo")
    decision = client.post("/api/decision/analyze", json={"question": "Which leads should we prioritize this week?"}).json()
    response = client.post("/api/approval", json={"decision_id": decision["id"], "action": "reject"})
    assert response.status_code == 400

    rejected = client.post("/api/approval", json={"decision_id": decision["id"], "action": "reject", "note": "Insufficient budget this quarter."})
    assert rejected.status_code == 200
    assert rejected.json()["approval"]["action"] == "reject"
    assert client.get(f"/api/decision/{decision['id']}/approval").json()["approval"]["note"] == "Insufficient budget this quarter."


def test_csv_upload_parses_synthetic_demo_file():
    csv_path = Path(__file__).resolve().parents[2] / "data" / "demo_sales_data.csv"
    response = client.post("/api/data/upload", files={"file": ("demo.csv", csv_path.read_bytes(), "text/csv")})
    assert response.status_code == 200
    assert response.json()["summary"]["rows"] == 360
    assert response.json()["summary"]["duplicates"] == 3
    assert all(item["month"] != "NaT" for item in response.json()["summary"]["revenue_opportunity"])


def test_revenue_question_weights_revenue_more_heavily():
    client.post("/api/data/demo")
    decision = client.post("/api/decision/analyze", json={"question": "Where is our biggest revenue opportunity?"}).json()
    assert decision["intent"] == "revenue_opportunity"
    assert decision["weights"]["revenue"] > decision["weights"]["engagement"]


def test_no_matching_records_returns_explicit_error(monkeypatch):
    client.post("/api/data/demo")
    original = main.records
    monkeypatch.setattr(main, "records", original[original["lead_status"] == "Active"].copy())
    response = client.post("/api/decision/analyze", json={"question": "Which inactive customers should we re-engage?"})
    assert response.status_code == 404
    assert "no matching" in response.json()["detail"].lower()


def test_records_without_decision_fields_return_insufficient_evidence(monkeypatch):
    client.post("/api/data/demo")
    original = main.records
    empty = original.iloc[:1].copy()
    empty[["lead_value", "engagement_score", "previous_purchases", "last_contact_date", "lead_status"]] = None
    monkeypatch.setattr(main, "records", empty)
    response = client.post("/api/decision/analyze", json={"question": "Which leads should we prioritize this week?"})
    assert response.status_code == 422
    assert "insufficient evidence" in response.json()["detail"].lower()


def test_conflicting_duplicate_records_block_analysis(monkeypatch):
    client.post("/api/data/demo")
    original = main.records
    duplicate = original.iloc[[0]].copy()
    duplicate["company"] = "Conflicting Source Record"
    monkeypatch.setattr(main, "records", pd.concat([original, duplicate], ignore_index=True))
    response = client.post("/api/decision/analyze", json={"question": "Which leads should we prioritize this week?"})
    assert response.status_code == 409
    assert "conflicting data detected" in response.json()["detail"].lower()


def test_historical_performance_question_requires_historical_data():
    client.post("/api/data/demo")
    response = client.post("/api/decision/analyze", json={"question": "What changed in our sales performance?"})
    assert response.status_code == 422
    assert "historical sales performance" in response.json()["detail"].lower()


def test_general_csv_profile_and_pandas_analytics_with_followups():
    uploaded = upload_csv()
    assert uploaded.status_code == 200
    summary = uploaded.json()["summary"]
    assert summary["filename"] == "customer_sales.csv"
    assert summary["rows"] == 3
    assert "Revenue" in summary["numeric_columns"]
    assert "Product" in summary["categorical_columns"]
    assert "Order Date" in summary["date_columns"]
    assert summary["supports_lead_decisions"] is False
    assert summary["numeric_correlations"]
    assert summary["numeric_correlations"][0]["paired_rows"] == 3
    assert client.get("/api/data/summary").json()["summary"]["filename"] == "customer_sales.csv"
    assert len(client.get("/api/data/preview").json()["rows"]) == 3
    profile = client.get("/api/data/profile").json()
    assert profile["filename"] == "customer_sales.csv"
    assert profile["column_profiles"][0]["missing_percentage"] == 0
    assert profile["column_profiles"][0]["top_values"]

    result = client.post("/api/analytics/query", json={"question": "Which product generated the highest revenue?"}).json()
    assert result["result"][0]["Product"] == "Alpha"
    assert result["result"][0]["Revenue"] == 300
    assert result["calculation"] == {"metric": "Revenue", "operation": "sum", "group_by": "Product", "sort": "descending"}
    assert result["chart"]["type"] == "bar"
    assert result["evidence"]

    second = client.post("/api/chat", json={"question": "What about the second highest?"}).json()
    assert second["follow_up"] is True
    assert second["result"][0]["Product"] == "Beta"
    trend = client.post("/api/chat", json={"question": "Show its monthly trend."}).json()
    assert trend["intent"] == "date_trend"
    assert trend["chart"]["type"] == "line"
    assert trend["result"][0]["period"].startswith("2024-")


def test_numeric_correlations_require_three_complete_rows_and_ignore_constant_pairs():
    csv = b"A,B,Constant\n1,2,5\n2,4,5\n3,6,5\n,8,5\n"
    uploaded = upload_csv(csv)
    assert uploaded.status_code == 200
    correlations = uploaded.json()["summary"]["numeric_correlations"]
    assert correlations == [{"column_a": "A", "column_b": "B", "correlation": 1.0, "paired_rows": 3}]


def test_analytics_uses_deterministic_fallback_without_llm(monkeypatch):
    monkeypatch.setattr(main.ai_service, "plan_analytics", lambda question, columns: None)
    monkeypatch.setattr(main.ai_service, "explain_analytics", lambda question, answer, result, evidence: answer)
    assert upload_csv().status_code == 200

    response = client.post("/api/analytics/query", json={"question": "Which product generated the highest revenue?"})

    assert response.status_code == 200
    assert response.json()["result"][0]["Product"] == "Alpha"
    assert response.json()["result"][0]["Revenue"] == 300
    assert response.json()["evidence"]
    assert response.json()["chart"]["type"] == "bar"


def test_llm_provider_endpoints_report_status_and_switch_provider(monkeypatch):
    original = main.llm_service.active_provider
    monkeypatch.setenv("GROQ_API_KEY", "test-provider-key")
    try:
        status = client.get("/api/llm/providers").json()
        assert status["active_provider"] == original
        assert next(item for item in status["providers"] if item["name"] == "groq")["configured"]
        assert "test-provider-key" not in str(status)
        changed = client.post("/api/llm/provider", json={"provider": "groq"})
        assert changed.status_code == 200
        assert changed.json()["active_provider"] == "groq"
        assert client.post("/api/llm/provider", json={"provider": "invalid"}).status_code == 422
    finally:
        main.llm_service.set_provider(original)


def test_numeric_unique_missing_filter_and_duplicate_queries_use_active_data():
    csv = b"Customer,Purchase Amount,Region\nAcme,100,North\nBeacon,200,South\nAcme,100,North\n, ,South\n"
    assert upload_csv(csv).status_code == 200
    average = client.post("/api/analytics/query", json={"question": "What is the average purchase amount?"}).json()
    assert average["result"][0]["value"] == 133.33333333333334
    unique = client.post("/api/analytics/query", json={"question": "How many unique customers are there?"}).json()
    assert unique["result"][0]["unique_count"] == 2
    missing = client.post("/api/analytics/query", json={"question": "Are there any missing values?"}).json()
    assert "2 missing values" in missing["answer"]
    filtered = client.post("/api/analytics/query", json={"question": "Show customers whose purchase amount is above 150."}).json()
    assert filtered["rows_analyzed"] == 1
    assert filtered["result"][0]["Customer"] == "Beacon"
    duplicate = client.post("/api/analytics/query", json={"question": "Find duplicate records."}).json()
    assert duplicate["rows_analyzed"] == 1
    comparison = client.post("/api/analytics/query", json={"question": "Compare revenue between North and South regions."}).json()
    assert {row["Region"] for row in comparison["result"]} == {"North", "South"}
    share = client.post("/api/analytics/query", json={"question": "What percentage of revenue came from each region?"}).json()
    assert share["chart"]["type"] == "pie"
    assert share["chart"]["y_key"] == "percentage"
    assert sum(row["percentage"] for row in share["result"]) == 100


def test_standard_deviation_correlation_distribution_and_category_follow_up():
    csv = b"Region,Sales,Quantity\nNorth,100,1\nNorth,200,2\nSouth,50,3\nSouth,150,4\n"
    assert upload_csv(csv).status_code == 200

    deviation = client.post("/api/analytics/query", json={"question": "What is the standard deviation of Sales?"}).json()
    assert deviation["operation"] == "std"
    assert round(deviation["result"][0]["value"], 6) == round(pd.Series([100, 200, 50, 150]).std(), 6)

    correlation = client.post("/api/analytics/query", json={"question": "What is the correlation between Sales and Quantity?"}).json()
    assert correlation["operation"] == "correlation"
    assert correlation["result"][0]["paired_rows"] == 4
    assert correlation["evidence"]

    distribution = client.post("/api/analytics/query", json={"question": "Show the distribution of Sales."}).json()
    assert distribution["chart"]["type"] == "bar"
    assert sum(row["count"] for row in distribution["result"]) == 4

    highest = client.post("/api/chat", json={"question": "Which region generated the highest sales?"}).json()
    assert highest["result"][0]["Region"] == "North"
    south = client.post("/api/chat", json={"question": "What about South?"}).json()
    assert south["follow_up"] is True
    assert south["result"][0]["Region"] == "South"
    assert south["result"][0]["Sales"] == 200


def test_validated_structured_filter_executes_against_active_dataset(monkeypatch):
    assert upload_csv(b"Customer,Sales,Region\nAcme,100,North\nBeacon,200,South\nCedar,50,South\n").status_code == 200
    monkeypatch.setattr(main.ai_service, "plan_analytics", lambda question, columns: {
        "intent": "filter",
        "metric": "Sales",
        "group_by": None,
        "operation": "filter",
        "sort": "none",
        "limit": 20,
        "filters": [{"column": "Sales", "operator": "gt", "value": 100}],
    })

    response = client.post("/api/analytics/query", json={"question": "Filter records by Sales over 100."})

    assert response.status_code == 200
    assert response.json()["rows_analyzed"] == 1
    assert response.json()["result"][0]["Customer"] == "Beacon"
    assert response.json()["evidence"][0]["Sales"] == 200


def test_xlsx_multisheet_upload_selects_and_profiles_actual_sheet():
    workbook = BytesIO()
    with pd.ExcelWriter(workbook, engine="openpyxl") as writer:
        pd.DataFrame({"Product": ["A", "B"], "Revenue": [12, 25]}).to_excel(writer, sheet_name="Sales", index=False)
        pd.DataFrame({"Department": ["Care", "Surgery"], "Cost": [70, 120]}).to_excel(writer, sheet_name="Costs", index=False)
    response = client.post("/api/data/upload", files={"file": ("operations.xlsx", workbook.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert response.status_code == 200
    assert response.json()["summary"]["sheet_names"] == ["Sales", "Costs"]
    assert response.json()["summary"]["selected_sheet"] == "Sales"
    selected = client.post("/api/data/select-sheet", json={"sheet_name": "Costs"})
    assert selected.status_code == 200
    assert selected.json()["summary"]["columns_list"] == ["Department", "Cost"]
    assert selected.json()["summary"]["filename"] == "operations.xlsx"
    answer = client.post("/api/analytics/query", json={"question": "What is the total cost?"}).json()
    assert answer["result"][0]["value"] == 190


def test_xls_upload_uses_xlrd_reader():
    workbook = xlwt.Workbook()
    sheet = workbook.add_sheet("Transactions")
    for column, value in enumerate(("Transaction ID", "Amount", "Category")):
        sheet.write(0, column, value)
    for row, values in enumerate((("TX-1", 150, "Travel"), ("TX-2", 225, "Supplies")), start=1):
        for column, value in enumerate(values):
            sheet.write(row, column, value)
    legacy_file = BytesIO()
    workbook.save(legacy_file)
    response = client.post("/api/data/upload", files={"file": ("transactions.xls", legacy_file.getvalue(), "application/vnd.ms-excel")})
    assert response.status_code == 200
    assert response.json()["summary"]["rows"] == 2
    assert response.json()["summary"]["filename"] == "transactions.xls"
    assert response.json()["summary"]["numeric_columns"] == ["Amount"]


def test_upload_rejects_unsupported_empty_and_corrupt_files():
    unsupported = client.post("/api/data/upload", files={"file": ("dataset.json", b"{}", "application/json")})
    assert unsupported.status_code == 400
    assert "unsupported file format" in unsupported.json()["detail"].lower()
    empty = upload_csv(b"")
    assert empty.status_code == 400
    assert "no usable rows" in empty.json()["detail"].lower()
    corrupt_excel = client.post("/api/data/upload", files={"file": ("broken.xlsx", b"not a workbook", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert corrupt_excel.status_code == 400
    assert "valid" in corrupt_excel.json()["detail"].lower()
    empty_workbook = BytesIO()
    with pd.ExcelWriter(empty_workbook, engine="openpyxl") as writer:
        pd.DataFrame().to_excel(writer, sheet_name="Empty", index=False)
    empty_xlsx = client.post("/api/data/upload", files={"file": ("empty.xlsx", empty_workbook.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert empty_xlsx.status_code == 400
    assert "no usable rows" in empty_xlsx.json()["detail"].lower()


def test_empty_unknown_and_lead_only_decisions_are_safe_for_general_data():
    assert upload_csv().status_code == 200
    unknown = client.post("/api/analytics/query", json={"question": "Tell me something ungrounded."})
    assert unknown.status_code == 422
    decision = client.post("/api/decision/analyze", json={"question": "Which leads should we prioritize this week?"})
    assert decision.status_code == 422
    assert "lead decision scoring requires" in decision.json()["detail"].lower()


def test_min_max_categorical_filter_and_missing_date_query():
    assert upload_csv(GENERIC_CSV).status_code == 200
    lowest = client.post("/api/analytics/query", json={"question": "What is the minimum revenue?"}).json()
    assert lowest["result"][0]["value"] == 50
    highest = client.post("/api/analytics/query", json={"question": "What is the maximum revenue?"}).json()
    assert highest["result"][0]["value"] == 200
    north = client.post("/api/analytics/query", json={"question": "How many records are in North?"}).json()
    assert north["rows_analyzed"] == 2
    assert all(row["Region"] == "North" for row in north["result"])
    assert upload_csv(b"Region,Purchase Amount\nNorth,10\nSouth,20\n").status_code == 200
    no_date = client.post("/api/analytics/query", json={"question": "Show monthly purchase amount trend."})
    assert no_date.status_code == 422
    assert "no date column" in no_date.json()["detail"].lower()