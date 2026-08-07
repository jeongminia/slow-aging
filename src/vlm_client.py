from __future__ import annotations

import base64
from io import BytesIO
import json
import re
from typing import Any

from huggingface_hub import InferenceClient
from PIL import Image, ImageOps


DEFAULT_MODEL = "Qwen/Qwen3-VL-8B-Instruct"


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


def parse_vlm_response(text: str) -> list[dict[str, Any]]:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I)
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.S)
        if not match:
            raise VLMError("VLM이 유효한 JSON을 반환하지 않았습니다.")
        try:
            payload = json.loads(match.group())
        except json.JSONDecodeError as exc:
            raise VLMError("VLM JSON을 해석하지 못했습니다. 다시 시도해 주세요.") from exc

    ingredients = payload.get("ingredients") if isinstance(payload, dict) else None
    if not isinstance(ingredients, list):
        raise VLMError("VLM 응답에 ingredients 배열이 없습니다.")

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in ingredients:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name_ko") or item.get("name") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        try:
            confidence = float(item.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        normalized.append(
            {
                "name": name,
                "canonical_name_en": str(item.get("canonical_name_en") or "").strip(),
                "confidence": max(0.0, min(1.0, confidence)),
            }
        )
    if not normalized:
        raise VLMError("사진에서 식재료를 찾지 못했습니다. 직접 입력해 주세요.")
    return normalized


def recognize_ingredients(
    image_bytes: bytes,
    hf_token: str,
    model_id: str = DEFAULT_MODEL,
) -> list[dict[str, Any]]:
    if not hf_token.strip():
        raise VLMError("Hugging Face 토큰이 필요합니다.")
    encoded_image, mime_type = _prepare_image(image_bytes)
    data_url = f"data:{mime_type};base64,{base64.b64encode(encoded_image).decode('ascii')}"

    prompt = """
냉장고 사진에서 실제로 보이는 식재료만 식별하세요.
레시피를 만들거나 보이지 않는 재료를 추측하지 마세요.
포장 또는 가림 때문에 확실하지 않으면 confidence를 낮게 주세요.
유통기한과 정확한 수량은 추정하지 마세요.

반드시 설명 없이 아래 형식의 JSON 객체만 반환하세요.
{
  "ingredients": [
    {
      "name_ko": "두부",
      "canonical_name_en": "tofu",
      "confidence": 0.93
    }
  ],
  "unknown_items": []
}
""".strip()

    try:
        client = InferenceClient(provider="auto", api_key=hf_token.strip())
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
            temperature=0.1,
            max_tokens=900,
        )
    except Exception as exc:
        # 공급자 오류에는 토큰이나 요청 본문이 포함될 수 있어 원문을 노출하지 않는다.
        raise VLMError(
            "Hugging Face VLM 호출에 실패했습니다. 토큰, 크레딧, 모델 제공 상태를 확인해 주세요."
        ) from exc
    return parse_vlm_response(_message_text(response))

