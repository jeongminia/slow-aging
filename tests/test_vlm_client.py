import pytest

from src.vlm_client import (
    VLMError,
    _build_failure_diagnostic,
    _redact_sensitive,
    parse_vlm_response,
)


def test_parses_json_code_fence_and_deduplicates():
    result = parse_vlm_response(
        """```json
        {"ingredients": [
          {"name_ko": "두부", "canonical_name_en": "tofu", "confidence": 0.9},
          {"name_ko": "두부", "confidence": 0.7},
          {"name_ko": "시금치", "confidence": "0.8"}
        ]}
        ```"""
    )
    assert [item["name"] for item in result] == ["두부", "시금치"]
    assert result[1]["confidence"] == 0.8


def test_rejects_invalid_payload():
    with pytest.raises(VLMError):
        parse_vlm_response("not json")


class FakeResponse:
    status_code = 403
    headers = {"x-request-id": "request-123"}
    text = ""

    def json(self):
        return {
            "error": "Bearer hf_abcdefghijklmnopqrstuvwxyz123456 has no inference permission"
        }


class FakeProviderError(RuntimeError):
    def __init__(self):
        super().__init__("provider call failed")
        self.response = FakeResponse()


def test_failure_diagnostic_keeps_cause_and_redacts_token():
    diagnostic = _build_failure_diagnostic(
        FakeProviderError(), "Qwen/Qwen3-VL-8B-Instruct"
    )

    assert "HTTP 상태: 403" in diagnostic
    assert "request-123" in diagnostic
    assert "Make calls to Inference Providers" in diagnostic
    assert "hf_abcdefghijklmnopqrstuvwxyz123456" not in diagnostic
    assert "hf_<redacted>" in diagnostic


def test_redacts_base64_image_data():
    redacted = _redact_sensitive(
        "payload=data:image/jpeg;base64,aGVsbG93b3JsZA=="
    )

    assert "aGVsbG93b3JsZA==" not in redacted
