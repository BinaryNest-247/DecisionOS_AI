from __future__ import annotations

import json
from typing import Any

from app.services.llm_service import LLMServiceError, llm_service

class AIService:
    """Compatibility facade for the optional provider-backed language layer."""

    def extract_intent(self, question: str) -> str:
        fallback = self._deterministic_intent(question)
        allowed = {"lead_prioritization", "revenue_opportunity", "customer_inactivity", "historical_performance", "ambiguous"}
        try:
            content = llm_service.generate(
                "Classify the business question. Return only JSON with one intent from: lead_prioritization, revenue_opportunity, customer_inactivity, historical_performance, ambiguous. Do not answer or add business facts.",
                question,
                json_schema={"type": "object", "properties": {"intent": {"type": "string", "enum": sorted(allowed)}}, "required": ["intent"]},
            )
            intent = json.loads(content).get("intent")
            return intent if intent in allowed else fallback
        except (LLMServiceError, ValueError, TypeError):
            return fallback

    @staticmethod
    def _deterministic_intent(question: str) -> str:
        normalized = question.strip().lower()
        if "performance" in normalized or "what changed" in normalized:
            return "historical_performance"
        if "inactive" in normalized or "at risk" in normalized or "re-engage" in normalized or "reengage" in normalized:
            return "customer_inactivity"
        if "revenue" in normalized or "opportun" in normalized:
            return "revenue_opportunity"
        if len(normalized) >= 8 and any(word in normalized for word in ("lead", "customer", "sales", "priorit", "contact", "account")):
            return "lead_prioritization"
        return "ambiguous"

    def explain(self, question: str, evidence: list[dict[str, Any]]) -> str:
        if not evidence:
            return self._fallback(question)
        inactivity_query = any(
            phrase in question.casefold()
            for phrase in ("inactive", "at risk", "re-engage", "reengage")
        )
        system_instruction = "Explain the decision in under 90 words using only the supplied evidence. Do not add unsupported facts or change values."
        if inactivity_query:
            system_instruction += " This is a customer-inactivity recovery ranking: longer gaps since last contact increase the inactivity score, and inactive status is prioritized over nurture. Describe this as inactivity duration, not recent activity."
        try:
            return llm_service.generate(
                system_instruction,
                json.dumps({"question": question, "evidence": evidence[:30]}, allow_nan=False),
            )
        except (LLMServiceError, ValueError, TypeError):
            return self._fallback(question)

    def plan_analytics(self, question: str, columns: list[str]) -> dict[str, Any] | None:
        try:
            return llm_service.analyze_question(question, columns)
        except (LLMServiceError, ValueError, TypeError):
            return None

    def explain_analytics(self, question: str, answer: str, result: list[dict[str, Any]], evidence: list[dict[str, Any]]) -> str:
        try:
            return llm_service.explain_result(question, answer, result, evidence)
        except (LLMServiceError, ValueError, TypeError):
            return answer

    @staticmethod
    def _fallback(question: str = "") -> str:
        if any(
            phrase in question.casefold()
            for phrase in ("inactive", "at risk", "re-engage", "reengage")
        ):
            return "Ranked by inactivity duration, lead value, engagement, purchase history, and lead status. Longer gaps since last contact raise the inactivity score."
        return "Ranked using the available lead value, engagement, contact recency, purchase history, and status. Each score is traceable to the factors shown below."


ai_service = AIService()