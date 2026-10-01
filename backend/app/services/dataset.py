from pathlib import Path
import re
from typing import Any

import numpy as np
import pandas as pd

from app.services.scoring import score_leads

ROOT = Path(__file__).resolve().parents[3]
DEMO_PATH = ROOT / "data" / "demo_sales_data.csv"
REQUIRED_COLUMNS = ["lead_id", "company", "industry", "lead_value", "engagement_score", "previous_purchases", "last_contact_date", "lead_status", "sales_activity", "customer_segment", "region", "sales_rep"]
NUMERIC_TERMS = ("revenue", "sales", "amount", "price", "cost", "value", "quantity", "spend", "total", "profit", "count", "discount")


def has_lead_schema(frame: pd.DataFrame) -> bool:
    return all(column in frame.columns for column in REQUIRED_COLUMNS)


def load_demo() -> pd.DataFrame:
    return pd.read_csv(DEMO_PATH)


def validate_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or frame.shape[1] == 0 or not frame.notna().any().any():
        raise ValueError("The uploaded file contains no usable rows.")
    cleaned = frame.copy()
    preprocessing: list[str] = []
    columns: list[str] = []
    for index, original in enumerate(cleaned.columns):
        name = str(original).strip() or f"unnamed_column_{index + 1}"
        if re.fullmatch(r"Unnamed:\s*\d+", name, re.I):
            name = f"unnamed_column_{index + 1}"
        if name != str(original):
            preprocessing.append(f"Trimmed column name '{original}' to '{name}'.")
        if name in columns:
            base = name
            suffix = 2
            while f"{base}_{suffix}" in columns:
                suffix += 1
            name = f"{base}_{suffix}"
            preprocessing.append(f"Renamed duplicate column to '{name}'.")
        columns.append(name)
    cleaned.columns = columns

    for column in cleaned.columns:
        values = cleaned[column]
        if pd.api.types.is_numeric_dtype(values) or pd.api.types.is_datetime64_any_dtype(values):
            continue
        if re.search(r"\b(id|identifier|code|sku)\b", column, re.I):
            continue
        non_missing = values.notna().sum()
        if not non_missing:
            continue
        text = values.astype("string").str.strip()
        numeric_text = text.str.replace(r"[,$₹%\s]", "", regex=True)
        numeric = pd.to_numeric(numeric_text, errors="coerce")
        if numeric.notna().sum() / non_missing >= 0.7:
            cleaned[column] = numeric
            preprocessing.append(f"Detected numeric values in '{column}'.")
            continue
        date_hint = bool(re.search(r"date|time|month|year|created|updated|admission", column, re.I))
        date_sample = text.dropna().head(20)
        date_pattern = r"(?:\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b|\b\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}\b|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2},?\s+\d{4}\b)"
        date_hint = date_hint or bool(len(date_sample) and date_sample.str.contains(date_pattern, case=False, regex=True).mean() >= 0.7)
        if date_hint:
            dates = pd.to_datetime(values, errors="coerce", format="mixed")
            if dates.notna().sum() / non_missing >= 0.7:
                cleaned[column] = dates
                preprocessing.append(f"Parsed date values in '{column}'.")
    cleaned.attrs["preprocessing"] = preprocessing
    return cleaned


def _json_value(value: Any) -> Any:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return pd.Timestamp(value).isoformat()
    if isinstance(value, np.generic):
        return value.item()
    return value


def _preferred_numeric(frame: pd.DataFrame) -> str | None:
    numeric = [column for column in frame.columns if pd.api.types.is_numeric_dtype(frame[column])]
    return next((column for term in NUMERIC_TERMS for column in numeric if term in column.lower()), numeric[0] if numeric else None)


def _suggestions(frame: pd.DataFrame, numeric: list[str], categorical: list[str], dates: list[str]) -> list[str]:
    questions: list[str] = []
    metric = _preferred_numeric(frame)
    if metric:
        questions.append(f"What is the total {metric}?")
        questions.append(f"What is the average {metric}?")
        if categorical:
            questions.append(f"Which {categorical[0]} has the highest {metric}?")
            questions.append(f"Show {metric} by {categorical[0]}.")
        if dates:
            questions.append(f"Show monthly {metric} trend by {dates[0]}.")
    elif categorical:
        questions.append(f"How many unique {categorical[0]} are there?")
        questions.append(f"Show the top 5 {categorical[0]} values.")
    questions.append("Are there any missing values?")
    return questions[:5]


