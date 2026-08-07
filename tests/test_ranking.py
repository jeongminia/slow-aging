from src.models import Recipe, RecipeStep
from src.ranking import UserPreferences, rank_recipes


def recipe(
    recipe_id: str,
    name: str,
    ingredients: str,
    protein: float,
    sodium: float,
    category: str = "밥",
):
    return Recipe(
        recipe_id=recipe_id,
        name=name,
        method="끓이기",
        category=category,
        serving_weight_g=300,
        calories_kcal=400,
        carbohydrate_g=50,
        protein_g=protein,
        fat_g=10,
        sodium_mg=sodium,
        hashtags="",
        image_url="",
        thumbnail_url="",
        ingredients_text=ingredients,
        steps=(RecipeStep(1, "10분간 끓인다."),),
    )


def test_ranking_prefers_matching_high_protein_low_sodium_recipe():
    recipes = [
        recipe("1", "두부 현미 덮밥", "두부 100g, 현미밥 200g, 시금치 30g", 24, 250),
        recipe("2", "두부 튀김", "두부 100g, 식용유 50g", 10, 800),
        recipe("3", "새우 볶음밥", "새우 100g, 쌀 200g", 15, 500),
    ]
    prefs = UserPreferences(
        ingredients=("두부", "시금치", "현미밥"),
        priority_ingredients=("시금치",),
    )

    ranked = rank_recipes(recipes, prefs)

    assert ranked[0].recipe.recipe_id == "1"
    assert set(ranked[0].matched_ingredients) == {"두부", "시금치", "현미"}
    assert all(item.recipe.recipe_id != "3" for item in ranked)


def test_excluded_ingredient_is_hard_filter():
    recipes = [
        recipe("1", "버섯 두부밥", "두부 100g, 표고버섯 20g", 20, 200),
        recipe("2", "시금치 두부밥", "두부 100g, 시금치 20g", 18, 250),
    ]
    prefs = UserPreferences(
        ingredients=("두부",), excluded_ingredients=("버섯",)
    )

    ranked = rank_recipes(recipes, prefs)

    assert [item.recipe.recipe_id for item in ranked] == ["2"]
