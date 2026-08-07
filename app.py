from __future__ import annotations

import os
from typing import Any

import pandas as pd
import streamlit as st

from src.foodsafety_client import (
    DEFAULT_BASE_URL,
    FoodSafetyAPIError,
    FoodSafetyClient,
)
from src.ranking import (
    UserPreferences,
    apply_semantic_scores,
    build_reranker_query,
    rank_recipes,
    recipe_document,
)
from src.reranker import BGEReranker, dependencies_available
from src.vlm_client import DEFAULT_MODEL, VLMError, recognize_ingredients


st.set_page_config(
    page_title="냉장고를 부탁해 · 저속노화 레시피",
    page_icon="🥬",
    layout="wide",
)


def _secret(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value:
        return value
    try:
        return str(st.secrets.get(name, default))
    except Exception:
        return default


@st.cache_data(ttl=21_600, show_spinner=False)
def _load_recipes(_api_key: str, base_url: str):
    return FoodSafetyClient(api_key=_api_key, base_url=base_url).fetch_all_recipes()


@st.cache_resource(show_spinner=False)
def _load_reranker() -> BGEReranker:
    return BGEReranker()


def _ingredient_frame(items: list[dict[str, Any]]) -> pd.DataFrame:
    rows = [
        {
            "사용": True,
            "재료명": item.get("name", ""),
            "신뢰도": float(item.get("confidence", 1.0)),
            "우선 소진": False,
        }
        for item in items
        if str(item.get("name", "")).strip()
    ]
    return pd.DataFrame(rows, columns=["사용", "재료명", "신뢰도", "우선 소진"])


def _manual_items(text: str) -> list[dict[str, Any]]:
    names = [item.strip() for item in text.replace("\n", ",").split(",")]
    return [
        {"name": name, "confidence": 1.0}
        for name in dict.fromkeys(name for name in names if name)
    ]


def _set_ingredients(items: list[dict[str, Any]]) -> None:
    st.session_state.ingredients_df = _ingredient_frame(items)
    st.session_state.recommendations = []
    # 새 분석 결과가 기존 data_editor의 편집 상태에 덮이지 않게 초기화한다.
    st.session_state.pop("ingredient_editor", None)


def _format_number(value: float | None, unit: str) -> str:
    return "정보 없음" if value is None else f"{value:g}{unit}"


def _render_recipe(rank: int, item) -> None:
    recipe = item.recipe
    st.markdown(f"### {rank}. {recipe.name}")
    left, right = st.columns([1, 2], gap="large")
    with left:
        image_url = recipe.image_url or recipe.thumbnail_url
        if image_url:
            st.image(image_url, use_container_width=True)
        st.caption(
            " · ".join(part for part in (recipe.category, recipe.method) if part)
            or "레시피"
        )
    with right:
        st.markdown(
            f"<div class='score-pill'>추천 적합도 {item.final_score * 100:.0f}점</div>",
            unsafe_allow_html=True,
        )
        if item.reasons:
            st.markdown("  \n".join(f"✓ {reason}" for reason in item.reasons))
        if item.matched_ingredients:
            st.success("보유 재료: " + ", ".join(item.matched_ingredients))
        if item.additional_ingredients:
            st.info(
                "추가로 확인할 재료: " + ", ".join(item.additional_ingredients)
            )
        st.caption(
            f"예상 조리시간 {item.estimated_time} · 조리법 문장에서 추정한 값입니다."
        )

    metrics = st.columns(5)
    metrics[0].metric("열량", _format_number(recipe.calories_kcal, "kcal"))
    metrics[1].metric("탄수화물", _format_number(recipe.carbohydrate_g, "g"))
    metrics[2].metric("단백질", _format_number(recipe.protein_g, "g"))
    metrics[3].metric("지방", _format_number(recipe.fat_g, "g"))
    metrics[4].metric("나트륨", _format_number(recipe.sodium_mg, "mg"))

    with st.expander("추천 점수 근거"):
        breakdown = item.breakdown
        score_data = pd.DataFrame(
            {
                "항목": [
                    "재료 일치",
                    "장보기 부담",
                    "우선 소진",
                    "저속노화 적합",
                    "조리 편의",
                ],
                "점수": [
                    breakdown.ingredient_match,
                    breakdown.shopping_ease,
                    breakdown.priority_use,
                    breakdown.slow_aging_fit,
                    breakdown.convenience,
                ],
            }
        ).set_index("항목")
        st.bar_chart(score_data, horizontal=True, height=260)
        if item.semantic_score is not None:
            st.caption(f"BGE 의미 적합도: {item.semantic_score:.3f}")

    with st.expander("재료와 조리법 보기", expanded=rank == 1):
        st.markdown("#### 재료")
        st.write(recipe.ingredients_text or "재료 정보가 없습니다.")
        if recipe.reduction_tip:
            st.info("저감 조리 팁: " + recipe.reduction_tip)
        st.markdown("#### 만드는 법")
        if not recipe.steps:
            st.write("조리 단계 정보가 없습니다.")
        for step in recipe.steps:
            if step.image_url:
                step_text, step_image = st.columns([3, 1])
                step_text.markdown(f"**{step.order}.** {step.text}")
                step_image.image(step.image_url, use_container_width=True)
            else:
                st.markdown(f"**{step.order}.** {step.text}")


def _initialize_state() -> None:
    if "ingredients_df" not in st.session_state:
        st.session_state.ingredients_df = _ingredient_frame([])
    if "recommendations" not in st.session_state:
        st.session_state.recommendations = []
    if "recipe_count" not in st.session_state:
        st.session_state.recipe_count = 0


_initialize_state()

st.markdown(
    """
<style>
    .block-container {padding-top: 2rem; padding-bottom: 4rem; max-width: 1180px;}
    .hero {background: linear-gradient(135deg, #123c35 0%, #176e5b 58%, #31a58c 100%);
           border-radius: 24px; padding: 2.2rem 2.4rem; color: white; margin-bottom: 1.5rem;}
    .hero h1 {font-size: 2.45rem; margin: 0 0 .55rem 0; color: white;}
    .hero p {font-size: 1.05rem; margin: 0; opacity: .92;}
    .step-label {font-size: .78rem; font-weight: 800; color: #11745f; letter-spacing: .08em;}
    .score-pill {display: inline-block; background: #e5f7f1; color: #0b6b56;
                 border-radius: 999px; padding: .45rem .8rem; font-weight: 800;
                 margin-bottom: .8rem;}
    div[data-testid="stMetric"] {background: #f7faf9; border: 1px solid #e2ebe8;
                                 padding: .75rem; border-radius: 14px;}
</style>
<div class="hero">
  <h1>냉장고를 부탁해 🥬</h1>
  <p>냉장고 사진에서 재료를 찾고, 식품안전나라 건강 레시피 중 오늘의 저속노화 식사를 추천합니다.</p>
</div>
""",
    unsafe_allow_html=True,
)

foodsafety_key = _secret("FOODSAFETY_API_KEY")
hf_token = _secret("HF_TOKEN")
api_base_url = _secret("FOODSAFETY_API_BASE_URL", DEFAULT_BASE_URL)
vlm_model = _secret("VLM_MODEL", DEFAULT_MODEL)

with st.sidebar:
    st.header("연결 상태")
    st.write("✅ 식품안전나라 API" if foodsafety_key else "⚠️ 식품안전나라 키 없음")
    st.write("✅ Hugging Face VLM" if hf_token else "⚠️ Hugging Face 토큰 없음")
    if st.session_state.recipe_count:
        st.caption(f"레시피 {st.session_state.recipe_count:,}개 로드됨")
    st.divider()
    st.caption("인증키는 서버에서만 사용되며 화면이나 로그에 표시하지 않습니다.")
    if st.button("레시피 메모리 캐시 새로고침", use_container_width=True):
        _load_recipes.clear()
        st.session_state.recipe_count = 0
        st.toast("레시피 캐시를 비웠습니다.")

st.markdown('<div class="step-label">STEP 01 · 재료 입력</div>', unsafe_allow_html=True)
st.subheader("냉장고 사진 또는 직접 입력")

upload_col, manual_col = st.columns(2, gap="large")
with upload_col:
    uploaded = st.file_uploader(
        "냉장고 사진",
        type=["jpg", "jpeg", "png", "webp"],
        help="정면에서 밝게 촬영한 JPG 또는 PNG 한 장을 권장합니다.",
    )
    if uploaded:
        st.image(uploaded, caption="업로드한 냉장고 사진", use_container_width=True)
    analyze_disabled = uploaded is None or not hf_token
    if st.button(
        "Qwen3-VL 8B로 재료 찾기",
        type="primary",
        disabled=analyze_disabled,
        use_container_width=True,
    ):
        with st.spinner("사진 속 재료를 확인하고 있습니다..."):
            try:
                detected = recognize_ingredients(
                    uploaded.getvalue(), hf_token=hf_token, model_id=vlm_model
                )
                _set_ingredients(detected)
                st.success(f"재료 {len(detected)}개를 찾았습니다. 꼭 확인해 주세요.")
            except VLMError as exc:
                st.error(str(exc))
    if not hf_token:
        st.caption("HF_TOKEN을 설정하기 전에는 오른쪽 직접 입력을 사용할 수 있습니다.")

with manual_col:
    manual_text = st.text_area(
        "직접 재료 입력",
        placeholder="예: 두부, 시금치, 달걀, 현미밥",
        height=150,
    )
    if st.button("직접 입력 적용", use_container_width=True):
        items = _manual_items(manual_text)
        if items:
            _set_ingredients(items)
            st.success(f"재료 {len(items)}개를 입력했습니다.")
        else:
            st.warning("쉼표로 구분해 재료를 입력해 주세요.")

st.markdown('<div class="step-label">STEP 02 · 사용자 확인</div>', unsafe_allow_html=True)
st.subheader("인식된 재료를 확인하세요")
edited_df = st.data_editor(
    st.session_state.ingredients_df,
    num_rows="dynamic",
    hide_index=True,
    use_container_width=True,
    column_config={
        "사용": st.column_config.CheckboxColumn("사용", default=True),
        "재료명": st.column_config.TextColumn("재료명", required=True),
        "신뢰도": st.column_config.ProgressColumn(
            "신뢰도", min_value=0.0, max_value=1.0, format="%.2f"
        ),
        "우선 소진": st.column_config.CheckboxColumn("우선 소진", default=False),
    },
    disabled=["신뢰도"],
    key="ingredient_editor",
)

st.markdown('<div class="step-label">STEP 03 · 추천 조건</div>', unsafe_allow_html=True)
st.subheader("오늘의 식사 조건")
condition_cols = st.columns(4)
with condition_cols[0]:
    category = st.selectbox(
        "요리 종류", ["상관없음", "밥", "반찬", "국", "찌개", "후식", "일품"]
    )
with condition_cols[1]:
    use_time_limit = st.toggle("시간 제한 사용", value=False)
    max_time = st.slider("최대 조리시간", 10, 120, 40, 5, disabled=not use_time_limit)
with condition_cols[2]:
    high_protein = st.toggle("단백질 우선", value=True)
    low_sodium = st.toggle("나트륨 낮게", value=True)
with condition_cols[3]:
    excluded_text = st.text_input(
        "제외·알레르기 재료", placeholder="예: 버섯, 새우"
    )
    reranker_installed = dependencies_available()
    use_reranker = st.checkbox(
        "BGE Reranker 사용",
        value=False,
        disabled=not reranker_installed,
        help="상위 후보 20개를 한국어 식사 조건에 맞게 한 번 더 정렬합니다.",
    )
    if not reranker_installed:
        st.caption("선택 설치 후 사용할 수 있습니다.")

if st.button("오늘의 레시피 3개 추천", type="primary", use_container_width=True):
    active_rows = edited_df[edited_df["사용"] == True]  # noqa: E712
    ingredients = tuple(
        str(value).strip() for value in active_rows["재료명"].tolist() if str(value).strip()
    )
    priority = tuple(
        str(row["재료명"]).strip()
        for _, row in active_rows.iterrows()
        if bool(row["우선 소진"]) and str(row["재료명"]).strip()
    )
    excluded = tuple(
        item.strip()
        for item in excluded_text.replace("\n", ",").split(",")
        if item.strip()
    )

    if not ingredients:
        st.error("추천에 사용할 재료를 한 개 이상 입력해 주세요.")
    elif not foodsafety_key:
        st.error(
            "FOODSAFETY_API_KEY가 설정되지 않았습니다. README의 인증키 설정 방법을 따라 주세요."
        )
    else:
        preferences = UserPreferences(
            ingredients=ingredients,
            priority_ingredients=priority,
            excluded_ingredients=excluded,
            category=category,
            max_time_minutes=max_time if use_time_limit else None,
            high_protein=high_protein,
            low_sodium=low_sodium,
        )
        try:
            with st.spinner("식품안전나라 레시피를 불러오고 후보를 계산합니다..."):
                recipes = _load_recipes(foodsafety_key, api_base_url)
                st.session_state.recipe_count = len(recipes)
                ranked = rank_recipes(recipes, preferences, limit=30)

            if use_reranker and ranked:
                with st.spinner("BGE Reranker가 상위 후보를 정렬하고 있습니다..."):
                    top_candidates = ranked[:20]
                    reranker = _load_reranker()
                    semantic_scores = reranker.score(
                        build_reranker_query(preferences),
                        [recipe_document(item) for item in top_candidates],
                    )
                    reranked = apply_semantic_scores(top_candidates, semantic_scores)
                    ranked = reranked + ranked[20:]

            st.session_state.recommendations = ranked[:3]
            if not ranked:
                st.warning(
                    "조건에 맞는 레시피를 찾지 못했습니다. 제외 재료나 시간 조건을 완화해 보세요."
                )
            else:
                st.success("추천이 완료되었습니다.")
        except FoodSafetyAPIError as exc:
            st.error(str(exc))
        except Exception:
            st.error(
                "추천 과정에서 오류가 발생했습니다. Reranker를 끄거나 캐시를 새로고침한 뒤 다시 시도해 주세요."
            )

if st.session_state.recommendations:
    st.divider()
    st.markdown('<div class="step-label">STEP 04 · 추천 결과</div>', unsafe_allow_html=True)
    st.subheader("오늘의 저속노화 레시피")
    tabs = st.tabs(
        [f"#{index} {item.recipe.name}" for index, item in enumerate(st.session_state.recommendations, 1)]
    )
    for index, (tab, item) in enumerate(zip(tabs, st.session_state.recommendations, strict=True), 1):
        with tab:
            _render_recipe(index, item)

st.divider()
st.caption(
    "레시피·영양·조리 이미지 출처: 식품의약품안전처 식품안전나라 COOKRCP01 · "
    "저속노화 적합도와 조리시간은 프로젝트의 설명 가능한 휴리스틱이며 의료적 판단이 아닙니다."
)
st.markdown(
    "[식품안전나라 데이터활용서비스](https://www.foodsafetykorea.go.kr/api/openApiInfo.do?menu_grp=MENU_GRP31&menu_no=661&svc_no=COOKRCP01)"
)
