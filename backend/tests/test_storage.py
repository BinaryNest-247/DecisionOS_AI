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
<<<<<<< HEAD
    assert storage.get_approval("missing") is None


def test_delete_dataset_records_removes_only_matching_decisions_and_approvals(tmp_path):
    storage = DecisionStorage(tmp_path / "decisions.sqlite3")
    storage.save_decision({"id": "deleted", "dataset_id": "demo-id", "created_at": "2026-10-01T12:00:00Z"})
    storage.save_decision({"id": "kept", "dataset_id": "other-id", "created_at": "2026-10-01T13:00:00Z"})
    storage.save_approval({"decision_id": "deleted", "action": "approve"})
    storage.save_approval({"decision_id": "kept", "action": "approve"})

    assert storage.delete_dataset_records("demo-id") == 1

    assert storage.get_decision("deleted") is None
    assert storage.get_approval("deleted") is None
    assert storage.get_latest_decision()["id"] == "kept"
    assert storage.get_approval("kept")["action"] == "approve"
    assert storage.is_dataset_deleted("demo-id")
=======
    assert storage.get_approval("missing") is None
>>>>>>> 8e03c96660b8785c021372d016b8b39ca7766d71
