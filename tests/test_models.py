from src.models import Recipe


def test_recipe_parses_api_row_and_steps():
    row = {
        "RCP_SEQ": "10",
        "RCP_NM": "두부 곤약 나물 비빔밥",
        "RCP_WAY2": "끓이기",
        "RCP_PAT2": "밥",
        "INFO_ENG": "225",
        "INFO_CAR": "26g",
        "INFO_PRO": "14",
        "INFO_FAT": "7",
        "INFO_NA": "97mg",
        "RCP_PARTS_DTLS": "두부 110g, 현미쌀 3g, 콩나물 15g",
        "ATT_FILE_NO_MK": "http://www.foodsafetykorea.go.kr/image.png",
        "MANUAL01": "1. 두부를 데친다.a",
        "MANUAL_IMG01": "http://www.foodsafetykorea.go.kr/step.png",
        "MANUAL02": "2. 재료를 섞는다.",
        "RCP_NA_TIP": "소금 대신 향신료를 사용한다.",
    }

    recipe = Recipe.from_api_row(row)

    assert recipe.recipe_id == "10"
    assert recipe.protein_g == 14
    assert recipe.sodium_mg == 97
    assert recipe.image_url.startswith("https://")
    assert len(recipe.steps) == 2
    assert recipe.steps[0].order == 1
    assert recipe.steps[0].text == "두부를 데친다."
    assert recipe.steps[0].image_url.startswith("https://")


def test_recipe_preserves_manual_field_order_when_a_step_is_missing():
    recipe = Recipe.from_api_row(
        {
            "RCP_SEQ": "11",
            "RCP_NM": "단계 누락 예시",
            "MANUAL02": "2. 재료를 섞는다.",
            "MANUAL05": "5. 그릇에 담는다.",
        }
    )

    assert [step.order for step in recipe.steps] == [2, 5]
    assert [step.text for step in recipe.steps] == ["재료를 섞는다.", "그릇에 담는다."]
