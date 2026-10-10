"""분석 요청과 저장된 결과 화면."""

import os
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st

from .gemini import AnalysisError, MODEL, analysis_context, analyze


def api_key() -> str:
    if value := os.environ.get("GEMINI_API_KEY", "").strip():
        return value
    try:
        return str(st.secrets.get("GEMINI_API_KEY", "")).strip()
    except (FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
        return ""


def render_analysis(store, plant):
    st.subheader("AI 분석")
    key = api_key()
    if not key:
        st.info("Gemini API 키를 설정하면 분석을 사용할 수 있어요. 키는 .streamlit/secrets.toml에 입력하세요.")
    st.caption("현재 상태와 최근 관리 기록 최대 30건, 선택한 사진 1장을 Google Gemini로 보냅니다. "
               "무료 구간 데이터는 Google 제품 개선에 사용될 수 있어요.")
    st.caption("무료 사용은 AI Studio의 Free Tier 프로젝트에서 설정해 주세요. "
               "앱은 결제 상태를 확인할 수 없으며, 결제를 연결한 프로젝트의 키는 과금될 수 있어요.")
    st.caption(f"사용 모델: {MODEL} · 버튼을 누를 때만 호출")
    with st.form(f"analysis_{plant['id']}"):
        state = st.text_area("지금 상태와 궁금한 점", max_chars=3000,
                             placeholder="예: 잎이 처져 있어요. 물을 더 줘야 할까요?", key="ai_state")
        photo = st.file_uploader("분석할 현재 사진 (선택)", type=["jpg", "jpeg", "png", "webp"], key="ai_photo")
        use_registered = st.checkbox("새 사진이 없으면 등록 사진 함께 보내기", value=False, key="ai_use_registered",
                                       disabled=not bool(plant["photo_path"]))
        consent = st.checkbox("위 내용을 확인했고, 선택한 사진과 기록을 Google로 보내 분석합니다.", key="ai_consent")
        submit = st.form_submit_button("Gemini로 분석", disabled=not bool(key))
    if submit:
        if not consent:
            st.error("사진과 기록 전송 안내를 확인하고 체크해 주세요.")
        elif not state.strip():
            st.error("지금 상태나 궁금한 점을 입력해 주세요.")
        else:
            try:
                image = photo.getvalue() if photo is not None else (
                    store.photo_path(plant["photo_path"]).read_bytes() if use_registered and plant["photo_path"] else None
                )
                context = analysis_context(store, plant["id"], state, image is not None)
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

    analyses = store.list_analyses(plant["id"])
    st.caption(f"저장된 분석 {len(analyses)}건 · AI 제안은 실제 관리 기록과 구분해서 보관합니다.")
    for index, analysis in enumerate(analyses):
        timestamp = datetime.fromisoformat(analysis["created_at"]).astimezone(ZoneInfo("Asia/Seoul"))
        with st.expander(f"{timestamp:%Y-%m-%d %H:%M} · {analysis['model']}", expanded=index == 0):
            result = analysis["result"]
            st.write(result["summary"])
            for field, label in (("observations", "참고한 관찰"), ("checks", "먼저 확인할 것"), ("actions", "관리 제안")):
                st.write(f"**{label}**")
                for item in result[field]:
                    st.write(f"• {item}")
            st.caption(result["uncertainty"])
            st.write(f"분석 당시 질문: {analysis['input']['current_state']}")
            if analysis["photo_path"]:
                st.image(str(store.photo_path(analysis["photo_path"])), width=320)
            st.caption(f"참고 기록 {len(analysis['input']['recent_care_logs'])}건 · "
                       f"응답에 포함된 전체 토큰: {analysis['usage'].get('total_tokens', '정보 없음')}")
