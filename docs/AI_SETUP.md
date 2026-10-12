# Gemini 분석 설정

식물 등록과 관리 기록은 키 없이 사용할 수 있습니다. **실제 AI 분석에는 본인의 Gemini API 키가 필요합니다.**
현재 기본 모델은 `gemini-3.8-flash`이며, 공식 요금표에서 Standard Free Tier를 확인했습니다(2026-10-11).
무료 구간의 한도와 모델 제공 여부는 바뀔 수 있으므로 AI Studio의 프로젝트 표시를 확인하세요.

## 1. 무료 프로젝트와 API 키 준비

1. [Google AI Studio의 API Keys](https://aistudio.google.com/apikey)를 열고 본인 Google 계정으로 로그인합니다.
2. 프로젝트를 선택하거나 만들고 **Create API key**로 키를 발급합니다. 약관 확인이나 계정 인증은 본인이 진행합니다.
3. 해당 프로젝트가 **Free Tier**인지 확인합니다. 무료로 시작하려면 결제 계정을 연결하거나 유료 구간으로 업그레이드하지 마세요.
4. 키는 채팅, Issue, PR, README에 붙이지 않습니다. 다음 단계에서 내 PC의 로컬 파일에만 입력합니다.

학교 계정이 AI Studio 사용을 제한한다면 계정 관리자에게 허용 여부를 확인해야 합니다.

## 2. 내 PC에 키 설정

`app.py` 폴더에서 Windows PowerShell을 열고 실행합니다.

```powershell
Copy-Item .streamlit/secrets.toml.example .streamlit/secrets.toml
notepad .streamlit/secrets.toml
```

이미 키 파일이 있다면 복사하지 않고 편집만 합니다. 아래 빈 따옴표 안에 키를 붙이고 저장합니다.

```toml
GEMINI_API_KEY = ""
```

키를 설정한 뒤 실행 중인 앱을 종료(`Ctrl+C`)하고 다시 실행합니다.

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

환경변수 `GEMINI_API_KEY`도 지원하며, 설정되어 있으면 파일보다 먼저 사용합니다.
`.streamlit/secrets.toml`은 Git에서 제외되지만, 본인 PC에서는 키를 포함한 파일이므로 따로 공유하지 마세요.

## 3. 분석 사용

1. 내 정원에서 식물 카드를 열고 **AI 분석** 탭을 선택합니다.
2. **지금 상태와 궁금한 점**을 입력합니다.
3. 필요하면 현재 사진 1장을 올립니다. 새 사진이 없을 때 등록 사진을 보내려면 별도로 체크합니다.
4. 전송 안내를 확인하고 **Gemini로 분석**을 누릅니다.

입력은 선택한 식물의 기본 정보, 마지막 물주기, 최근 관리 기록 최대 30건, 최근 이전 제안 최대 10건과 각 제안의 실행·최근 경과 최대 3건, 현재 질문, 선택 사진입니다.
지역을 저장하고 날씨 포함을 선택하면 도시의 실외 모델 날씨·시각·출처도 함께 보냅니다. [지역 날씨 설정](WEATHER.md)
과거 사진 전체나 다른 식물의 기록은 보내지 않습니다. 사진은 검증·축소하고 GPS 등 메타데이터를 제거한 JPEG로 전달합니다.
결과는 상태 요약, 참고 관찰, 확인할 사항, 관리 제안, 불확실성으로 표시합니다.
분석 당시 입력·사진과 결과·모델·시간·응답에 포함된 토큰 정보를 SQLite에 보관합니다.
JSON 다운로드에도 분석 결과와 제안·실행·경과 연결이 포함됩니다.
**관리 기록 남기기**에서 실제로 한 관리를 저장한 뒤, **이후 상태 남기기**로 경과를 기록하세요.
다음 분석에서는 이 연결 정보를 참고합니다. [관리 흐름 안내](CARE_LOOP.md)

## 무료 사용과 오류

- 앱은 Google 프로젝트의 결제 상태를 확인하거나 바꾸지 않습니다. 결제를 연결한 키를 쓰면 호출에 비용이 생길 수 있습니다.
- 분석 버튼을 누를 때 한 번 요청합니다. 앱 새로고침이나 기록 조회만으로 호출하지 않습니다.
- 요청 한도 오류(`429`)의 응답 코드가 있으면 원인별로 안내합니다. `rate_limit_exceeded`는 분당·초당 요청/토큰, `quota_exceeded`는 일일 할당량, `too_many_requests`는 단기간 요청 집중입니다. 코드가 없으면 원인을 확정하지 않습니다. 자동 재시도나 다른 모델 전환은 없습니다.
- 실패하거나 형식이 잘못된 응답은 분석 결과로 저장하지 않습니다. 오류 안내에 키나 API 원문 오류를 표시하지 않습니다.
- 응답 대기는 최대 45초입니다. 시간 초과 시 Google 쪽에서 요청이 처리됐을 수도 있습니다. 자동으로 다시 호출하지 않습니다.
- Free Tier의 입력·출력은 Google 제품 개선에 사용될 수 있습니다. 얼굴, 개인정보가 보이는 사진과 민감한 메모는 입력하지 마세요.
- `store: false`는 Interactions의 후속 조회용 저장을 끄는 설정입니다. 무료 구간의 데이터 이용 정책을 바꾸지는 않습니다.
- 흙의 수분과 실내 환경을 사진만으로 확정할 수 없습니다. 제안에 적힌 확인 조건을 먼저 살펴보세요.

**현재 검증 범위:** API 응답을 모의한 테스트로 요청 형식, 이미지 처리, 오류·한도 처리, 저장·재조회, 중복 호출 방지를 확인했습니다.
제안·실행·경과를 다음 요청과 당시 입력에 포함하는 흐름도 모의 API로 검증했습니다.
실제 API의 연결·분석 품질·사용 가능한 무료 한도는 본인 키로 확인해야 합니다. 모의 응답을 사용자 데이터에 AI 결과로 저장하지 않습니다.

## 실제 한도 확인

[AI Studio의 활성 한도](https://aistudio.google.com/rate-limit)에서 **앱 키를 발급한 프로젝트**와 **gemini-3.8-flash**를 확인합니다.
RPM(분당 요청), TPM(분당 입력 토큰), RPD(일일 요청) 중 하나만 초과해도 제한될 수 있습니다.
한도는 키별이 아니라 프로젝트별이며 모델·사용 등급·계정 상태에 따라 달라집니다. 같은 프로젝트에서 키를 새로 만들어도 한도가 분리되지 않습니다.
일일 요청 한도는 Google 공식 문서의 태평양 시간 자정 기준으로 재설정되므로 한국 자정이라고 가정하지 않습니다.
분당 제한과 단기간 요청 집중은 대기 후 수동으로 다시 시도하고, 일일 할당량은 사용량과 재설정을 확인합니다.
원인을 확인하지 못한 429는 무료 한도 소진으로 단정하거나 결제 전환을 권하지 않습니다.
앱은 허용한 오류 코드와 숫자로 된 Retry-After 초만 읽고, 원문 메시지·프로젝트 정보·키는 화면/DB/비교 파일에 남기지 않습니다.
Retry-After는 서버가 안내한 대기 시간이며 그 후 성공을 보장하지 않습니다. 이전 오류에서 상세 코드를 저장하지 않았다면 원인을 소급해 알아낼 수 없습니다.

공식 참고: [요청 한도](https://ai.google.dev/gemini-api/docs/rate-limits?hl=ko) · [Interactions 오류 코드와 응답 형식](https://ai.google.dev/gemini-api/docs/api-errors?hl=ko)

## 학교의 ChatGPT Pro 지원

ChatGPT Pro 구독과 일반 OpenAI API 사용 요금은 별도입니다. Pro를 지원받으면 ChatGPT에서 직접 사진을 검토하거나 개발 도움을 받을 수 있지만,
이 앱의 일반 OpenAI API 호출 비용이 그 구독에 포함되는 것은 아닙니다. 학교가 앱의 GPT 호출도 지원하려면 별도의 API 프로젝트·크레딧 예산을 확인해야 합니다.

공식 자료: [Google API 키](https://ai.google.dev/gemini-api/docs/api-key) · [Gemini 요금](https://ai.google.dev/gemini-api/docs/pricing) ·
[요청 한도](https://ai.google.dev/gemini-api/docs/rate-limits) · [Interactions REST API](https://ai.google.dev/api/interactions-api) ·
[이미지 입력](https://ai.google.dev/gemini-api/docs/image-understanding) · [구조화된 출력](https://ai.google.dev/gemini-api/docs/structured-output) ·
[OpenAI 구독과 API 안내](https://learn.chatgpt.com/docs/pricing)
