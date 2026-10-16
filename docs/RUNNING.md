# 실행·테스트·데이터 안내

이 문서는 내 PC에서 코드를 실행하는 개발자용입니다.
공유 앱만 사용하는 팀원은 설치·개인 API 키 없이 [팀원 안내](TEAM_TESTING.md)를 따라 접속하세요.
로컬 기본 정원과 공유 앱의 개인 정원은 자동 동기화되지 않습니다.

## 준비

- Python 3.12 권장. Python 3.12.14, Streamlit 1.65.0, Pillow 12.3.0에서 검증했습니다.
- Windows에서는 Python 설치 시 PATH 옵션을 켜거나 `py` 명령을 사용하세요.
- 이 폴더를 압축 해제하거나 GitHub에서 내려받으세요.

Git을 사용하는 경우 다음 명령으로 시작합니다.

```powershell
git clone https://github.com/Mhoyoung/plant-care-ai.git
cd plant-care-ai
```

## 실행 · Windows PowerShell

`app.py`가 있는 폴더에서 터미널을 열고 실행합니다.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
```

`py`가 없는 환경에서는 첫 줄을 `python -m venv .venv`로 바꾸세요.
가상환경 활성화는 필요하지 않습니다. 위 명령은 가상환경의 Python을 직접 사용합니다.

브라우저가 열리면 앱을 사용합니다. 자동으로 열리지 않으면 터미널에 표시되는 주소를 여세요.
기본 주소는 `http://localhost:8501`입니다. 종료할 때는 터미널에서 `Ctrl+C`를 누릅니다.

## 실행 · macOS / Linux

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m streamlit run app.py
```

## 첫 확인 순서

1. `몬스테라 A`라는 식물을 등록합니다.
2. 식물 상세의 **관리 기록** 탭에서 물주기 기록과 상태 메모를 저장합니다.
3. 같은 탭에서 `상태 관찰` 기록을 추가하고 경과를 `호전`, `변화 없음`, `악화` 중 하나로 남깁니다.
4. 타임라인에 날짜 순서대로 표시되는지 확인합니다.
5. 앱을 종료하고 다시 켠 뒤 식물과 기록이 유지되는지 확인합니다.
6. 다른 식물을 등록하고 각 식물의 기록이 섞이지 않는지 확인합니다.

식물이 등록된 뒤 다시 접속하면 **내 정원**이 열립니다. 카드를 누르면 해당 식물의 상세 화면으로 이동합니다.
**한눈에 보기**에서는 최근 기록과 저장한 AI 요약을, **AI 분석**에서는 새 분석과 이전 결과를 확인합니다.
화면 이동이나 탭 전환만으로 AI가 호출되지 않습니다. 사진 없는 식물은 예시 일러스트로 표시합니다.
AI 제안과 실제 실행·이후 관찰을 연결하는 사용 순서는 [관리 흐름 안내](CARE_LOOP.md)에 있습니다.

## 데이터와 사진

팀원용 앱은 [Supabase 외부 저장소 안내](CLOUD_STORAGE.md)에 따라 연결할 수 있습니다.
아래의 `data/` 위치와 폴더 복사 방법은 기본 로컬 모드 기준입니다.
앱 왼쪽 **기록 보관과 백업**에서 로컬·외부 모드 모두 사진을 포함한 전체 정원 ZIP을 내려받을 수 있습니다.

처음 실행할 때 아래 파일과 폴더가 만들어집니다.

```text
data/
  plants.db       식물 정보, 관리 기록, AI 분석과 당시 입력
  photos/         검증하고 크기를 줄인 사진
