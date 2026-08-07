from __future__ import annotations

import ast
import base64
from io import BytesIO
import json
import logging
import re
from typing import Any

from huggingface_hub import InferenceClient
from PIL import Image, ImageOps


DEFAULT_MODEL = "Qwen/Qwen3.5-9B"
DEFAULT_PROVIDER = "auto"
LOGGER = logging.getLogger(__name__)

_HF_TOKEN_PATTERN = re.compile(r"\bhf_[A-Za-z0-9_-]{10,}\b")
_BEARER_PATTERN = re.compile(
    r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;'\"]+"
)
_DATA_URL_PATTERN = re.compile(
    r"data:image/[^;\s]+;base64,[A-Za-z0-9+/=]+", re.IGNORECASE
)


class VLMError(RuntimeError):
    def __init__(self, message: str, diagnostic: str = "") -> None:
        super().__init__(message)
        self.diagnostic = diagnostic


def _redact_sensitive(value: Any, limit: int = 1_500) -> str:
    """Provider 오류에서 토큰과 base64 이미지 데이터를 제거한다."""
    text = str(value or "")
    text = _DATA_URL_PATTERN.sub("data:image/<redacted>;base64,<redacted>", text)
    text = _BEARER_PATTERN.sub(r"\1<redacted>", text)
    text = _HF_TOKEN_PATTERN.sub("hf_<redacted>", text)
    text = re.sub(r"[\r\n\t]+", " ", text).strip()
    return text[:limit]


def _provider_message(response: Any, fallback: str) -> str:
    if response is None:
        return _redact_sensitive(fallback)

    try:
        payload = response.json()
    except Exception:
        payload = None

    if isinstance(payload, dict):
        message = (
            payload.get("error")
            or payload.get("message")
            or payload.get("detail")
        )
        if isinstance(message, dict):
            message = message.get("message") or json.dumps(
                message, ensure_ascii=False
            )
        if message:
            return _redact_sensitive(message)

    response_text = getattr(response, "text", "")
    return _redact_sensitive(response_text or fallback)


def _status_hint(
    status_code: int | None, error_type: str, provider_message: str = ""
) -> str:
    lowered_message = provider_message.lower()
    if (
        "not supported by any provider you have enabled" in lowered_message
        or "model_not_supported" in lowered_message
    ):
        return "선택한 모델을 제공하는 Inference Provider가 계정에서 활성화되어 있지 않습니다."
    hints = {
        400: "요청 형식 또는 해당 Provider의 멀티모달 입력 호환성을 확인하세요.",
        401: "HF_TOKEN이 유효한지 확인하세요.",
        402: "Hugging Face Inference Providers 크레딧 또는 결제 설정을 확인하세요.",
        403: "토큰에 'Make calls to Inference Providers' 권한이 있는지 확인하세요.",
        404: "모델 ID와 현재 모델을 제공하는 Inference Provider가 있는지 확인하세요.",
        408: "Provider 응답 시간이 초과되었습니다. 잠시 후 다시 시도하세요.",
        413: "업로드 이미지 또는 요청 본문이 너무 큽니다. 더 작은 이미지를 사용하세요.",
        422: "Provider가 요청 매개변수나 이미지 형식을 처리하지 못했습니다.",
        429: "호출 한도에 도달했습니다. 잠시 후 다시 시도하세요.",
        500: "Inference Provider 내부 오류입니다. 잠시 후 다시 시도하세요.",
        502: "Hugging Face 라우터와 Provider 사이의 연결 오류입니다.",
        503: "모델이 일시적으로 준비되지 않았거나 Provider를 사용할 수 없습니다.",
        504: "Inference Provider 응답이 시간 초과되었습니다.",
    }
    if status_code in hints:
        return hints[status_code]
    if error_type == "StopIteration":
        return "현재 모델에 연결할 수 있는 Provider를 찾지 못했거나 클라이언트가 Provider 정보를 해석하지 못했습니다."
    if "Timeout" in error_type:
        return "네트워크 또는 Provider 응답 시간이 초과되었습니다."
    if any(term in error_type for term in ("Connection", "Network", "Proxy")):
        return "네트워크, 프록시 또는 방화벽 연결을 확인하세요."
    return "아래 Provider 메시지와 오류 유형을 확인하세요."


def _build_failure_diagnostic(
    exc: Exception, model_id: str, provider: str = DEFAULT_PROVIDER
) -> str:
    response = getattr(exc, "response", None)
    raw_status = getattr(response, "status_code", None)
    try:
        status_code = int(raw_status) if raw_status is not None else None
    except (TypeError, ValueError):
        status_code = None

    headers = getattr(response, "headers", {}) or {}
    request_id = ""
    for name in ("x-request-id", "x-amzn-requestid", "x-correlation-id"):
        try:
            request_id = str(headers.get(name) or "").strip()
        except AttributeError:
            request_id = ""
        if request_id:
            break

    error_type = type(exc).__name__
    provider_message = _provider_message(response, str(exc))
    lines = [
        f"오류 유형: {error_type}",
        f"HTTP 상태: {status_code if status_code is not None else '확인 불가'}",
        f"모델: {_redact_sensitive(model_id, limit=200)}",
        f"Provider 선택: {_redact_sensitive(provider, limit=100)}",
        f"진단: {_status_hint(status_code, error_type, provider_message)}",
    ]
    if request_id:
        lines.append(f"요청 ID: {_redact_sensitive(request_id, limit=200)}")
    if provider_message:
        lines.append(f"Provider 메시지: {provider_message}")
    return "\n".join(lines)


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
        preview = _redact_sensitive(cleaned, limit=800) or "<빈 응답>"
        diagnostic = (
            f"응답 길이: {len(text):,}자\n"
            f"응답 미리보기: {preview}"
        )
        LOGGER.error("VLM JSON 파싱 실패\n%s", diagnostic)
        raise VLMError(
            "VLM JSON을 해석하지 못했습니다. 다시 시도해 주세요.",
            diagnostic=diagnostic,
        )

    ingredients = payload.get("ingredients")
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
    provider: str = DEFAULT_PROVIDER,
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
생각 과정, <think> 태그, Markdown 코드 블록을 출력하지 마세요.
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
        diagnostic = _build_failure_diagnostic(exc, model_id, provider)
        # 원본 예외 문자열에는 Provider 구현에 따라 요청 본문이 포함될 수 있으므로
        # traceback 대신 마스킹된 진단 정보만 터미널에 기록한다.
        LOGGER.error("Hugging Face VLM 요청 실패\n%s", diagnostic)
        raise VLMError(
            "Hugging Face VLM 호출에 실패했습니다.", diagnostic=diagnostic
        ) from exc
    return parse_vlm_response(_message_text(response))
