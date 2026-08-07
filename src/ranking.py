from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from src.ingredients import (
    PANTRY_STAPLES,
    canonicalize,
    contains_any,
    extract_ingredient_names,
    health_markers,
    matched_ingredients,
)
from src.models import RankedRecipe, Recipe, ScoreBreakdown
from src.time_estimator import estimate_minutes, format_estimated_time


@dataclass(frozen=True)
class UserPreferences:
    ingredients: tuple[str, ...]
    priority_ingredients: tuple[str, ...] = ()
    excluded_ingredients: tuple[str, ...] = ()
    category: str = "상관없음"
    max_time_minutes: int | None = None
    high_protein: bool = True
    low_sodium: bool = True


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _nutrition_score(recipe: Recipe, prefs: UserPreferences) -> float:
    protein_target = 25.0 if prefs.high_protein else 18.0
    protein_score = (
        _clamp((recipe.protein_g or 0.0) / protein_target)
        if recipe.protein_g is not None
        else 0.35
    )

    sodium_limit = 600.0 if prefs.low_sodium else 900.0
    sodium_score = (
        _clamp(1.0 - max(0.0, (recipe.sodium_mg or 0.0) - 100.0) / sodium_limit)
        if recipe.sodium_mg is not None
        else 0.35
    )

    markers = health_markers(recipe.searchable_text)
    score = (
        0.30 * protein_score
        + 0.25 * sodium_score
        + 0.15 * markers["whole_grain"]
        + 0.15 * markers["legume"]
        + 0.15 * markers["vegetable"]
    )
    score -= 0.15 * markers["processed_penalty"]
    if "튀기" in recipe.method or "튀긴" in recipe.searchable_text:
        score -= 0.08
    return _clamp(score)


def _convenience_score(recipe: Recipe, max_time: int | None) -> tuple[float, str]:
    estimate = estimate_minutes(recipe.steps)
    time_label = format_estimated_time(estimate)

    if estimate and max_time:
        low, high = estimate
        if low > max_time:
            return 0.0, time_label
        time_score = 1.0 if high <= max_time else _clamp(max_time / high)
    elif estimate:
        _, high = estimate
        time_score = _clamp(1.15 - high / 120)
    else:
        time_score = 0.75 if len(recipe.steps) <= 5 else 0.55

    step_score = 1.0 if len(recipe.steps) <= 5 else 0.75 if len(recipe.steps) <= 8 else 0.45
    return 0.65 * time_score + 0.35 * step_score, time_label


def _make_reasons(
    recipe: Recipe,
    matched: list[str],
    priority_matched: list[str],
) -> list[str]:
    reasons: list[str] = []
    if matched:
        reasons.append(f"냉장고 재료 {len(matched)}개 활용")
    if priority_matched:
        reasons.append(f"우선 소진 재료 활용: {', '.join(priority_matched[:3])}")
    if recipe.protein_g is not None:
        reasons.append(f"단백질 {recipe.protein_g:g}g")
    if recipe.sodium_mg is not None:
        reasons.append(f"나트륨 {recipe.sodium_mg:g}mg")
    markers = health_markers(recipe.searchable_text)
    pattern_names = [
        label
        for label, key in (("통곡물", "whole_grain"), ("콩류", "legume"), ("채소", "vegetable"))
        if markers[key] > 0
    ]
    if pattern_names:
        reasons.append(" · ".join(pattern_names) + " 포함")
    return reasons[:4]


