from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

import numpy as np
import pandas as pd
from fastapi import HTTPException

from app.schemas.analytics import AnalysisPlan
from app.services.ai_service import ai_service
from app.services.dataset import _json_value

OPERATIONS = {"count", "sum", "average", "min", "max", "median", "std", "correlation", "distribution", "unique_count", "missing", "duplicates", "filter"}
STOP_WORDS = {"the", "a", "an", "of", "by", "for", "is", "are", "was", "were", "what", "which", "show", "me", "give", "tell", "find", "generated", "generate", "has", "have", "had", "with", "from", "there", "any", "all", "how", "many", "much", "highest", "lowest", "most", "least", "total", "average", "mean", "sum", "compare", "between", "and", "top", "above", "over", "under", "than", "more", "less", "records", "data", "dataset", "please", "our", "their", "per", "each"}
ALIASES = {
    "revenue": {"revenue", "sales", "sale", "amount", "purchase amount", "transaction amount", "total sales", "sales amount", "income"},
    "quantity": {"quantity", "qty", "units", "items sold", "volume"},
    "price": {"price", "cost", "value", "spend", "spent", "profit", "discount"},
    "customer": {"customer", "client", "patient", "account", "buyer"},
    "product": {"product", "item", "sku"},
    "region": {"region", "area", "territory", "state", "city", "location"},
    "salesperson": {"salesperson", "sales person", "sales rep", "representative", "rep", "employee"},
    "category": {"category", "type", "segment", "department"},
}


def _normal(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text).lower()).strip()


def _column_for(frame: pd.DataFrame, text: str, candidates: list[str] | None = None) -> str | None:
    candidates = candidates or list(frame.columns)
    normalized_text = _normal(text)
    exact = [column for column in candidates if _normal(column) == normalized_text]
    if exact:
        return exact[0]
    question_tokens = set(normalized_text.split()) - STOP_WORDS
    scored: list[tuple[float, str]] = []
    for column in candidates:
        normalized_column = _normal(column)
        column_tokens = set(normalized_column.split())
        overlap = len(question_tokens & column_tokens) / max(1, len(column_tokens))
        ratio = SequenceMatcher(None, normalized_column, normalized_text).ratio()
        score = max(overlap, ratio * 0.7)
        for alias_group in ALIASES.values():
            if any(alias == normalized_column or alias in normalized_column for alias in alias_group):
                if any(alias in normalized_text for alias in alias_group):
                    score = max(score, 0.95)
        if re.search(rf"\b{re.escape(normalized_column)}\b", normalized_text):
            score = 1.0
        scored.append((score, column))
    if not scored:
        return None
    score, column = max(scored)
    return column if score >= 0.38 else None


