from __future__ import annotations

import ast
import base64
from io import BytesIO
import json
import re
from typing import Any

from huggingface_hub import InferenceClient
from PIL import Image, ImageOps

from src.ingredients import ALIASES, canonicalize


DEFAULT_MODEL = "Qwen/Qwen3.5-9B"
DEFAULT_PROVIDER = "auto"


class VLMError(RuntimeError):
    pass


def _prepare_image(image_bytes: bytes, max_edge: int = 1600) -> tuple[bytes, str]:
    try:
        image = Image.open(BytesIO(image_bytes))
        image = ImageOps.exif_transpose(image).convert("RGB")
    except Exception as exc:
        raise VLMError("이미지 파일을 읽을 수 없습니다.") from exc

    image.thumbnail((max_edge, max_edge))
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=88, optimize=True)
    return buffer.getvalue(), "image/jpeg"


def _message_text(response: Any) -> str:
    try:
        content = response.choices[0].message.content
    except (AttributeError, IndexError, KeyError) as exc:
        raise VLMError("VLM 응답에서 텍스트를 찾지 못했습니다.") from exc
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(item.get("text", "")) if isinstance(item, dict) else str(item)
            for item in content
        )
    return str(content)


def _confidence(value: Any, default: float | None = None) -> float | None:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, score))


def _preferred_ingredient_name(item: dict[str, Any]) -> tuple[str, float]:
    """한글·영문 후보 중 언어별 신뢰도가 더 높은 이름 하나를 선택한다."""
    name_ko = str(item.get("name_ko") or "").strip()
    name_en = str(
        item.get("name_en") or item.get("canonical_name_en") or ""
    ).strip()
    fallback_name = str(item.get("name") or "").strip()
    shared_confidence = _confidence(item.get("confidence"), 0.5)
    if shared_confidence is None:
        shared_confidence = 0.5
    confidence_ko = _confidence(item.get("confidence_ko"))
    confidence_en = _confidence(item.get("confidence_en"))

    if name_ko and name_en:
        ko_score = confidence_ko if confidence_ko is not None else shared_confidence
        en_score = confidence_en if confidence_en is not None else shared_confidence
        # 동점이면 한국어 UI의 일관성을 위해 한국어 이름을 우선한다.
        return (name_en, en_score) if en_score > ko_score else (name_ko, ko_score)
    if name_ko:
        return name_ko, confidence_ko if confidence_ko is not None else shared_confidence
    if name_en:
        return name_en, confidence_en if confidence_en is not None else shared_confidence
    return fallback_name, shared_confidence


def parse_vlm_response(text: str) -> list[dict[str, Any]]:
    # Qwen3.5 Provider가 설정을 무시하고 thinking 내용을 반환하는 경우에도
    # 최종 JSON만 파싱할 수 있도록 추론 블록과 Markdown fence를 제거한다.
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.I | re.S).strip()
    cleaned = re.sub(r"```(?:json)?", "", cleaned, flags=re.I).replace("```", "")

    payload: Any = None
    decoder = json.JSONDecoder()
    for start, character in enumerate(cleaned):
        if character != "{":
            continue
        try:
            candidate, _ = decoder.raw_decode(cleaned[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            payload = candidate
            break

    # 흔한 비표준 출력인 후행 쉼표와 작은따옴표 딕셔너리를 제한적으로 복구한다.
    if payload is None:
        first_brace = cleaned.find("{")
        last_brace = cleaned.rfind("}")
        if first_brace >= 0 and last_brace > first_brace:
            candidate_text = cleaned[first_brace : last_brace + 1]
            without_trailing_commas = re.sub(
                r",\s*([}\]])", r"\1", candidate_text
            )
            try:
                payload = json.loads(without_trailing_commas)
            except json.JSONDecodeError:
                try:
                    literal = ast.literal_eval(candidate_text)
                    payload = literal if isinstance(literal, dict) else None
                except (SyntaxError, ValueError):
                    payload = None

    if not isinstance(payload, dict):
        raise VLMError("VLM JSON을 해석하지 못했습니다. 다시 시도해 주세요.")

    ingredients = payload.get("ingredients")
    if not isinstance(ingredients, list):
        raise VLMError("VLM 응답에 ingredients 배열이 없습니다.")

    normalized_by_ingredient: dict[str, dict[str, Any]] = {}
    ingredient_order: list[str] = []
    for item in ingredients:
        if not isinstance(item, dict):
            continue
        name, confidence = _preferred_ingredient_name(item)
        if not name:
            continue
        ingredient_key = canonicalize(name) or name.casefold()
        display_name = ingredient_key if ingredient_key in ALIASES else name
        existing = normalized_by_ingredient.get(ingredient_key)
        if existing and existing["confidence"] >= confidence:
            continue
        if existing is None:
            ingredient_order.append(ingredient_key)
        normalized_by_ingredient[ingredient_key] = {
            "name": display_name,
            "confidence": confidence,
        }
    normalized = [
        normalized_by_ingredient[key]
        for key in ingredient_order
        if key in normalized_by_ingredient
    ]
    if not normalized:
        raise VLMError("사진에서 식재료를 찾지 못했습니다. Step 2 표에 직접 추가해 주세요.")
    return normalized


def recognize_ingredients(
    image_bytes: bytes,
    hf_token: str,
    model_id: str = DEFAULT_MODEL,
    provider: str = DEFAULT_PROVIDER,
) -> list[dict[str, Any]]:
    if not hf_token.strip():
        raise VLMError("Hugging Face 토큰이 필요합니다.")
    encoded_image, mime_type = _prepare_image(image_bytes)
    data_url = f"data:{mime_type};base64,{base64.b64encode(encoded_image).decode('ascii')}"

    prompt = """
냉장고 사진에서 실제로 보이는 식재료만 식별하세요.
레시피를 만들거나 보이지 않는 재료를 추측하지 마세요.
포장 또는 가림 때문에 확실하지 않으면 언어별 confidence를 낮게 주세요.
유통기한과 정확한 수량은 추정하지 마세요.
각 식재료마다 한국어명과 영문명을 각각 판별하고 언어별 confidence를 주세요.
두 이름이 같은 식재료인지 확실하지 않으면 확신이 낮은 쪽의 confidence를 낮추세요.
사진 속 하나의 식재료를 한국어와 영어로 나누어 두 항목으로 만들지 마세요.

반드시 설명 없이 아래 형식의 JSON 객체만 반환하세요.
생각 과정, <think> 태그, Markdown 코드 블록을 출력하지 마세요.
{
  "ingredients": [
    {
      "name_ko": "두부",
      "name_en": "tofu",
      "confidence_ko": 0.93,
      "confidence_en": 0.96
    }
  ],
  "unknown_items": []
}
""".strip()

    try:
        client = InferenceClient(provider=provider, api_key=hf_token.strip())
        response = client.chat.completions.create(
            model=model_id,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": data_url}},
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
            temperature=0.2,
            top_p=0.8,
            presence_penalty=1.5,
            max_tokens=1_200,
            extra_body={
                "top_k": 20,
                "chat_template_kwargs": {"enable_thinking": False},
            },
        )
    except Exception as exc:
        raise VLMError(
            "Hugging Face VLM 호출에 실패했습니다. 잠시 후 다시 시도하거나 "
            "Step 2 표에 재료를 직접 추가해 주세요."
        ) from exc
    return parse_vlm_response(_message_text(response))
