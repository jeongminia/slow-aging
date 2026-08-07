from __future__ import annotations

import re
from typing import Iterable


ALIASES: dict[str, tuple[str, ...]] = {
    "달걀": ("달걀", "계란", "egg"),
    "두부": ("두부", "순두부", "연두부", "tofu"),
    "시금치": ("시금치", "spinach"),
    "대파": ("대파", "쪽파", "실파", "파", "green onion", "scallion"),
    "양파": ("양파", "적양파", "onion"),
    "마늘": ("마늘", "garlic"),
    "당근": ("당근", "carrot"),
    "애호박": ("애호박", "주키니", "호박", "zucchini"),
    "버섯": (
        "버섯",
        "표고버섯",
        "새송이버섯",
        "느타리버섯",
        "팽이버섯",
        "양송이버섯",
        "mushroom",
    ),
    "현미": ("현미", "현미밥", "brown rice"),
    "잡곡": ("잡곡", "잡곡밥", "흑미", "오곡", "mixed grain"),
    "쌀": ("쌀", "밥", "rice"),
    "닭가슴살": ("닭가슴살", "닭 가슴살", "가슴살", "chicken breast"),
    "닭고기": ("닭고기", "닭", "chicken"),
    "돼지고기": ("돼지고기", "돈육", "pork"),
    "소고기": ("소고기", "쇠고기", "우육", "beef"),
    "생선": ("생선", "흰살생선", "fish"),
    "연어": ("연어", "salmon"),
    "고등어": ("고등어", "mackerel"),
    "참치": ("참치", "tuna"),
    "콩나물": ("콩나물",),
    "숙주": ("숙주", "숙주나물"),
    "브로콜리": ("브로콜리", "broccoli"),
    "양배추": ("양배추", "cabbage"),
    "배추": ("배추", "알배추", "청경채", "bok choy"),
    "케일": ("케일", "kale"),
    "오이": ("오이", "cucumber"),
    "가지": ("가지", "eggplant"),
    "토마토": ("토마토", "방울토마토", "tomato"),
    "감자": ("감자", "potato"),
    "고구마": ("고구마", "sweet potato"),
    "콩": (
        "콩",
        "대두",
        "검은콩",
        "서리태",
        "강낭콩",
        "완두콩",
        "병아리콩",
        "렌틸콩",
        "bean",
        "lentil",
        "chickpea",
    ),
    "김치": ("김치", "kimchi"),
    "오징어": ("오징어", "squid"),
    "새우": ("새우", "shrimp", "prawn"),
    "조개": ("조개", "바지락", "홍합", "clam", "mussel"),
    "두유": ("두유", "soy milk"),
    "우유": ("우유", "milk"),
    "요거트": ("요거트", "요구르트", "yogurt"),
    "치즈": ("치즈", "cheese"),
    "귀리": ("귀리", "오트", "오트밀", "oat"),
    "보리": ("보리", "보리쌀", "barley"),
    "메밀": ("메밀", "buckwheat"),
}

PANTRY_STAPLES = {
    "물",
    "소금",
    "후추",
    "설탕",
    "식용유",
    "참기름",
    "들기름",
    "간장",
    "식초",
    "깨",
    "참깨",
}

WHOLE_GRAINS = ("현미", "잡곡", "흑미", "귀리", "보리", "메밀", "통밀")
LEGUMES = ("콩", "두부", "청국장", "된장", "렌틸", "병아리콩", "완두콩")
VEGETABLES = (
    "시금치",
    "브로콜리",
    "양배추",
    "배추",
    "케일",
    "오이",
    "가지",
    "토마토",
    "당근",
    "애호박",
    "호박",
    "양파",
    "버섯",
    "콩나물",
    "숙주",
    "나물",
    "파프리카",
    "피망",
)
ULTRA_PROCESSED = ("소시지", "햄", "베이컨", "라면", "스팸", "핫도그")


def compact(text: str) -> str:
    return re.sub(r"[^0-9a-zA-Z가-힣]", "", str(text or "").lower())


def canonicalize(name: str) -> str:
    normalized = compact(name)
    if not normalized:
        return ""
    for canonical, aliases in ALIASES.items():
        if any(compact(alias) == normalized for alias in aliases):
            return canonical
    return re.sub(r"\s+", " ", str(name).strip().lower())


def aliases_for(name: str) -> tuple[str, ...]:
    canonical = canonicalize(name)
    return ALIASES.get(canonical, (canonical,))


def contains_ingredient(text: str, ingredient: str) -> bool:
    haystack = compact(text)
    return any(compact(alias) in haystack for alias in aliases_for(ingredient) if alias)


def matched_ingredients(text: str, ingredients: Iterable[str]) -> list[str]:
    matched: list[str] = []
    for ingredient in ingredients:
        canonical = canonicalize(ingredient)
        if canonical and canonical not in matched and contains_ingredient(text, canonical):
            matched.append(canonical)
    return matched


def contains_any(text: str, ingredients: Iterable[str]) -> bool:
    return any(contains_ingredient(text, ingredient) for ingredient in ingredients)


def extract_known_ingredients(text: str) -> list[str]:
    found: list[str] = []
    for canonical, aliases in ALIASES.items():
        if any(compact(alias) in compact(text) for alias in aliases):
            found.append(canonical)
    return found


def extract_ingredient_names(text: str, limit: int = 12) -> list[str]:
    """표시용 추가 재료 후보를 추출한다. 정확한 영양 파싱 용도로 쓰지 않는다."""
    names = extract_known_ingredients(text)
    if len(names) >= limit:
        return names[:limit]

    cleaned = re.sub(r"\([^)]*\)", " ", text)
    chunks = re.split(r"[,;/\n]", cleaned)
    unit_pattern = re.compile(
        r"([가-힣A-Za-z]+(?:\s+[가-힣A-Za-z]+){0,2})\s*"
        r"(?:\d+(?:\.\d+)?|약간)\s*(?:g|kg|ml|l|개|장|쪽|알|컵|큰술|작은술|약간)?",
        re.IGNORECASE,
    )
    for chunk in chunks:
        match = unit_pattern.search(chunk.strip())
        if not match:
            continue
        candidate = match.group(1).strip().split()[-1]
        canonical = canonicalize(candidate)
        if (
            canonical
            and canonical not in PANTRY_STAPLES
            and canonical not in names
            and len(canonical) >= 2
        ):
            names.append(canonical)
        if len(names) >= limit:
            break
    return names


def health_markers(text: str) -> dict[str, float]:
    normalized = compact(text)
    vegetable_count = sum(compact(term) in normalized for term in VEGETABLES)
    return {
        "whole_grain": float(any(compact(term) in normalized for term in WHOLE_GRAINS)),
        "legume": float(any(compact(term) in normalized for term in LEGUMES)),
        "vegetable": min(1.0, vegetable_count / 3),
        "processed_penalty": float(
            any(compact(term) in normalized for term in ULTRA_PROCESSED)
        ),
    }

