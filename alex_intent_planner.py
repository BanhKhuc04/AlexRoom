from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from typing import Any

from alex_intelligence import (
    IntelligenceDecision,
    IntelligenceRoute,
    route_intelligence,
)


_CLEAR_LLM_INTENT = re.compile(
    r"\b(giai thich|phan tich|ke cho toi|ke chuyen|tu van|huong dan)\b"
)
_MISSING_TARGET = re.compile(
    r"\b(?:bat|tat|mo|dong|kiem tra|lam|thuc hien)\s+"
    r"(?:no|cai do|cai kia|thiet bi do|viec do)\b"
)
_UNRESOLVED_REFERENCE = re.compile(
    r"\b(?:cai do|cai kia|viec do|thiet bi do)\b"
)
_DEVICE_ID = re.compile(r"(?<![a-z0-9_-])esp\d+(?![a-z0-9_-])")
_ACTION_WORD = re.compile(
    r"\b(?:bat|tat|mo|dong|kiem tra|doi|chuyen|chay|lam|thuc hien)\b"
)


class IntentCertainty(str, Enum):
    EXACT = "exact"
    HEURISTIC = "heuristic"
    UNKNOWN = "unknown"


class ClarificationReason(str, Enum):
    EMPTY_INPUT = "empty_input"
    MISSING_TARGET = "missing_target"
    AMBIGUOUS_DEVICE_REFERENCE = "ambiguous_device_reference"
    INSUFFICIENT_CONTEXT = "insufficient_context"


@dataclass(frozen=True, slots=True)
class IntentStep:
    index: int
    original_text: str
    normalized_text: str
    decision: IntelligenceDecision
    certainty: IntentCertainty
    requires_clarification: bool
    clarification_reason: ClarificationReason | None

    def to_compact_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "original_text": self.original_text,
            "normalized_text": self.normalized_text,
            "decision": {
                "route": self.decision.route.value,
                "matched": self.decision.matched,
                "reason": self.decision.reason,
                "allowed_tool_names": list(
                    self.decision.allowed_tool_names
                ),
                "metadata": dict(self.decision.metadata),
            },
            "certainty": self.certainty.value,
            "requires_clarification": self.requires_clarification,
            "clarification_reason": (
                self.clarification_reason.value
                if self.clarification_reason is not None
                else None
            ),
        }


@dataclass(frozen=True, slots=True)
class IntelligencePlan:
    original_text: str
    steps: tuple[IntentStep, ...]
    multi_intent: bool
    requires_clarification: bool
    clarification_prompt: str | None

    def to_compact_dict(self) -> dict[str, Any]:
        return {
            "original_text": self.original_text,
            "steps": [step.to_compact_dict() for step in self.steps],
            "multi_intent": self.multi_intent,
            "requires_clarification": self.requires_clarification,
            "clarification_prompt": self.clarification_prompt,
        }


@dataclass(frozen=True, slots=True)
class _Separator:
    start: int
    end: int


def plan_intelligence(user_text: str) -> IntelligencePlan:
    """Build an ordered plan; this function never executes a decision."""

    original = user_text if isinstance(user_text, str) else ""
    if not original.strip():
        return IntelligencePlan(
            original_text=original,
            steps=(),
            multi_intent=False,
            requires_clarification=True,
            clarification_prompt="Bạn muốn ALEX làm gì?",
        )

    segments = _split_conservatively(original)
    steps = tuple(
        _build_step(index, segment)
        for index, segment in enumerate(segments)
    )
    clarification_step = next(
        (step for step in steps if step.requires_clarification),
        None,
    )
    return IntelligencePlan(
        original_text=original,
        steps=steps,
        multi_intent=len(steps) > 1,
        requires_clarification=clarification_step is not None,
        clarification_prompt=(
            _clarification_prompt(clarification_step)
            if clarification_step is not None
            else None
        ),
    )


def compact_intelligence_plan(plan: IntelligencePlan) -> dict[str, Any]:
    return plan.to_compact_dict()


def _build_step(index: int, text: str) -> IntentStep:
    segment = _clean_segment(text)
    normalized = _normalize_text(segment)
    decision = route_intelligence(segment)
    clarification_reason = _clarification_reason(
        normalized,
        decision,
    )
    return IntentStep(
        index=index,
        original_text=segment,
        normalized_text=normalized,
        decision=decision,
        certainty=_certainty(decision, normalized, clarification_reason),
        requires_clarification=clarification_reason is not None,
        clarification_reason=clarification_reason,
    )


