# 저속노화를 위한 냉장고를 부탁해

냉장고 사진에서 식재료를 인식하고, 사용자가 인식 결과를 교정한 뒤 식품의약품안전처 식품안전나라의 `COOKRCP01` 레시피 중 조건에 맞는 메뉴 3개를 추천하는 Streamlit 데모입니다.

레시피를 미리 JSON 파일로 저장하지 않습니다. 앱이 식품안전나라 API에서 최신 데이터를 불러와 6시간 동안 메모리에만 캐시합니다.

## 주요 기능

- `Qwen/Qwen3-VL-8B-Instruct`를 이용한 냉장고 재료 인식
- 낮은 신뢰도 재료의 사용자 확인, 추가, 삭제
- 우선 소진 재료와 제외·알레르기 재료 입력
- 식품안전나라 `COOKRCP01` 실시간 연동
- 재료 일치도, 장보기 부담, 영양, 조리 편의성 기반 설명 가능한 점수
- 열량, 탄수화물, 단백질, 지방, 나트륨 표시
- 최대 20단계 조리법과 단계별 이미지 표시
- 인증키가 없어도 가능한 수동 재료 입력 UI

## 전체 흐름

```text
냉장고 사진
  → Qwen3-VL 8B 재료 추출
  → 사용자 확인 및 교정
  → 식품안전나라 레시피 실시간 로드
  → 제외 재료 강제 필터
  → 구조화 점수 계산
  → 상위 3개 레시피와 조리법 출력
```

## 사용 데이터와 모델

### 식품안전나라 레시피 API

- 서비스 ID: `COOKRCP01`
- 공식 문서: <https://www.foodsafetykorea.go.kr/api/openApiInfo.do?menu_grp=MENU_GRP31&menu_no=661&svc_no=COOKRCP01>
- 제공 항목: 메뉴명, 재료, 1인분 영양정보, 조리법, 완성 이미지, 단계별 이미지, 저감 조리 팁
- 출처 표시 조건으로 상업적·비상업적 이용과 2차적 저작물 작성 가능

### VLM

- 모델: <https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct>
- 실행: Hugging Face Inference Providers
- 역할: 사진에서 보이는 식재료만 JSON으로 추출

## 프로젝트 구조

```text
.
├── app.py
├── src/
│   ├── foodsafety_client.py   # COOKRCP01 호출과 페이지 처리
│   ├── ingredients.py         # 한영 재료명 정규화와 동의어
│   ├── models.py              # 레시피와 추천 결과 모델
│   ├── ranking.py             # 필터와 설명 가능한 추천 점수
│   ├── time_estimator.py      # 조리 문장의 시간 표현 추출
│   └── vlm_client.py          # Qwen3-VL 호출과 JSON 검증
├── tests/
├── requirements.txt
└── .streamlit/
    ├── config.toml
    └── secrets.toml.example
```

## 준비 사항

- Python 3.11 권장
- 발급받은 식품안전나라 Open API 인증키
- VLM을 사용할 경우 Hugging Face 사용자 토큰과 Inference Providers 사용 가능 크레딧

API 인증키와 Hugging Face 토큰을 Git, README, 스크린샷 또는 메신저에 노출하지 마세요.

## 로컬 실행

### 1. 가상환경 만들기

macOS 또는 Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Windows PowerShell:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
```

### 2. 기본 의존성 설치

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

기본 설치에는 무거운 로컬 모델이 포함되지 않습니다. Qwen3-VL은 Hugging Face의 원격 추론을 사용합니다.

### 3. 인증키 설정

`.streamlit/secrets.toml.example`을 참고해 `.streamlit/secrets.toml` 파일을 만듭니다.

macOS 또는 Linux에서는 먼저 예제 파일을 복사할 수 있습니다.

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```

그다음 복사한 파일을 열어 아래 값을 실제 키로 교체합니다.

```toml
FOODSAFETY_API_KEY = "발급받은_식품안전나라_인증키"
HF_TOKEN = "hf_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"

VLM_MODEL = "Qwen/Qwen3-VL-8B-Instruct"
FOODSAFETY_API_BASE_URL = "https://openapi.foodsafetykorea.go.kr/api"
```

- `FOODSAFETY_API_KEY`는 추천 기능에 필수입니다.
- `HF_TOKEN`이 없으면 사진 분석 버튼이 비활성화되지만 재료를 직접 입력해 나머지 흐름을 사용할 수 있습니다.
- 앱은 인증키가 포함된 전체 요청 URL을 오류 메시지나 로그로 출력하지 않습니다.

환경변수로도 설정할 수 있습니다.

```bash
export FOODSAFETY_API_KEY="발급받은_인증키"
export HF_TOKEN="hf_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
```

### 4. 앱 실행

