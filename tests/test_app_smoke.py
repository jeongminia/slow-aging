import json
from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest

from src.models import Recipe, RecipeStep
from src.ranking import UserPreferences, rank_recipes


def test_streamlit_app_starts_without_secrets():
    app_path = Path(__file__).parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=10).run()

    assert not app.exception
    assert any("오늘의 레시피 3개 추천" in button.label for button in app.button)
    assert any(button.label == "재료 찾기" for button in app.button)
    assert any(button.label == "표 정렬" for button in app.button)
    assert not app.text_area
    assert any("쉿, 나만 저속노화!" in markdown.value for markdown in app.markdown)


def test_ingredient_table_can_be_sorted_after_editing():
    app_path = Path(__file__).parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=10)
    app.session_state["ingredients_df"] = pd.DataFrame(
        [
            {"사용": True, "재료명": "두부", "신뢰도": 0.8, "우선 소진": False},
            {"사용": True, "재료명": "고구마", "신뢰도": 0.9, "우선 소진": False},
        ]
    )
    app.session_state["ingredient_editor_version"] = 0
    app.run()

    next(box for box in app.selectbox if box.label == "정렬 기준").select("재료명")
    next(box for box in app.selectbox if box.label == "정렬 방향").select("오름차순")
    next(button for button in app.button if button.label == "표 정렬").click()
    app.run()

    assert not app.exception
    assert app.session_state["ingredients_df"]["재료명"].tolist() == [
        "고구마",
        "두부",
    ]


def test_recommendation_renders_weighted_score_pie_chart():
    app_path = Path(__file__).parents[1] / "app.py"
    recipe = Recipe(
        recipe_id="demo",
        name="두부 현미밥",
        method="끓이기",
        category="밥",
        serving_weight_g=300,
        calories_kcal=400,
        carbohydrate_g=50,
        protein_g=24,
        fat_g=10,
        sodium_mg=250,
        hashtags="",
        image_url="",
        thumbnail_url="",
        ingredients_text="두부, 현미, 시금치",
        steps=(RecipeStep(1, "10분 끓인다."),),
    )
    recommendation = rank_recipes(
        [recipe], UserPreferences(ingredients=("두부",))
    )[0]
    app = AppTest.from_file(str(app_path), default_timeout=10)
    app.session_state["recommendations"] = [recommendation]
    app.run()

    assert not app.exception
    charts = app.get("vega_lite_chart")
    assert len(charts) == 1
    chart_spec = json.loads(charts[0].proto.spec)
    arc_encoding = chart_spec["layer"][0]["encoding"]
    assert arc_encoding["theta"]["field"] == "기여 비중"
    assert "남은 점수" not in arc_encoding["color"]["scale"]["domain"]
    assert arc_encoding["color"]["scale"]["range"] == [
        "#0B4F3C",
        "#238B45",
        "#66A61E",
        "#A6BD3A",
        "#4DB6AC",
    ]
    assert any(expander.label == "맞춤 추천 점수 구성" for expander in app.expander)
