from __future__ import annotations

import re
from typing import Iterable

from src.models import RecipeStep


_RANGE_MINUTES = re.compile(r"(\d+)\s*[~～-]\s*(\d+)\s*분")
_MINUTES = re.compile(r"(?<!\d)(\d+)\s*분")
_RANGE_HOURS = re.compile(r"(\d+)\s*[~～-]\s*(\d+)\s*시간")
_HOURS = re.compile(r"(?<!\d)(\d+)\s*시간")


def estimate_minutes(steps: Iterable[RecipeStep]) -> tuple[int, int] | None:
    """조리법 문장에 명시된 시간을 합산한 보수적인 추정값을 반환한다."""
    low_total = 0
    high_total = 0
    found = False

    for step in steps:
        text = step.text
        step_low = 0
        step_high = 0

        for low, high in _RANGE_HOURS.findall(text):
            step_low += int(low) * 60
            step_high += int(high) * 60
            found = True
        text = _RANGE_HOURS.sub("", text)

        for hour in _HOURS.findall(text):
            step_low += int(hour) * 60
            step_high += int(hour) * 60
            found = True
        text = _HOURS.sub("", text)

        for low, high in _RANGE_MINUTES.findall(text):
            step_low += int(low)
            step_high += int(high)
            found = True
        text = _RANGE_MINUTES.sub("", text)

        for minute in _MINUTES.findall(text):
            step_low += int(minute)
            step_high += int(minute)
            found = True

        low_total += step_low
        high_total += step_high

    if not found:
        return None
    return low_total, max(low_total, high_total)


def format_estimated_time(value: tuple[int, int] | None) -> str:
    if value is None:
        return "시간 정보 없음"
    low, high = value
    if low == high:
        return f"약 {low}분"
    return f"약 {low}~{high}분"