def summarize(frame: pd.DataFrame, metadata: dict[str, Any] | None = None) -> dict:
    metadata = metadata or {}
    rows, columns = len(frame), list(frame.columns)
    duplicate_rows = int(frame.duplicated().sum())
    missing_by_column = frame.isna().sum().astype(int).to_dict()
    missing = int(sum(missing_by_column.values()))
    numeric_columns = [column for column in columns if pd.api.types.is_numeric_dtype(frame[column])]
    date_columns = [column for column in columns if pd.api.types.is_datetime64_any_dtype(frame[column])]
    categorical_columns = [column for column in columns if column not in numeric_columns and column not in date_columns]
    numeric_correlations: list[dict[str, Any]] = []
    if len(numeric_columns) > 1:
        numeric_frame = frame[numeric_columns]
        correlation_matrix = numeric_frame.corr(min_periods=3)
        for left_index, left in enumerate(numeric_columns):
            for right in numeric_columns[left_index + 1:]:
                coefficient = correlation_matrix.loc[left, right]
                paired_rows = int(numeric_frame[[left, right]].dropna().shape[0])
                if pd.notna(coefficient) and paired_rows >= 3:
                    numeric_correlations.append({
                        "column_a": str(left),
                        "column_b": str(right),
                        "correlation": float(coefficient),
                        "paired_rows": paired_rows,
                    })
        numeric_correlations.sort(key=lambda item: abs(item["correlation"]), reverse=True)
        numeric_correlations = numeric_correlations[:10]
    profiles = []
    for column in columns:
        values = frame[column]
        profile: dict[str, Any] = {
            "name": column,
            "dtype": "datetime" if column in date_columns else "numeric" if column in numeric_columns else "categorical",
            "missing": int(values.isna().sum()),
            "missing_percentage": round(float(values.isna().mean() * 100), 2) if rows else 0.0,
            "unique": int(values.nunique(dropna=True)),
        }
        if column in numeric_columns:
            numeric = pd.to_numeric(values, errors="coerce")
            profile.update({"min": _json_value(numeric.min()), "max": _json_value(numeric.max()), "mean": _json_value(numeric.mean()), "median": _json_value(numeric.median()), "sum": _json_value(numeric.sum()), "std": _json_value(numeric.std())})
        elif column in date_columns:
            profile.update({"min": _json_value(values.min()), "max": _json_value(values.max())})
        else:
            profile["top_values"] = [
                {"value": _json_value(value), "count": int(count)}
                for value, count in values.dropna().value_counts().head(5).items()
            ]
        profiles.append(profile)

    lead_mode = has_lead_schema(frame)
    priority_distribution: dict[str, int] = {}
    high_priority_leads = 0
    potential_revenue = 0.0
    outdated_records = 0
    if lead_mode:
        scored = score_leads(frame)
        priority_distribution = {str(key): int(value) for key, value in scored["priority"].value_counts().to_dict().items()}
        high_priority_leads = int(priority_distribution.get("HIGH", 0))
        potential_revenue = float(scored.loc[scored["priority"] == "HIGH", "lead_value"].sum())
        contact_dates = pd.to_datetime(frame["last_contact_date"], errors="coerce")
        outdated_records = int((contact_dates < pd.Timestamp.today() - pd.Timedelta(days=90)).fillna(False).sum())

    metric = _preferred_numeric(frame)
    metric_sum = float(pd.to_numeric(frame[metric], errors="coerce").sum()) if metric else None
    category_column = categorical_columns[0] if categorical_columns else None
    category_distribution = []
    if category_column:
        top_categories = frame[category_column].dropna().astype(str).value_counts().head(5)
        category_distribution = [{"name": str(name), "value": int(value)} for name, value in top_categories.items()]
    date_column = date_columns[0] if date_columns else None
    trends: list[dict[str, Any]] = []
    if metric and date_column:
        dated = frame[[date_column, metric]].dropna().copy()
        if not dated.empty:
            dated["month"] = pd.to_datetime(dated[date_column]).dt.to_period("M").astype(str)
            grouped = dated.groupby("month")[metric].sum().tail(12)
            trends = [{"month": str(month), "value": float(value)} for month, value in grouped.items()]

    conflicting = 0
    if "lead_id" in frame.columns:
        values = frame[frame["lead_id"].notna()].groupby("lead_id")[columns].nunique(dropna=False)
        conflicting = int((values > 1).any(axis=1).sum())
    quality = round(max(0, 100 * (1 - (missing + duplicate_rows) / max(1, rows * max(1, len(columns))))), 1)
    warnings = [f"{count} missing values in {column}" for column, count in missing_by_column.items() if count]
    if duplicate_rows:
        warnings.append(f"{duplicate_rows} duplicate records detected.")
    return {
        "dataset_name": metadata.get("filename", "Sales Leads Dataset" if lead_mode else "Uploaded dataset"),
        "filename": metadata.get("filename", "demo_sales_data.csv" if lead_mode else "uploaded_dataset"),
        "file_type": metadata.get("file_type", "csv" if lead_mode else "unknown"),
        "source": metadata.get("source", "demo" if lead_mode else "upload"),
        "dataset_id": metadata.get("dataset_id", ""),
        "sheet_names": metadata.get("sheet_names", []),
        "selected_sheet": metadata.get("selected_sheet"),
        "rows": int(rows), "columns": len(columns), "data_quality": quality,
        "duplicates": duplicate_rows, "duplicate_rows": duplicate_rows,
        "conflicting_records": conflicting, "missing_values": missing,
        "missing_percentage": round(missing / max(1, rows * max(1, len(columns))) * 100, 2),
        "missing_by_column": {str(key): int(value) for key, value in missing_by_column.items()},
        "outdated_records": outdated_records, "columns_list": columns,
        "column_profiles": profiles, "numeric_columns": numeric_columns,
        "numeric_correlations": numeric_correlations,
        "categorical_columns": categorical_columns, "date_columns": date_columns,
        "preprocessing": metadata.get("preprocessing", frame.attrs.get("preprocessing", [])),
        "quality_warnings": warnings, "supports_lead_decisions": lead_mode,
        "priority_distribution": priority_distribution, "high_priority_leads": high_priority_leads,
        "potential_revenue": potential_revenue, "revenue_opportunity": trends,
        "primary_metric": metric, "primary_metric_sum": metric_sum,
        "category_distribution": category_distribution,
        "suggested_questions": _suggestions(frame, numeric_columns, categorical_columns, date_columns),
    }