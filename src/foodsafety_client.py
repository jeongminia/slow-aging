from __future__ import annotations

import math
from urllib.parse import quote

import requests

from src.models import Recipe


DEFAULT_BASE_URL = "https://openapi.foodsafetykorea.go.kr/api"
SERVICE_ID = "COOKRCP01"


class FoodSafetyAPIError(RuntimeError):
    """식품안전나라 API를 안전하게 사용자에게 전달하기 위한 오류."""


class FoodSafetyClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: int = 30,
    ) -> None:
        if not api_key.strip():
            raise ValueError("식품안전나라 API 인증키가 필요합니다.")
        self._api_key = api_key.strip()
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": "slow-aging-fridge-demo/1.0",
            }
        )

    def _page_url(self, start: int, end: int) -> str:
        safe_key = quote(self._api_key, safe="")
        return (
            f"{self._base_url}/{safe_key}/{SERVICE_ID}/json/{start}/{end}"
        )

    def _fetch_page(self, start: int, end: int) -> tuple[list[dict], int]:
        try:
            response = self._session.get(
                self._page_url(start, end), timeout=self._timeout
            )
            response.raise_for_status()
            payload = response.json()
        except requests.Timeout as exc:
            raise FoodSafetyAPIError(
                "식품안전나라 응답 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요."
            ) from exc
        except (requests.RequestException, ValueError) as exc:
            # 예외 문자열에는 URL 경로의 인증키가 포함될 수 있으므로 노출하지 않는다.
            raise FoodSafetyAPIError(
                "식품안전나라 API에 연결하지 못했습니다. 네트워크와 API 주소를 확인해 주세요."
            ) from exc

        service = payload.get(SERVICE_ID)
        if not isinstance(service, dict):
            raise FoodSafetyAPIError(
                "식품안전나라에서 예상하지 못한 형식의 응답을 받았습니다."
            )

        result = service.get("RESULT") or {}
        code = str(result.get("CODE") or "INFO-000")
        if code == "INFO-200":
            return [], int(service.get("total_count") or 0)
        if code != "INFO-000":
            messages = {
                "INFO-100": "식품안전나라 인증키가 유효하지 않습니다.",
                "INFO-300": "식품안전나라 API 호출 한도를 초과했습니다.",
                "INFO-400": "해당 API를 사용할 권한이 없습니다.",
                "ERROR-310": "COOKRCP01 서비스를 찾을 수 없습니다.",
                "ERROR-500": "식품안전나라 서버에서 오류가 발생했습니다.",
            }
            raise FoodSafetyAPIError(
                messages.get(code, f"식품안전나라 API 오류가 발생했습니다. ({code})")
            )

        rows = service.get("row") or []
        if not isinstance(rows, list):
            rows = []
        try:
            total_count = int(service.get("total_count") or len(rows))
        except (TypeError, ValueError):
            total_count = len(rows)
        return rows, total_count

    def fetch_all_recipes(self, page_size: int = 1000) -> list[Recipe]:
        if not 1 <= page_size <= 1000:
            raise ValueError("page_size는 1 이상 1000 이하여야 합니다.")

        first_rows, total_count = self._fetch_page(1, page_size)
        all_rows = list(first_rows)
        page_count = math.ceil(total_count / page_size) if total_count else 1

        for page in range(1, page_count):
            start = page * page_size + 1
            end = min((page + 1) * page_size, total_count)
            rows, _ = self._fetch_page(start, end)
            all_rows.extend(rows)

        recipes: list[Recipe] = []
        seen: set[str] = set()
        for row in all_rows:
            recipe = Recipe.from_api_row(row)
            if not recipe.recipe_id or recipe.recipe_id in seen:
                continue
            seen.add(recipe.recipe_id)
            recipes.append(recipe)
        return recipes