def _split_conservatively(text: str) -> tuple[str, ...]:
    cleaned = _clean_segment(text)
    for separator in _separators(cleaned):
        left = _clean_segment(cleaned[:separator.start])
        right = _clean_segment(cleaned[separator.end:])
        if not left or not right:
            continue
        if not (
            _is_complete_intent(left)
            and _is_complete_intent(right)
        ):
            continue
        return (
            *_split_conservatively(left),
            *_split_conservatively(right),
        )
    return (cleaned,)


def _separators(text: str) -> tuple[_Separator, ...]:
    normalized = _normalize_text(text)
    separators: set[tuple[int, int]] = set()
    for pattern in (
        re.compile(r";"),
        re.compile(r","),
        re.compile(r"\bsau do\b"),
        re.compile(r"\broi\b"),
        re.compile(r"\bva\b"),
    ):
        separators.update(
            (match.start(), match.end())
            for match in pattern.finditer(normalized)
        )
    return tuple(
        _Separator(start, end)
        for start, end in sorted(separators)
    )


def _is_complete_intent(text: str) -> bool:
    normalized = _normalize_text(text)
    decision = route_intelligence(text)
    if _clarification_reason(normalized, decision) is not None:
        return False
    if decision.route is not IntelligenceRoute.LLM:
        return True
    if decision.matched:
        return True
    return _CLEAR_LLM_INTENT.search(normalized) is not None


def _certainty(
    decision: IntelligenceDecision,
    normalized: str,
    clarification_reason: ClarificationReason | None,
) -> IntentCertainty:
    if clarification_reason is not None:
        return IntentCertainty.UNKNOWN
    if decision.route is not IntelligenceRoute.LLM:
        return IntentCertainty.EXACT
    if decision.matched or _CLEAR_LLM_INTENT.search(normalized):
        return IntentCertainty.EXACT
    return IntentCertainty.HEURISTIC


def _clarification_reason(
    normalized: str,
    decision: IntelligenceDecision,
) -> ClarificationReason | None:
    if not normalized:
        return ClarificationReason.EMPTY_INPUT
    device_ids = tuple(_DEVICE_ID.findall(normalized))
    if (
        len(set(device_ids)) > 1
        and " hay " in f" {normalized} "
        and _ACTION_WORD.search(normalized) is None
    ):
        return ClarificationReason.AMBIGUOUS_DEVICE_REFERENCE
    if _MISSING_TARGET.search(normalized):
        return ClarificationReason.MISSING_TARGET
    if _UNRESOLVED_REFERENCE.search(normalized):
        return ClarificationReason.INSUFFICIENT_CONTEXT
    if (
        decision.route is IntelligenceRoute.LLM
        and not decision.matched
        and normalized in {"lam di", "lam viec do di", "cai nao"}
    ):
        return ClarificationReason.INSUFFICIENT_CONTEXT
    return None


def _clarification_prompt(step: IntentStep) -> str:
    normalized = step.normalized_text
    if (
        step.clarification_reason
        is ClarificationReason.AMBIGUOUS_DEVICE_REFERENCE
    ):
        return "Bạn muốn chọn thiết bị nào và thực hiện việc gì?"
    if re.search(r"\b(?:bat|mo)\b", normalized):
        return "Bạn muốn bật thiết bị nào?"
    if re.search(r"\btat\b", normalized):
        return "Bạn muốn tắt thiết bị nào?"
    if "kiem tra" in normalized:
        return "Bạn muốn kiểm tra gì?"
    return "Bạn muốn ALEX thực hiện việc gì?"


def _clean_segment(text: str) -> str:
    return " ".join(
        text.strip(" \t\r\n,;:.!?").split()
    )


def _normalize_text(text: str) -> str:
    lowered = text.strip().lower()
    lowered = lowered.replace("×", "x")
    lowered = lowered.replace("–", "-")
    lowered = lowered.replace("—", "-")
    decomposed = unicodedata.normalize(
        "NFD",
        lowered.replace("đ", "d"),
    )
    no_accents = "".join(
        character
        for character in decomposed
        if unicodedata.category(character) != "Mn"
    )
    return " ".join(no_accents.split())
