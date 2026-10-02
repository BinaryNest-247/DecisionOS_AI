from __future__ import annotations

from datetime import date
import math
from typing import Any
from uuid import uuid4

import numpy as np
import pandas as pd

DEFAULT_WEIGHTS = {"revenue": 0.30, "engagement": 0.25, "recency": 0.20, "purchases": 0.15, "status": 0.10}
INACTIVE_DEFAULT_WEIGHTS = {"revenue": 0.05, "engagement": 0.20, "recency": 0.50, "purchases": 0.05, "status": 0.20}


def normalize_weights(
    weights: dict[str, float] | None,
    defaults: dict[str, float] = DEFAULT_WEIGHTS,
) -> dict[str, float]:
    supplied = weights or {}
    unknown = set(supplied) - set(defaults)
    if unknown:
        raise ValueError(f"Unknown scoring factors: {', '.join(sorted(unknown))}.")
    supplied_values = [float(value) for value in supplied.values()]
    percent_scale = 100.0 if any(value > 1 for value in supplied_values) or sum(supplied_values) > 1.000001 else 1.0
    values = {
        key: float(supplied[key]) if key in supplied else value * percent_scale
        for key, value in defaults.items()
    }
    if any(not math.isfinite(value) or value < 0 for value in values.values()):
        raise ValueError("Weights must be finite, non-negative numbers.")
    total = sum(values.values())
    if total <= 0:
        raise ValueError("At least one scoring weight must be greater than zero.")
    return {key: value / total for key, value in values.items()}


def _normalized(series: pd.Series, default: float = 0.0) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    low, high = values.min(), values.max()
    if pd.isna(low) or pd.isna(high):
        return pd.Series(default, index=series.index, dtype=float)
    if high == low:
        return pd.Series(0.5, index=series.index, dtype=float)
    return ((values - low) / (high - low)).fillna(default)


def score_leads(records: pd.DataFrame, weights: dict[str, float] | None = None) -> pd.DataFrame:
    active_weights = normalize_weights(weights)
    result = records.copy()
    revenue = _normalized(result["lead_value"])
    engagement = (pd.to_numeric(result["engagement_score"], errors="coerce").fillna(0) / 100).clip(0, 1)
    purchases = _normalized(result["previous_purchases"])
    contact_dates = pd.to_datetime(result["last_contact_date"], errors="coerce")
    days_since = (pd.Timestamp(date.today()) - contact_dates).dt.days
    recency = (1 - days_since.clip(lower=0, upper=180).fillna(180) / 180).clip(0, 1)
    statuses = result["lead_status"].fillna("").str.lower()
    status = statuses.map({"active": 1.0, "qualified": 0.9, "new": 0.75, "nurture": 0.55, "inactive": 0.15, "closed": 0.05}).fillna(0.3)
    factors = {
        "revenue": revenue * 100 * active_weights["revenue"],
        "engagement": engagement * 100 * active_weights["engagement"],
        "recency": recency * 100 * active_weights["recency"],
        "purchases": purchases * 100 * active_weights["purchases"],
        "status": status * 100 * active_weights["status"],
    }
    result["score"] = sum(factors.values()).round().astype(int)
    for key, contribution in factors.items():
        result[f"{key}_contribution"] = contribution.round(1)
    result["priority"] = np.select([result["score"] >= 67, result["score"] >= 38], ["HIGH", "MEDIUM"], default="LOW")
    return result.sort_values(["score", "lead_value"], ascending=False, na_position="last")


def score_inactive_leads(records: pd.DataFrame, weights: dict[str, float] | None = None) -> pd.DataFrame:
    active_weights = normalize_weights(weights, INACTIVE_DEFAULT_WEIGHTS)
    result = records.copy()
    contact_dates = pd.to_datetime(result["last_contact_date"], errors="coerce")
    days_since = (pd.Timestamp(date.today()) - contact_dates).dt.days.clip(lower=0, upper=180).fillna(180)
    status = result["lead_status"].fillna("").str.lower().map({"inactive": 1.0, "nurture": 0.8}).fillna(0.2)
    factors = {
        "revenue": _normalized(result["lead_value"]) * 100 * active_weights["revenue"],
        "engagement": (pd.to_numeric(result["engagement_score"], errors="coerce").fillna(0) / 100).clip(0, 1) * 100 * active_weights["engagement"],
        "recency": days_since.div(180) * 100 * active_weights["recency"],
        "purchases": _normalized(result["previous_purchases"]) * 100 * active_weights["purchases"],
        "status": status * 100 * active_weights["status"],
    }
    result["score"] = sum(factors.values()).round().astype(int)
    for name, contribution in factors.items():
        result[f"{name}_contribution"] = contribution.round(1)
    result["priority"] = np.select([result["score"] >= 67, result["score"] >= 38], ["HIGH", "MEDIUM"], default="LOW")
    return result.sort_values("score", ascending=False, na_position="last")


def score_for_decision(decision: dict[str, Any], records: pd.DataFrame, weights: dict[str, float]) -> pd.DataFrame:
    if decision.get("intent") == "customer_inactivity":
        return score_inactive_leads(records, weights)
    return score_leads(records, weights)


def serialize_lead(row: pd.Series, intent: str = "lead_prioritization") -> dict[str, Any]:
    last_contact = pd.to_datetime(row.get("last_contact_date"), errors="coerce")
    days_since = (pd.Timestamp(date.today()) - last_contact).days if not pd.isna(last_contact) else None
    contributions = {key: float(row.get(f"{key}_contribution", 0)) for key in ("revenue", "engagement", "recency", "purchases", "status")}
    positive = [
        "Inactivity Duration" if name == "recency" and intent == "customer_inactivity"
        else "Recent Activity" if name == "recency"
        else name.title()
        for name, value in contributions.items()
        if value >= 12
    ]
    return {
        "lead_id": str(row.get("lead_id", "")), "company": str(row.get("company") or "Unknown company"),
        "industry": row.get("industry"), "lead_value": float(row["lead_value"]) if pd.notna(row.get("lead_value")) else None,
        "engagement_score": float(row["engagement_score"]) if pd.notna(row.get("engagement_score")) else None,
        "previous_purchases": int(row["previous_purchases"]) if pd.notna(row.get("previous_purchases")) else None,
        "last_contact_date": last_contact.strftime("%Y-%m-%d") if not pd.isna(last_contact) else None,
        "days_since_contact": int(days_since) if days_since is not None else None,
        "lead_status": row.get("lead_status"), "sales_activity": row.get("sales_activity"),
        "customer_segment": row.get("customer_segment"), "region": row.get("region"), "sales_rep": row.get("sales_rep"),
        "score": int(row["score"]), "priority": str(row["priority"]), "contributions": contributions,
        "reason": " + ".join(positive[:3]) or "Best available combined score",
    }


def new_decision_id() -> str:
    return str(uuid4())