```

사진은 JPG, PNG, WEBP를 지원합니다. 파일당 10MB, 2,500만 화소 이하로 제한하고,
긴 변을 최대 1,600픽셀로 줄인 JPEG로 저장합니다. GPS 등 원본 메타데이터는 저장하지 않습니다.

JSON 다운로드에는 사진 내용이 포함되지 않습니다. 앱의 전체 정원 ZIP은 사진도 포함합니다.
로컬 모드에서 폴더로 백업하려면 앱을 종료한 뒤 `data/` 폴더를 복사하세요.
JSON 형식은 `schema_version: 2`이며, 기존 식물·관리 기록·분석과 함께 `ai_suggestions`를 포함합니다.
선택한 도시 ID는 `weather_region`, 분석 당시 날씨는 분석 입력의 `outdoor_weather`에 포함됩니다. [날씨 안내](WEATHER.md)
앱 시작 시 기존 DB에 제안 테이블과 관리 기록의 연결 필드를 추가합니다. 이전 분석의 원문·당시 입력과 기존 기록은 유지합니다.
기존 관리 기록을 임의로 제안의 실행으로 연결하지 않습니다. 업데이트 전에는 앱을 종료하고 `data/`를 복사해 두세요.
저장 위치를 바꾸려면 실행 전에 `PLANT_CARE_DATA_DIR` 환경변수에 폴더 경로를 설정하세요.

로컬 모드는 자기 PC에 별도의 정원을 보관합니다. 공유 앱은 Supabase DB·비공개 사진 저장소를 사용하며
이메일·비밀번호 로그인과 사용자별 RLS로 개인 정원을 구분합니다. 실제 설정·메일 조건은 [계정 안내](ACCOUNTS.md)를 확인하세요.
공유 서버에 로컬 모드로 배포하면 임시 디스크의 기록은 재시작·재배포 후 보관이 보장되지 않습니다.
관리 기록의 오늘 날짜와 제안 날짜는 한국 시간(Asia/Seoul)을 기준으로 합니다.

## 코드 구조

```text
app.py                     Streamlit 화면
assets/                    정원 스타일과 식물 일러스트
plant_care/
  ui.py                    식물 카드·요약·타임라인 표시
  constants.py             관리 종류와 경과 값
  storage.py               SQLite 저장과 조회
  media.py                 사진 검증과 저장
  ai_context.py            최근 기록을 AI 입력으로 구성
  gemini.py                Gemini REST 요청과 응답 검증
  ai_ui.py                 분석 폼과 결과 화면
  care_ui.py               AI 제안 실행과 이후 관찰 연결
  insight_ui.py            새싹 안내·확인 카드·전체 분석 표시
  comparison.py            기록 제외/포함 비교 실험
  comparison_ui.py         비교 준비·호출·평가·다운로드 화면
  cloud_store.py           Supabase 팀 정원·비공개 사진
  store_factory.py         저장소 선택
  snapshot.py              전체 정원 ZIP 백업·복원
  data_ui.py               백업·이전 화면
  weather.py               지역 실외 모델 날씨
  weather_ui.py            도시 설정과 날씨 표시
  time_utils.py            한국 기준 오늘 날짜
tests/                     저장소와 화면 동작 검증
requirements.txt           필요한 외부 라이브러리
docs/ROADMAP.md             단계별 개발 계획
.gitignore                 개인 데이터와 비밀키 업로드 제외
.streamlit/config.toml      화면 색상과 사진 크기 설정
```

SQLite와 `unittest`는 Python 기본 라이브러리입니다. 별도 DB 서버나 유료 API 키 없이 시작할 수 있습니다.
Gemini 분석에 필요한 무료 구간·키 설정은 [AI 안내](AI_SETUP.md)를 참고하세요.
화면 코드와 저장·AI 입력 코드를 분리해두어, 나중에 모바일 화면과 Python API 서버로 확장하기 쉽게 구성했습니다.

## 테스트

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

테스트는 임시 폴더를 사용합니다. 실제 `data/` 폴더에 예시 식물이나 테스트 사진을 추가하지 않습니다.
API는 모의 응답을 사용합니다. 실제 AI 요청이나 과금 없이 실행됩니다.

## 수정한 코드를 GitHub에 올리기

GitHub에는 코드, 이 README, 라이브러리 목록과 테스트를 올립니다.
개인 기록, 사진, DB 파일, API 비밀키는 `.gitignore`로 제외합니다.

위 `git clone` 명령으로 내려받은 폴더에서 코드를 수정한 뒤 실행합니다.

```powershell
git add .
git commit -m "Update plant care app"
git push
```

처음 push할 때 GitHub 로그인이 필요할 수 있습니다. 비밀번호나 토큰을 코드에 넣지 마세요.
ZIP 다운로드에는 Git 이력이 없습니다. 변경 이력을 관리하려면 `git clone` 방식으로 내려받으세요.
GitHub 업로드는 코드 보관입니다. 웹 앱을 다른 사람이 사용할 수 있게 배포하는 작업은 별도입니다.

## 다음 개발

우선 등록·기록·재조회 흐름을 직접 확인하세요. 이후 순서는 [개발 계획](ROADMAP.md)을 참고하세요.

기술 참고: [Streamlit](https://docs.streamlit.io/), [Python SQLite](https://docs.python.org/3/library/sqlite3.html),
[GitHub 저장소 생성](https://docs.github.com/en/repositories/creating-and-managing-repositories/creating-a-new-repository).