def _fallback_plan(frame: pd.DataFrame, question: str) -> dict[str, Any]:
    normalized = _normal(question)
    columns = list(frame.columns)
    numeric = [column for column in columns if pd.api.types.is_numeric_dtype(frame[column])]
    dates = [column for column in columns if pd.api.types.is_datetime64_any_dtype(frame[column])]
    categorical = [column for column in columns if column not in numeric and column not in dates]

    if "correlation" in normalized or "correlated" in normalized:
        mentioned = [column for column in numeric if re.search(rf"\b{re.escape(_normal(column))}\b", normalized)]
        return {"intent": "correlation", "metric": mentioned[0] if mentioned else None, "group_by": mentioned[1] if len(mentioned) > 1 else None, "operation": "correlation", "sort": "none", "limit": 20}

    if "missing" in normalized or "null" in normalized or "blank" in normalized:
        column = _column_for(frame, normalized, columns)
        return {"intent": "missing_analysis", "metric": column, "group_by": None, "operation": "missing", "sort": "none", "limit": 20}
    if "duplicate" in normalized or "repeated record" in normalized:
        return {"intent": "duplicate_analysis", "metric": None, "group_by": None, "operation": "duplicates", "sort": "none", "limit": 20}

    mentioned_numeric = _column_for(frame, normalized, numeric)
    metric = mentioned_numeric
    if metric is None and numeric:
        metric = next((column for column in numeric if any(term in _normal(column) for term in ("revenue", "sales", "amount", "quantity", "price", "cost", "value", "profit"))), None)
    if metric is None and numeric and any(term in normalized for term in ("average", "mean", "median", "sum", "total", "highest", "lowest", "amount", "revenue", "sales", "spent", "spend", "quantity", "price", "cost")):
        metric = numeric[0]

    group_by = None
    for column in categorical:
        value = _normal(column)
        if value and (re.search(rf"\bby\s+{re.escape(value)}\b", normalized) or re.search(rf"\b{re.escape(value)}\b", normalized)):
            group_by = column
            break
    if group_by is None:
        for semantic, aliases in ALIASES.items():
            if any(alias in normalized for alias in aliases):
                group_by = next((column for column in categorical if any(alias in _normal(column) for alias in aliases)), None)
                if group_by:
                    break
    date_trend = bool(dates and any(term in normalized for term in ("month", "monthly", "trend", "over time", "daily", "yearly")))
    date_column = dates[0] if dates else None
    operation = "count"
    if "unique" in normalized or "distinct" in normalized:
        operation = "unique_count"
    elif "distribution" in normalized or "histogram" in normalized:
        operation = "distribution"
    elif "standard deviation" in normalized or re.search(r"\bstd\b", normalized):
        operation = "std"
    elif any(term in normalized for term in ("average", "avg", "mean")):
        operation = "average"
    elif "median" in normalized:
        operation = "median"
    elif "minimum" in normalized or "min value" in normalized or "min of" in normalized or "lowest value" in normalized:
        operation = "min"
    elif "maximum" in normalized or "max value" in normalized or "max of" in normalized or "highest value" in normalized:
        operation = "max"
    elif metric and any(term in normalized for term in ("sum", "total", "revenue", "sales", "amount", "spent", "spend", "quantity", "profit", "price", "cost")):
        operation = "sum"
    elif group_by or date_trend:
        operation = "sum" if metric else "count"
    elif any(term in normalized for term in ("how many", "count", "number of")):
        operation = "count"

    sort = "descending" if any(term in normalized for term in ("highest", "top", "most", "largest", "best")) else "ascending" if any(term in normalized for term in ("lowest", "bottom", "least", "smallest")) else "none"
    limit_match = re.search(r"\btop\s+(\d+)\b", normalized)
    limit = min(100, int(limit_match.group(1))) if limit_match else 10 if sort != "none" else 20
    if date_trend:
        group_by = date_column
    return {"intent": "date_trend" if date_trend else "aggregation", "metric": metric, "group_by": group_by, "operation": operation, "sort": sort, "limit": limit}


def _safe_plan(frame: pd.DataFrame, question: str) -> dict[str, Any]:
    fallback = {**_fallback_plan(frame, question), "filters": []}
    proposed = ai_service.plan_analytics(question, [str(column) for column in frame.columns])
    if not proposed:
        return fallback
    try:
        proposed = AnalysisPlan.model_validate(proposed).model_dump()
    except Exception:
        return fallback
    valid_columns = {str(column): column for column in frame.columns}
    metric = proposed.get("metric")
    group_by = proposed.get("group_by")
    operation = proposed.get("operation")
    filters = []
    for item in proposed.get("filters", []):
        column = valid_columns.get(item["column"])
        if column is None:
            return fallback
        filters.append({**item, "column": column})
    return {
        **fallback,
        "intent": str(proposed.get("intent") or fallback["intent"]),
        "metric": valid_columns.get(metric, fallback["metric"]) if metric else fallback["metric"],
        "group_by": valid_columns.get(group_by, fallback["group_by"]) if group_by else fallback["group_by"],
        "operation": operation if operation in OPERATIONS else fallback["operation"],
        "sort": proposed.get("sort") if proposed.get("sort") in {"ascending", "descending", "none"} else fallback["sort"],
        "limit": max(1, min(100, int(proposed.get("limit", fallback["limit"])))) if str(proposed.get("limit", fallback["limit"])).isdigit() else fallback["limit"],
        "filters": filters,
    }


def _records(frame: pd.DataFrame, limit: int = 30) -> list[dict[str, Any]]:
    return [{str(column): _json_value(value) for column, value in row.items()} for row in frame.head(limit).to_dict(orient="records")]


