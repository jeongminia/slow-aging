from src.foodsafety_client import FoodSafetyClient


class FakeClient(FoodSafetyClient):
    def __init__(self):
        super().__init__("not-a-real-key")
        self.calls = []

    def _fetch_page(self, start, end):
        self.calls.append((start, end))
        rows = [
            {
                "RCP_SEQ": str(index),
                "RCP_NM": f"레시피 {index}",
                "RCP_PARTS_DTLS": "두부 100g",
            }
            for index in range(start, min(end, 3) + 1)
        ]
        return rows, 3


def test_fetch_all_recipes_paginates_and_deduplicates():
    client = FakeClient()
    recipes = client.fetch_all_recipes(page_size=2)

    assert [recipe.recipe_id for recipe in recipes] == ["1", "2", "3"]
    assert client.calls == [(1, 2), (3, 3)]

