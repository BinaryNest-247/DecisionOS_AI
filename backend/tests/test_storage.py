import sqlite3

from app.services.storage import DecisionStorage


def test_latest_decision_uses_created_at_not_insert_order(tmp_path):
    storage = DecisionStorage(tmp_path / "decisions.sqlite3")
    storage.save_decision({"id": "newest", "created_at": "2026-10-01T12:00:00+00:00"})
    storage.save_decision({"id": "older", "created_at": "2026-10-01T10:00:00+00:00"})

    assert storage.get_latest_decision()["id"] == "newest"


def test_latest_decision_skips_invalid_json_and_approval_round_trips(tmp_path):
    storage = DecisionStorage(tmp_path / "decisions.sqlite3")
    storage.save_decision({"id": "valid", "created_at": "2026-10-01T10:00:00Z"})
    with sqlite3.connect(storage.path) as connection:
        connection.execute("INSERT INTO decisions(id, payload) VALUES (?, ?)", ("broken", "not-json"))
    approval = {"decision_id": "valid", "action": "modify", "note": "Adjusted", "recommendation": "Contact later", "timestamp": "2026-10-01T11:00:00Z"}
    storage.save_approval(approval)

    assert storage.get_latest_decision()["id"] == "valid"
    assert storage.get_approval("valid") == approval
    assert storage.get_approval("missing") is None