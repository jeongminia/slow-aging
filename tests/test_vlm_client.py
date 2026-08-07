import pytest

from src.vlm_client import VLMError, parse_vlm_response


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

