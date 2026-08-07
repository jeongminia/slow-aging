from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any


def _text(value: Any) -> str:
    return str(value or "").strip()


def _number(value: Any) -> float | None:
    text = _text(value).replace(",", "")
    if not text:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group())
    except ValueError:
        return None


def secure_image_url(url: str) -> str:
    """식품안전나라 이미지 URL을 HTTPS로 표시한다."""
    url = _text(url)
    if url.startswith("http://www.foodsafetykorea.go.kr/"):
        return "https://www.foodsafetykorea.go.kr/" + url.removeprefix(
            "http://www.foodsafetykorea.go.kr/"
        )
    return url


@dataclass(frozen=True)
class RecipeStep:
    order: int
    text: str
    image_url: str = ""


@dataclass(frozen=True)
class Recipe:
    recipe_id: str
    name: str
    method: str
    category: str
    serving_weight_g: float | None
    calories_kcal: float | None
    carbohydrate_g: float | None
    protein_g: float | None
    fat_g: float | None
    sodium_mg: float | None
    hashtags: str
    image_url: str
    thumbnail_url: str
    ingredients_text: str
    steps: tuple[RecipeStep, ...] = field(default_factory=tuple)
    reduction_tip: str = ""

    @classmethod
    def from_api_row(cls, row: dict[str, Any]) -> "Recipe":
        steps: list[RecipeStep] = []
        for index in range(1, 21):
            suffix = f"{index:02d}"
            raw_step = _text(row.get(f"MANUAL{suffix}"))
            if not raw_step:
                continue
            # 일부 원본 데이터에는 앞쪽 단계 번호와 끝쪽 사진 참조용 a/b/c가
            # 함께 들어 있다. 화면에서 번호가 중복되지 않도록 본문만 보존한다.
            clean_step = re.sub(r"^\s*\d+\s*[.)]\s*", "", raw_step)
            clean_step = re.sub(r"\s*[a-zA-Z]\s*$", "", clean_step).strip()
            steps.append(
                RecipeStep(
                    order=index,
                    text=clean_step,
                    image_url=secure_image_url(
                        _text(row.get(f"MANUAL_IMG{suffix}"))
                    ),
                )
            )

        return cls(
            recipe_id=_text(row.get("RCP_SEQ")),
            name=_text(row.get("RCP_NM")) or "이름 없는 레시피",
            method=_text(row.get("RCP_WAY2")),
            category=_text(row.get("RCP_PAT2")),
            serving_weight_g=_number(row.get("INFO_WGT")),
            calories_kcal=_number(row.get("INFO_ENG")),
            carbohydrate_g=_number(row.get("INFO_CAR")),
            protein_g=_number(row.get("INFO_PRO")),
            fat_g=_number(row.get("INFO_FAT")),
            sodium_mg=_number(row.get("INFO_NA")),
            hashtags=_text(row.get("HASH_TAG")),
            image_url=secure_image_url(_text(row.get("ATT_FILE_NO_MK"))),
            thumbnail_url=secure_image_url(_text(row.get("ATT_FILE_NO_MAIN"))),
            ingredients_text=_text(row.get("RCP_PARTS_DTLS")),
            steps=tuple(steps),
            reduction_tip=_text(row.get("RCP_NA_TIP")),
        )

    @property
    def searchable_text(self) -> str:
        step_text = " ".join(step.text for step in self.steps)
        return " ".join(
            part
            for part in (
                self.name,
                self.method,
                self.category,
                self.hashtags,
                self.ingredients_text,
                step_text,
            )
            if part
        )


@dataclass(frozen=True)
class ScoreBreakdown:
    ingredient_match: float
    shopping_ease: float
    priority_use: float
    slow_aging_fit: float
    convenience: float


@dataclass
class RankedRecipe:
    recipe: Recipe
    structured_score: float
    final_score: float
    breakdown: ScoreBreakdown
    matched_ingredients: list[str]
    additional_ingredients: list[str]
    reasons: list[str]
    estimated_time: str
    semantic_score: float | None = None
