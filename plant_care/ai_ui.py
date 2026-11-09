"""분석 요청과 저장된 결과 화면."""

import os
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st

from .gemini import AnalysisError, MODEL, analysis_context, analyze
from .ui import display_photo
from .weather import REGIONS, WeatherError, fetch_weather, unavailable_weather
from .weather_ui import region_settings, show_weather
from .insight_ui import render_insight


def api_key() -> str:
    if value := os.environ.get("GEMINI_API_KEY", "").strip():
        return value
    try:
        return str(st.secrets.get("GEMINI_API_KEY", "")).strip()
    except (FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
        return ""


def render_analysis(store, plant, on_refresh=None):
    analyses = store.list_analyses(plant["id"])
    with st.container(key="analysis_workspace"):
        st.html('<section class="analysis-intro" aria-label="AI 분석 안내">'
                '<span class="analysis-label">AI 식물 파트너</span>'
                '<h3>지금 모습, 함께 살펴볼까요?</h3>'
                '<p>사진과 쌓인 기록에서 다음에 확인할 일을 찾아요.</p>'
                '<ol class="analysis-steps" aria-label="분석 순서">'
                '<li><span>1</span>상태 입력</li><li><span>2</span>전송 확인</li>'
                '<li><span>3</span>결과 살펴보기</li></ol></section>')
        with st.container(key="analysis_draft"), st.expander("새 AI 분석 요청", expanded=not analyses):
            _analysis_request(store, plant, on_refresh)
        _analysis_history(store, plant)


def _analysis_request(store, plant, on_refresh):
    region = region_settings(store, plant['id'])
    key = api_key()
    if not key:
        st.info("AI 분석 연결을 준비 중이에요. 관리자에게 연결 설정을 확인해 달라고 요청해 주세요.")
    with st.form(f"analysis_{plant['id']}"):
        st.html('<div class="analysis-form-heading">현재 상태와 사진</div>'
                '<p class="analysis-form-hint">잎·흙·최근 변화 중 직접 확인한 내용을 알려주세요. 사진은 선택이에요.</p>')
        left, right = st.columns([1.2, 1], gap="medium")
        with left:
            state = st.text_area("지금 상태와 궁금한 점", max_chars=3000, height=145,
                             placeholder="예: 잎이 처져 있어요. 물을 더 줘야 할까요?", key="ai_state")
        with right:
            photo = st.file_uploader("분석할 현재 사진 (선택)", type=["jpg", "jpeg", "png", "webp"], key="ai_photo")
            use_registered = st.checkbox("새 사진이 없으면 등록 사진 함께 보내기", value=False, key="ai_use_registered",
                                       disabled=not bool(plant["photo_path"]))
        include_weather = st.checkbox('선택한 지역의 실외 날씨 함께 참고', value=False,
                                      key=f'ai_weather_{plant["id"]}', disabled=region is None)
        if region:
            st.caption(f'{REGIONS[region][0]}의 대표 좌표로 Open-Meteo에 날씨를 요청하고, 받은 날씨를 Gemini 분석에 포함합니다.')
        else:
            st.caption('날씨도 참고하려면 위의 지역 설정을 펼쳐 도시를 저장해 주세요.')
        st.html('<div class="analysis-confirm-heading">전송 전에 확인해 주세요</div>')
        st.caption('입력한 상태·관리 기록·이전 제안과 경과를 Google Gemini로 보냅니다. 사진과 날씨는 선택한 경우에만 포함해요.')
        with st.expander("분석에 사용하는 정보와 무료 구간 안내"):
            st.caption("현재 상태와 최근 관리 기록 최대 30건, 이전 제안 최대 10건과 각 제안의 최근 경과 3건, 선택한 사진 1장을 Google Gemini로 보냅니다. "
                       "선택한 경우 지역 실외 날씨도 함께 보냅니다. 무료 구간 데이터는 Google 제품 개선에 사용될 수 있어요.")
            st.caption("무료 사용은 AI Studio의 Free Tier 프로젝트에서 설정해 주세요. "
                       "앱은 결제 상태를 확인할 수 없으며, 결제를 연결한 프로젝트의 키는 과금될 수 있어요.")
            st.caption(f"사용 모델: {MODEL} · 버튼을 누를 때만 호출")
            st.markdown('[프로젝트·모델의 실제 요청 한도 확인](https://aistudio.google.com/rate-limit) · [429 원인별 안내](https://ai.google.dev/gemini-api/docs/api-errors?hl=ko)')
        consent = st.checkbox("사진·식물 기록과 선택한 날씨를 Google로 보내 분석하는 데 동의해요.", key="ai_consent")
        submit = st.form_submit_button("Gemini로 분석", type="primary", disabled=not bool(key), width="stretch", on_click=on_refresh)
    if submit:
        if not consent:
            st.error("사진과 기록 전송 안내를 확인하고 체크해 주세요.")
        elif not state.strip():
            st.error("지금 상태나 궁금한 점을 입력해 주세요.")
        else:
            try:
                image = photo.getvalue() if photo is not None else (
                    store.read_photo(plant["photo_path"]) if use_registered and plant["photo_path"] else None
                )
                weather = None
                if include_weather and region:
                    try:
                        with st.spinner('분석에 참고할 실외 날씨를 확인하고 있어요…'):
                            weather = fetch_weather(region)
                    except WeatherError as error:
                        st.warning(f'{error} 이번에는 사진과 기록으로만 분석합니다.')
                        weather = unavailable_weather(region)
                context = analysis_context(store, plant["id"], state, image is not None, weather)
                with st.spinner("사진과 관리 기록을 분석하고 있어요…"):
                    result, usage = analyze(key, context, image)
                try:
                    store.add_analysis(plant["id"], MODEL, context, result, usage, image)
                except (ValueError, OSError, sqlite3.Error):
                    st.error("분석은 완료됐지만 저장하지 못했어요. 아래 결과를 복사해 두세요.")
                    st.json(result)
                else:
                    st.success("분석 결과를 저장했어요.")
            except (AnalysisError, ValueError) as error:
                st.error(str(error))
            except OSError:
                st.error("분석할 사진을 읽지 못했어요. 사진 파일을 확인해 주세요.")



def _analysis_history(store, plant):
    analyses = store.list_analyses(plant["id"])
    suggestions = store.list_suggestions(plant["id"])
    with st.container(key="analysis_history"):
        st.html('<div class="analysis-history-heading"><h3>쌓아둔 AI 관찰</h3>'
                f'<span>{len(analyses)}건</span></div>')
        st.caption("저장 당시의 관찰이에요. AI 제안과 실제로 한 관리 기록은 구분해서 보관해요.")
        if not analyses:
            st.html('<div class="analysis-empty"><b>아직 저장된 AI 관찰이 없어요</b>'
                    '<p>현재 상태를 입력하고 분석하면<br>이 식물의 관찰을 여기에서 이어볼 수 있어요.</p></div>')
        for index, analysis in enumerate(analyses):
            _saved_analysis(store, analysis, index, suggestions)


def _saved_analysis(store, analysis, index, suggestions):
    timestamp = datetime.fromisoformat(analysis["created_at"]).astimezone(ZoneInfo("Asia/Seoul"))
    with st.expander(f"{timestamp:%Y.%m.%d %H:%M} · {'최근 관찰' if index == 0 else '지난 관찰'}", expanded=index == 0):
        result = analysis["result"]
        render_insight(result, analysis['input'], f"analysis_{analysis['id']}", store=store,
                       suggestions=[s for s in suggestions if s['analysis_id'] == analysis['id']])
        if weather := analysis['input'].get('outdoor_weather'):
            with st.expander('분석 당시 참고한 지역 날씨'):
                show_weather(weather)
        with st.expander("분석 당시 기록·사진 보기"):
            st.write(f"분석 당시 질문: {analysis['input']['current_state']}")
            previous = analysis["input"].get("previous_suggestions", [])
            st.caption(f"분석 당시 참고한 이전 제안 {len(previous)}건 · 실행과 경과를 구분해 반영")
            if previous:
                st.json(previous)
            if analysis["photo_path"]:
                display_photo(store, analysis['photo_path'], width=320)
            st.caption(f"참고 기록 {len(analysis['input']['recent_care_logs'])}건 · 모델 {analysis['model']} · "
                       f"응답에 포함된 전체 토큰: {analysis['usage'].get('total_tokens', '정보 없음')}")
