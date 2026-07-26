from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Literal, Mapping


RouterToolName = Literal["system_status", "list_devices"]

_CALCULATOR_BINARY_PATTERN = re.compile(
    r"^\d+(?:[.,]\d+)?\s*(?:\+|-|x|\*|/)\s*\d+(?:[.,]\d+)?$"
)
_CALCULATOR_PERCENT_PATTERN = re.compile(
    r"^\d+(?:[.,]\d+)?\s*%\s*cua\s*\d+(?:[.,]\d+)?$"
)
_RELAY_PATTERN = re.compile(r"\brelay(?:[_\s-]?[1-4])?\b")
_ACTION_VERB_PATTERN = re.compile(
    r"\b(bat|tat|mo|dong|chay|khoi dong|kich hoat|doi|chuyen(?:\s+sang)?)\b"
)
_ROOM_MODE_PATTERN = re.compile(
    r"\b(room mode|che do (hoc|ngu|sleep|study|away|home))\b"
)

_SYSTEM_STATUS_PHRASES = (
    "trang thai alex",
    "trang thai he thong alex",
    "cho toi xem trang thai he thong alex",
    "alex co on khong",
    "kiem tra tinh trang he thong",
    "kiem tra he thong alex",
)
_DEVICE_STATUS_PHRASES = (
    "esp01 online khong",
    "co nhung thiet bi nao",
    "liet ke thiet bi",
    "thiet bi nao dang online",
    "trang thai thiet bi",
    "danh sach thiet bi",
)
_TIME_PHRASES = (
    "may gio roi",
    "bay gio la may gio",
    "bay gio may gio",
    "hom nay ngay bao nhieu",
    "hom nay la thu may",
    "hom nay thu may",
)
_WEATHER_PHRASES = (
    "thoi tiet",
    "mai co mua khong",
    "hom nay co mua khong",
    "nhiet do ngoai troi",
)


class IntelligenceRoute(str, Enum):
    SYSTEM = "system"
    CALCULATOR = "calculator"
    TIME = "time"
    WEATHER = "weather"
    LLM = "llm"


@dataclass(frozen=True, slots=True)
class IntelligenceDecision:
    route: IntelligenceRoute
    matched: bool
    reason: str
    allowed_tool_names: tuple[RouterToolName, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "allowed_tool_names", tuple(self.allowed_tool_names))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


def route_intelligence(user_text: str) -> IntelligenceDecision:
    normalized = _normalize_text(user_text)

    if not isinstance(user_text, str):
        return _llm_fallback("invalid_input_type")
    if not normalized:
        return _llm_fallback("empty_or_whitespace_input")
    if _is_guarded_action_command(normalized):
        return IntelligenceDecision(
            route=IntelligenceRoute.LLM,
            matched=True,
            reason="guarded_mutation_command_falls_back",
        )
    if _is_calculator_expression(normalized):
        return IntelligenceDecision(
            route=IntelligenceRoute.CALCULATOR,
            matched=True,
            reason="deterministic_calculator_expression",
        )
    if _is_device_status_query(normalized):
        return IntelligenceDecision(
            route=IntelligenceRoute.SYSTEM,
            matched=True,
            reason="device_registry_status_query",
            allowed_tool_names=("list_devices",),
        )
    if _is_system_status_query(normalized):
        return IntelligenceDecision(
            route=IntelligenceRoute.SYSTEM,
            matched=True,
            reason="overall_system_status_query",
            allowed_tool_names=("system_status",),
        )
    if _is_time_query(normalized):
        return IntelligenceDecision(
            route=IntelligenceRoute.TIME,
            matched=True,
            reason="deterministic_time_query",
        )
    if _is_weather_query(normalized):
        return IntelligenceDecision(
            route=IntelligenceRoute.WEATHER,
            matched=True,
            reason="deterministic_weather_query",
        )
    return _llm_fallback("no_deterministic_route_matched")


def _llm_fallback(reason: str) -> IntelligenceDecision:
    return IntelligenceDecision(
        route=IntelligenceRoute.LLM,
        matched=False,
        reason=reason,
    )


def _normalize_text(user_text: object) -> str:
    if not isinstance(user_text, str):
        return ""
    lowered = user_text.strip().lower()
    lowered = lowered.replace("×", "x")
    lowered = lowered.replace("–", "-")
    lowered = lowered.replace("—", "-")
    no_accents = _strip_accents(lowered)
    return " ".join(no_accents.split())


def _strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value.replace("đ", "d"))
    return "".join(char for char in normalized if unicodedata.category(char) != "Mn")


def _contains_any(text: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in text for phrase in phrases)


def _is_calculator_expression(text: str) -> bool:
    return bool(
        _CALCULATOR_BINARY_PATTERN.fullmatch(text)
        or _CALCULATOR_PERCENT_PATTERN.fullmatch(text)
    )


def _is_system_status_query(text: str) -> bool:
    return _contains_any(text, _SYSTEM_STATUS_PHRASES)


def _is_device_status_query(text: str) -> bool:
    return _contains_any(text, _DEVICE_STATUS_PHRASES)


def _is_time_query(text: str) -> bool:
    return _contains_any(text, _TIME_PHRASES)


def _is_weather_query(text: str) -> bool:
    if _contains_any(text, _WEATHER_PHRASES):
        return True
    return "mua" in text and ("hom nay" in text or "mai" in text)


def _is_guarded_action_command(text: str) -> bool:
    if _RELAY_PATTERN.search(text):
        return True

    if _ACTION_VERB_PATTERN.search(text) and (
        "den test" in text
        or "test led" in text
        or _ROOM_MODE_PATTERN.search(text) is not None
        or "mission" in text
        or "automation" in text
    ):
        return True

    return False