def _apply_plan_filters(frame: pd.DataFrame, filters: list[dict[str, Any]]) -> pd.DataFrame:
    filtered = frame
    for condition in filters:
        column = condition["column"]
        operator = condition["operator"]
        expected = condition["value"]
        values = filtered[column]
        if operator == "contains":
            mask = values.astype("string").str.contains(str(expected), case=False, na=False, regex=False)
        elif pd.api.types.is_datetime64_any_dtype(values):
            target = pd.to_datetime(expected, errors="coerce")
            if pd.isna(target):
                raise HTTPException(422, f"The filter value for '{column}' is not a valid date.")
            comparable = pd.to_datetime(values, errors="coerce")
            mask = _compare(comparable, operator, target)
        elif pd.api.types.is_numeric_dtype(values):
            target = pd.to_numeric(pd.Series([expected]), errors="coerce").iloc[0]
            if pd.isna(target):
                raise HTTPException(422, f"The filter value for '{column}' must be numeric.")
            comparable = pd.to_numeric(values, errors="coerce")
            mask = _compare(comparable, operator, target)
        elif operator in {"eq", "ne"}:
            comparable = values.astype("string").str.casefold()
            target = str(expected).casefold()
            mask = comparable.eq(target) if operator == "eq" else comparable.ne(target)
        else:
            raise HTTPException(422, f"The '{operator}' filter requires a numeric or date column.")
        filtered = filtered[mask.fillna(False)]
    return filtered


def _compare(values: pd.Series, operator: str, target: Any) -> pd.Series:
    comparisons = {
        "eq": values.eq,
        "ne": values.ne,
        "gt": values.gt,
        "gte": values.ge,
        "lt": values.lt,
        "lte": values.le,
    }
    return comparisons[operator](target)


def _format(value: Any) -> str:
    if isinstance(value, (int, float, np.number)):
        return f"{value:,.2f}".rstrip("0").rstrip(".")
    return str(value)


def _answer(question: str, plan: dict[str, Any], result: list[dict[str, Any]], rows: int, total: int) -> str:
    operation = plan["operation"]
    metric = plan.get("metric")
    group = plan.get("group_by")
    if operation == "missing":
        return f"The active dataset contains {rows:,} missing values across the analyzed columns."
    if operation == "duplicates":
        return f"The active dataset contains {rows:,} duplicate records."
    if operation == "filter":
        return f"Found {rows:,} matching records in the active dataset."
    if operation == "correlation" and result:
        item = result[0]
        return f"The correlation between {item['column_a']} and {item['column_b']} is {_format(item['correlation'])} across {item['paired_rows']:,} complete rows."
    if not result:
        return "No matching business records were found in the active dataset."
    if group and plan.get("sort") != "none" and metric and operation in {"sum", "average", "min", "max", "median", "count"}:
        top = result[0]
        value = next((value for key, value in top.items() if key != group), None)
        direction = "highest" if plan["sort"] == "descending" else "lowest"
        measure = f"total {metric}" if operation == "sum" else metric
        return f"{top.get(group)} has the {direction} {measure} ({_format(value)})."
    if group and plan.get("sort") != "none" and operation == "count":
        top = result[0]
        return f"{top.get(group)} has the most records ({_format(top.get('count', 0))})."
    if group:
        return f"Analyzed {metric or 'record count'} by {group} across {rows:,} rows."
    if operation == "count":
        return f"The active dataset contains {rows:,} records."
    value = result[0].get("value") if result else None
    return f"The {operation} of {metric or 'the selected values'} is {_format(value)} across {rows:,} rows."