```bash
streamlit run app.py
```

브라우저가 자동으로 열리지 않으면 다음 주소로 접속합니다.

```text
http://localhost:8501
```

### 5. 앱 사용 순서

1. 냉장고 사진을 올리고 `Qwen3-VL 8B로 재료 찾기`를 누릅니다.
2. 인식된 재료를 확인하고 잘못된 항목을 수정하거나 삭제합니다.
3. 빨리 사용해야 할 재료에 `우선 소진`을 체크합니다.
4. 제외 재료, 요리 종류, 단백질·나트륨 선호를 입력합니다.
5. `오늘의 레시피 3개 추천`을 누릅니다.
6. 추천 근거와 영양정보를 확인하고 `재료와 조리법 보기`를 엽니다.

## 테스트

```bash
pip install -r requirements-dev.txt
pytest -q
```

테스트는 실제 인증키나 네트워크 없이 다음을 검증합니다.

- 식품안전나라 응답 파싱과 페이지 처리
- 조리 단계와 이미지 URL 변환
- 재료 동의어와 제외 재료 필터
- 영양·재료 기반 순위 계산
- 조리 시간 표현 추출
- VLM JSON 파싱과 잘못된 응답 처리
- 인증키가 없는 상태에서의 Streamlit 화면 기동

## 추천 점수

```text
구조화 점수 =
0.35 × 냉장고 재료 일치율
+ 0.15 × 추가 장보기 부담
+ 0.15 × 우선 소진 재료 활용도
+ 0.25 × 저속노화 식사 적합도
+ 0.10 × 조리 편의성
```

저속노화 식사 적합도는 식품안전나라의 단백질·나트륨 값과 재료 문자열에서 확인되는 통곡물·콩류·채소를 사용합니다. 식이섬유, 첨가당, 포화지방처럼 API가 제공하지 않는 영양값은 만들어내지 않습니다.

## 데이터 처리 방식

- API 한 번의 최대 요청 건수인 1000개 단위로 자동 페이지 처리합니다.
- 첫 로드 이후 결과를 Streamlit 메모리에 6시간 캐시합니다.
- 레시피 응답을 JSON 파일이나 DB로 저장하지 않습니다.
- 사이드바의 `레시피 메모리 캐시 새로고침`으로 즉시 다시 받을 수 있습니다.
- 제외·알레르기 재료는 점수가 아니라 추천 후보에서 먼저 제거합니다.
- 명시적인 조리 시간이 없으면 시간을 임의 생성하지 않고 `시간 정보 없음`으로 표시합니다.

## 문제 해결

### 식품안전나라 연결 실패

1. 인증키가 `COOKRCP01` 서비스에 승인되었는지 확인합니다.
2. 키 앞뒤에 공백이 없는지 확인합니다.
3. 사이드바에서 캐시를 새로고침합니다.
4. 공식 문서 환경에서 HTTPS가 지원되지 않는 경우에만 다음 값을 시험할 수 있습니다.

```toml
FOODSAFETY_API_BASE_URL = "http://openapi.foodsafetykorea.go.kr/api"
```

HTTP는 인증키가 암호화되지 않은 채 전송될 수 있으므로 로컬 시험 외에는 권장하지 않습니다.

### Qwen3-VL 호출 실패

- `HF_TOKEN` 권한과 잔여 Inference Providers 크레딧을 확인합니다.
- 모델 페이지에서 현재 제공자가 활성화되어 있는지 확인합니다.
- 사진을 15MB 이하 JPG 또는 PNG로 다시 올립니다.
- VLM이 없어도 직접 재료 입력으로 추천 기능을 시험할 수 있습니다.

### 추천 결과가 없음

- 제외 재료를 줄입니다.
- 시간 제한을 끕니다. `COOKRCP01`에는 총 조리 시간이 없어 조리 문장의 시간 표현으로만 추정합니다.
- 냉장고 재료를 `계란` 대신 `달걀`처럼 일반적인 이름으로 수정합니다. 기본 동의어는 자동 처리됩니다.

## 현재 한계

- 냉장고 사진에서 가려진 식품과 정확한 수량·유통기한을 신뢰성 있게 알 수 없습니다.
- 식품안전나라 API에는 식이섬유, 첨가당, 포화지방과 알레르기 라벨이 없습니다.
- 총 조리 시간이 별도 필드로 제공되지 않아 조리법 문장에서 명시된 시간만 합산합니다.
- 추천 점수는 설명 가능한 데모 휴리스틱이며 의료적 진단이나 노화 속도 측정값이 아닙니다.

## 출처

레시피, 영양정보, 조리법 및 이미지는 식품의약품안전처 식품안전나라 `COOKRCP01` 데이터를 사용합니다. 앱 결과 하단에도 출처 링크를 표시합니다.
