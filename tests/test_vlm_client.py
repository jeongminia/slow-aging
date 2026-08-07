import pytest

from src.vlm_client import (
    VLMError,
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


def test_selects_higher_confidence_language_for_mismatched_names():
    result = parse_vlm_response(
        """{"ingredients": [{
          "name_ko": "고구마",
          "name_en": "chickpeas",
          "confidence_ko": 0.31,
          "confidence_en": 0.94
        }]}"""
    )

    assert result == [{"name": "chickpeas", "confidence": 0.94}]


def test_prefers_korean_name_when_language_confidence_is_tied():
    result = parse_vlm_response(
        """{"ingredients": [{
          "name_ko": "병아리콩",
          "name_en": "chickpeas",
          "confidence_ko": 0.9,
          "confidence_en": 0.9
        }]}"""
    )

    assert result == [{"name": "병아리콩", "confidence": 0.9}]


def test_rejects_invalid_payload():
    with pytest.raises(VLMError, match="VLM JSON을 해석하지 못했습니다"):
        parse_vlm_response("not json")


def test_parses_json_after_thinking_block():
    result = parse_vlm_response(
        """<think>사진을 자세히 살펴본다.</think>
        ```json
        {"ingredients": [{"name_ko": "두부", "confidence": 0.91}]}
        ```"""
    )

    assert result[0]["name"] == "두부"


def test_recovers_json_with_trailing_commas():
    result = parse_vlm_response(
        '{"ingredients": [{"name_ko": "달걀", "confidence": 0.8,}],}'
    )

    assert result[0]["name"] == "달걀"