def rank_recipes(
    recipes: Iterable[Recipe],
    preferences: UserPreferences,
    limit: int = 30,
) -> list[RankedRecipe]:
    ingredients = tuple(
        dict.fromkeys(
            canonicalize(item)
            for item in preferences.ingredients
            if canonicalize(item)
        )
    )
    priority = tuple(
        dict.fromkeys(
            canonicalize(item)
            for item in preferences.priority_ingredients
            if canonicalize(item)
        )
    )
    excluded = tuple(
        dict.fromkeys(
            canonicalize(item)
            for item in preferences.excluded_ingredients
            if canonicalize(item)
        )
    )

    ranked: list[RankedRecipe] = []
    for recipe in recipes:
        text = recipe.searchable_text
        if excluded and contains_any(text, excluded):
            continue
        if preferences.category != "상관없음" and preferences.category not in recipe.category:
            continue

        matched = matched_ingredients(text, ingredients)
        if ingredients and not matched:
            continue

        priority_matched = matched_ingredients(text, priority)
        ingredient_score = len(matched) / max(1, len(ingredients))

        recipe_ingredients = extract_ingredient_names(recipe.ingredients_text)
        non_staples = [item for item in recipe_ingredients if item not in PANTRY_STAPLES]
        additional = [item for item in non_staples if item not in matched]
        shopping_score = _clamp(1.0 - len(additional) / max(4, len(non_staples) or 1))
        priority_score = (
            len(priority_matched) / len(priority) if priority else 0.5
        )
        nutrition_score = _nutrition_score(recipe, preferences)
        convenience_score, time_label = _convenience_score(
            recipe, preferences.max_time_minutes
        )

        if preferences.max_time_minutes and convenience_score == 0.0:
            continue

        structured = (
            0.35 * ingredient_score
            + 0.15 * shopping_score
            + 0.15 * priority_score
            + 0.25 * nutrition_score
            + 0.10 * convenience_score
        )
        breakdown = ScoreBreakdown(
            ingredient_match=ingredient_score,
            shopping_ease=shopping_score,
            priority_use=priority_score,
            slow_aging_fit=nutrition_score,
            convenience=convenience_score,
        )
        ranked.append(
            RankedRecipe(
                recipe=recipe,
                structured_score=structured,
                final_score=structured,
                breakdown=breakdown,
                matched_ingredients=matched,
                additional_ingredients=additional[:6],
                reasons=_make_reasons(recipe, matched, priority_matched),
                estimated_time=time_label,
            )
        )

    ranked.sort(key=lambda item: item.structured_score, reverse=True)
    return ranked[:limit]


def build_reranker_query(preferences: UserPreferences) -> str:
    conditions = [
        f"냉장고 재료: {', '.join(preferences.ingredients)}",
        f"우선 사용할 재료: {', '.join(preferences.priority_ingredients) or '없음'}",
        f"제외 재료: {', '.join(preferences.excluded_ingredients) or '없음'}",
        "채소와 통곡물 또는 콩류를 포함한 균형 잡힌 한 끼",
    ]
    if preferences.high_protein:
        conditions.append("단백질이 충분한 메뉴")
    if preferences.low_sodium:
        conditions.append("나트륨이 낮은 메뉴")
    if preferences.max_time_minutes:
        conditions.append(f"{preferences.max_time_minutes}분 안에 가능한 메뉴")
    return ". ".join(conditions)


def recipe_document(item: RankedRecipe) -> str:
    recipe = item.recipe
    nutrition = (
        f"열량 {recipe.calories_kcal or 0:g}kcal, "
        f"단백질 {recipe.protein_g or 0:g}g, "
        f"나트륨 {recipe.sodium_mg or 0:g}mg"
    )
    return (
        f"{recipe.name}. 종류 {recipe.category}. 조리방법 {recipe.method}. "
        f"재료 {recipe.ingredients_text}. {nutrition}. "
        f"예상 시간 {item.estimated_time}."
    )


def apply_semantic_scores(
    ranked: Sequence[RankedRecipe], semantic_scores: Sequence[float], weight: float = 0.15
) -> list[RankedRecipe]:
    if len(ranked) != len(semantic_scores):
        raise ValueError("후보와 의미 점수 개수가 일치해야 합니다.")
    weight = _clamp(weight)
    for item, score in zip(ranked, semantic_scores, strict=True):
        normalized = _clamp(float(score))
        item.semantic_score = normalized
        item.final_score = (1.0 - weight) * item.structured_score + weight * normalized
    return sorted(ranked, key=lambda item: item.final_score, reverse=True)

