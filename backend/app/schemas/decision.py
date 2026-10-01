import math
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class AnalyzeRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    limit: int = Field(default=10, ge=1, le=100)


class SimulationRequest(BaseModel):
    decision_id: str
    weights: dict[str, float]

    @field_validator("weights")
    @classmethod
    def validate_weights(cls, weights: dict[str, float]) -> dict[str, float]:
        allowed = {"revenue", "engagement", "recency", "purchases", "status"}
        if not weights or set(weights) - allowed:
            raise ValueError("Provide weights for supported scoring factors only.")
        if any(not math.isfinite(value) or value < 0 for value in weights.values()):
            raise ValueError("Weights must be finite, non-negative numbers.")
        if sum(weights.values()) <= 0:
            raise ValueError("At least one scoring weight must be greater than zero.")
        return weights


class ApprovalRequest(BaseModel):
    decision_id: str
    action: str
    note: str = ""
    modified_recommendation: str | None = None


class AnalyticsRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class SheetRequest(BaseModel):
    sheet_name: str = Field(min_length=1, max_length=255)


class ProviderRequest(BaseModel):
    provider: Literal["gemini", "openrouter", "groq"]