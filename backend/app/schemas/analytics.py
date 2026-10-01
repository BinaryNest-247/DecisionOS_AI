from typing import Any, Literal

from pydantic import BaseModel, Field


class AnalysisFilter(BaseModel):
    column: str
    operator: Literal["eq", "ne", "gt", "gte", "lt", "lte", "contains"]
    value: Any


class AnalysisPlan(BaseModel):
    intent: str = "aggregation"
    metric: str | None = None
    group_by: str | None = None
    operation: Literal[
        "count",
        "sum",
        "average",
        "min",
        "max",
        "median",
        "std",
        "correlation",
        "distribution",
        "unique_count",
        "missing",
        "duplicates",
        "filter",
    ]
    sort: Literal["ascending", "descending", "none"] = "none"
    limit: int = Field(default=20, ge=1, le=100)
    date_column: str | None = None
    filters: list[AnalysisFilter] = Field(default_factory=list)