def analyze_question(frame: pd.DataFrame, question: str, previous: dict[str, Any] | None = None) -> dict[str, Any]:
    if frame.empty:
        raise HTTPException(422, "The active dataset contains no usable rows.")
    normalized = _normal(question)
    if previous and any(term in normalized for term in ("second highest", "second largest", "second one", "what about second")):
        prior_rows = previous.get("result", [])
        if len(prior_rows) < 2:
            raise HTTPException(422, "Insufficient evidence to identify a second result from the previous answer.")
        result = [prior_rows[1]]
        answer = f"The second-ranked result is {', '.join(f'{key}: {_format(value)}' for key, value in result[0].items())}."
        chart = previous.get("chart")
        if chart:
            chart = {**chart, "data": result}
        evidence = previous.get("evidence", [])
        group = previous.get("group_by")
        if group and group in frame.columns and group in result[0]:
            evidence = _records(frame[frame[group].astype(str) == str(result[0][group])])
        return {**previous, "question": question, "answer": answer, "result": result, "chart": chart, "evidence": evidence, "explanation": answer, "follow_up": True}

    follow_up_category = False
    plan = _safe_plan(frame, question)
    if previous and normalized.startswith(("what about ", "how about ", "and ")):
        prior_group = previous.get("group_by")
        prior_calculation = previous.get("calculation", {})
        if prior_group in frame.columns and prior_group != "period":
            matching_value = next((
                str(value)
                for value in frame[prior_group].dropna().astype(str).unique()
                if _normal(value) and re.search(rf"\b{re.escape(_normal(value))}\b", normalized)
            ), None)
            if matching_value:
                plan = {
                    "intent": previous.get("intent", "aggregation"),
                    "metric": prior_calculation.get("metric"),
                    "group_by": prior_group,
                    "operation": prior_calculation.get("operation", "sum"),
                    "sort": "none",
                    "limit": 20,
                }
                follow_up_category = True
    operation = plan["operation"]
    metric = plan.get("metric")
    group = plan.get("group_by")
    if operation in {"sum", "average", "min", "max", "median", "std"} and not metric and not group and not any(pd.api.types.is_numeric_dtype(frame[column]) for column in frame.columns):
        raise HTTPException(422, "No numeric column was found for this calculation. Available columns are: " + ", ".join(map(str, frame.columns)) + ".")
    operation_cues = ("how many", "count", "number of", "sum", "total", "average", "avg", "mean", "median", "standard deviation", "minimum", "maximum", "highest", "lowest", "top", "bottom", "unique", "distinct", "missing", "null", "blank", "duplicate", "above", "over", "below", "under", "greater than", "less than", "trend", "monthly", "daily", "compare", "percentage", "percent", "share", "correlation", "distribution", "histogram", "by ", "what about", "how about")
    direct_column_mention = any(_normal(column) and re.search(rf"\b{re.escape(_normal(column))}\b", normalized) for column in frame.columns)
    if not any(cue in normalized for cue in operation_cues) and not direct_column_mention:
        raise HTTPException(422, f"This question cannot be answered from the active dataset. Available columns are: {', '.join(map(str, frame.columns))}.")
    follow_up_trend = bool(previous and any(term in normalized for term in ("its monthly", "their monthly", "that monthly", "trend")))
    if follow_up_trend and not metric:
        metric = previous.get("calculation", {}).get("metric")
        if metric:
            plan["metric"] = metric
            plan["operation"] = operation = "sum"
    if any(term in normalized for term in ("trend", "monthly", "daily", "over time", "by month", "by year")) and not any(pd.api.types.is_datetime64_any_dtype(frame[column]) for column in frame.columns):
        raise HTTPException(422, "No date column was found for this time trend. Available columns are: " + ", ".join(map(str, frame.columns)) + ".")
    date_trend = plan["intent"] == "date_trend" and group is not None and group in frame.columns and pd.api.types.is_datetime64_any_dtype(frame[group])
    recognized_count = any(term in normalized for term in ("how many", "count", "number of", "record", "rows"))
    if operation not in {"missing", "duplicates"} and not metric and not group and not date_trend and not recognized_count:
        raise HTTPException(422, f"I couldn't identify a column for this question. Available columns are: {', '.join(map(str, frame.columns))}.")
    numeric_operations = {"sum", "average", "min", "max", "median", "std", "distribution", "correlation"}
    if metric and operation in numeric_operations and not pd.api.types.is_numeric_dtype(frame[metric]):
        raise HTTPException(422, f"No numeric column was found for this calculation. '{metric}' is not numeric.")
    if operation == "correlation" and (not group or group not in frame.columns or not pd.api.types.is_numeric_dtype(frame[group])):
        numeric_names = ", ".join(str(column) for column in frame.columns if pd.api.types.is_numeric_dtype(frame[column]))
        raise HTTPException(422, f"Name two numeric columns to calculate a correlation. Available numeric columns: {numeric_names}.")

    working = frame.copy()
    working["__source_row"] = range(1, len(working) + 1)
    evidence_source = working
    if operation == "missing":
        selected_columns = [plan["metric"]] if plan.get("metric") in frame.columns else list(frame.columns)
        missing_by_column = frame[selected_columns].isna().sum()
        result = [{"column": str(column), "missing_values": int(count)} for column, count in missing_by_column.items()]
        missing_total = int(missing_by_column.sum())
        answer = f"There are {missing_total:,} missing values in {', '.join(map(str, selected_columns))}." if missing_total else "No missing values were found in the active dataset."
        evidence = _records(frame[frame[selected_columns].isna().any(axis=1)].assign(source_row=lambda data: data.index + 1))
        rows_analyzed = len(frame)
        chart = None
    elif operation == "duplicates":
        duplicate_mask = frame.duplicated(keep=False)
        duplicate_frame = frame[duplicate_mask]
        result = _records(duplicate_frame)
        rows_analyzed = int(frame.duplicated().sum())
        answer = f"Found {rows_analyzed:,} duplicate rows in the active dataset."
        evidence = _records(duplicate_frame.assign(source_row=duplicate_frame.index + 1))
        chart = None
    elif operation == "correlation":
        paired = frame[[metric, group]].dropna()
        if len(paired) < 2:
            raise HTTPException(422, "At least two complete rows are required to calculate a correlation.")
        coefficient = paired[metric].corr(paired[group])
        if pd.isna(coefficient):
            raise HTTPException(422, "Correlation is undefined for constant or non-numeric columns.")
        result = [{"column_a": metric, "column_b": group, "correlation": float(coefficient), "paired_rows": int(len(paired))}]
        evidence = _records(frame.loc[paired.index, [metric, group]].assign(source_row=paired.index + 1))
        rows_analyzed = len(paired)
        answer = _answer(question, plan, result, rows_analyzed, len(frame))
        chart = None
    else:
        threshold = re.search(r"\b(above|over|greater than|more than|exceeding|below|under|less than)\s+₹?\s*([\d,]+(?:\.\d+)?)", normalized)
        categorical_filters: list[tuple[str, str]] = []
        working = _apply_plan_filters(working, plan.get("filters", []))
        if previous and any(term in normalized for term in ("its monthly", "their monthly", "that monthly", "trend")):
            prior = previous.get("result", [])
            prior_group = previous.get("group_by")
            if prior and prior_group and prior_group in frame.columns:
                leading = prior[0].get(prior_group)
                if leading is not None:
                    categorical_filters.append((prior_group, str(leading)))
                date_column = next((column for column in frame.columns if pd.api.types.is_datetime64_any_dtype(frame[column])), None)
                if date_column:
                    group = date_column
                    plan["intent"] = "date_trend"
                    date_trend = True
        for column in frame.columns:
            if column == metric or pd.api.types.is_numeric_dtype(frame[column]) or pd.api.types.is_datetime64_any_dtype(frame[column]):
                continue
            values = frame[column].dropna().astype(str).unique()
            if len(values) > 1000:
                continue
            for value in values:
                if _normal(value) and re.search(rf"\b{re.escape(_normal(value))}\b", normalized):
                    categorical_filters.append((str(column), value))
        grouped_filters: dict[str, set[str]] = {}
        for column, value in categorical_filters:
            grouped_filters.setdefault(column, set()).add(value.casefold())
        for column, values in grouped_filters.items():
            if column in working.columns:
                working = working[working[column].astype(str).str.casefold().isin(values)]
        if grouped_filters and any(term in normalized for term in ("how many", "count", "number of")):
            operation = "filter"
            group = None
            plan["operation"] = "filter"
            plan["group_by"] = None
        if threshold and metric:
            threshold_value = float(threshold.group(2).replace(",", ""))
            operator = threshold.group(1)
            if operator in {"above", "over", "greater than", "more than", "exceeding"}:
                working = working[pd.to_numeric(working[metric], errors="coerce") > threshold_value]
            else:
                working = working[pd.to_numeric(working[metric], errors="coerce") < threshold_value]
            operation = "filter"
            plan["operation"] = operation
        rows_analyzed = len(working)
        result_frame: pd.DataFrame
        chart = None
        if operation == "filter":
            result_frame = working.head(plan["limit"])
        elif operation == "unique_count":
            target = metric or group
            if not target:
                raise HTTPException(422, "I couldn't identify a column for the unique count. Name the column you want to count.")
            result_frame = pd.DataFrame([{"column": target, "unique_count": int(working[target].nunique(dropna=True))}])
            metric = target
        elif operation == "count" and not group:
            result_frame = pd.DataFrame([{"count": int(rows_analyzed)}])
        elif group:
            group_key = "__period" if date_trend else group
            if date_trend:
                valid = working[working[group].notna()].copy()
                period = "M" if "month" in normalized or "monthly" in normalized or "trend" in normalized else "D" if "daily" in normalized else "Y"
                valid[group_key] = pd.to_datetime(valid[group], errors="coerce").dt.to_period(period).astype(str)
                working = valid[valid[group_key] != "NaT"]
            if metric and operation in {"sum", "average", "min", "max", "median", "std"}:
                aggregation = {"average": "mean"}.get(operation, operation)
                result_frame = working.groupby(group_key, dropna=False)[metric].agg(aggregation).reset_index(name=metric)
            else:
                result_frame = working.groupby(group_key, dropna=False).size().reset_index(name="count")
            if date_trend:
                result_frame = result_frame.rename(columns={group_key: "period"})
                group = "period"
            if plan["sort"] in {"ascending", "descending"}:
                result_frame = result_frame.sort_values(result_frame.columns[-1], ascending=plan["sort"] == "ascending")
            result_frame = result_frame.head(plan["limit"])
            chart_type = "line" if date_trend else "pie" if "share" in normalized or "percentage" in normalized or "percent" in normalized else "bar"
            chart = {"type": chart_type, "x_key": str(result_frame.columns[0]), "y_key": str(result_frame.columns[-1]), "data": _records(result_frame)}
        elif operation == "distribution" and metric:
            numeric = pd.to_numeric(working[metric], errors="coerce").dropna()
            if numeric.empty:
                raise HTTPException(422, f"No numeric values are available in '{metric}' for a distribution.")
            bin_count = min(10, max(1, int(numeric.nunique())))
            bins = pd.cut(numeric, bins=bin_count, duplicates="drop", include_lowest=True)
            result_frame = bins.value_counts(sort=False).rename_axis("range").reset_index(name="count")
            result_frame["range"] = result_frame["range"].astype(str)
            result_frame = result_frame[result_frame["count"] > 0]
            chart = {"type": "bar", "x_key": "range", "y_key": "count", "data": _records(result_frame)}
        elif metric and operation in {"sum", "average", "min", "max", "median", "std"}:
            numeric = pd.to_numeric(working[metric], errors="coerce").dropna()
            aggregation = {"sum": numeric.sum, "average": numeric.mean, "min": numeric.min, "max": numeric.max, "median": numeric.median, "std": numeric.std}[operation]
            result_frame = pd.DataFrame([{"value": _json_value(aggregation())}])
        elif operation == "count":
            result_frame = pd.DataFrame([{"count": rows_analyzed}])
        else:
            raise HTTPException(422, "This question cannot be answered from the active dataset.")

        result = _records(result_frame)
        if chart and "percentage" in normalized or chart and "percent" in normalized or chart and "share" in normalized:
            chart_values = [item.get(chart["y_key"], 0) for item in result]
            total = sum(value or 0 for value in chart_values)
            for item in result:
                value = item.get(chart["y_key"], 0) or 0
                item["percentage"] = round(value / total * 100, 2) if total else 0
            chart["y_key"] = "percentage"
            chart["data"] = result

        if operation == "filter":
            evidence_source = working.drop(columns=["__source_row"], errors="ignore").copy()
            evidence_source["source_row"] = working["__source_row"].to_numpy()
        elif date_trend:
            evidence_source = working
        elif group and group in frame.columns:
            winning_values = [row.get(group) for row in result[:5]]
            evidence_source = frame[frame[group].astype(str).isin([str(value) for value in winning_values])]
        elif metric and metric in frame.columns:
            evidence_source = frame[frame[metric].notna()]
        else:
            evidence_source = frame
        evidence = _records(evidence_source.assign(source_row=evidence_source.index + 1))
        answer = _answer(question, plan, result, rows_analyzed, len(frame))

    explanation = ai_service.explain_analytics(question, answer, result, evidence)
    response = {
        "question": question,
        "answer": answer,
        "intent": plan.get("intent", "data_quality"),
        "columns_used": [column for column in [plan.get("metric"), plan.get("group_by")] if column],
        "operation": plan.get("operation"),
        "group_by": plan.get("group_by"),
        "sort": plan.get("sort"),
        "limit": plan.get("limit"),
        "calculation": {"metric": plan.get("metric"), "operation": plan.get("operation"), "group_by": plan.get("group_by"), "sort": plan.get("sort")},
        "result": result,
        "evidence": evidence,
        "chart": chart,
        "explanation": explanation,
        "rows_analyzed": int(rows_analyzed),
        "total_rows": int(len(frame)),
        "follow_up": follow_up_category,
    }
    return response