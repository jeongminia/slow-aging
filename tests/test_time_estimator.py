from src.models import RecipeStep
from src.time_estimator import estimate_minutes, format_estimated_time


def test_estimates_explicit_ranges_and_minutes():
    steps = [
        RecipeStep(1, "콩을 20~25분 삶는다."),
        RecipeStep(2, "5분간 더 끓인다."),
    ]
    value = estimate_minutes(steps)
    assert value == (25, 30)
    assert format_estimated_time(value) == "약 25~30분"


def test_unknown_time_is_not_invented():
    assert estimate_minutes([RecipeStep(1, "재료를 잘 섞는다.")]) is None
    assert format_estimated_time(None) == "시간 정보 없음"

