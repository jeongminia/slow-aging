from src.ingredients import canonicalize, contains_ingredient, extract_known_ingredients


def test_korean_aliases_are_canonicalized():
    assert canonicalize("계란") == "달걀"
    assert canonicalize("순두부") == "두부"
    assert contains_ingredient("순두부 100g, 애호박 20g", "두부")


def test_known_ingredients_are_extracted():
    values = extract_known_ingredients("현미밥, 두부, 시금치, 달걀")
    assert {"현미", "두부", "시금치", "달걀"}.issubset(values)

