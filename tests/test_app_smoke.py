from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_streamlit_app_starts_without_secrets():
    app_path = Path(__file__).parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=10).run()

    assert not app.exception
    assert any("오늘의 레시피 3개 추천" in button.label for button in app.button)
    assert any("직접 재료 입력" in area.label for area in app.text_area)
