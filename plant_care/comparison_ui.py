"""정원 기록과 분리된 수동 AI 비교 실험 화면."""
import streamlit as st

from .ai_ui import api_key
from .comparison import CASES, SOURCE, demo_context, export_trial, new_trial, run_side
from .gemini import AnalysisError, analysis_context
from .media import prepare_photo
from .ui import heading
from .insight_ui import render_insight
from .private_media import photo as display_private_photo, download

LABELS = {"baseline": "기록 없이", "history": "기록 포함"}


def comparison_screen(store, plants, on_refresh=None):
    heading("COMPARE & LEARN", "기록이 있으면, 무엇이 달라질까요?", "같은 현재 상태에 과거 기록만 다르게 전달해 두 답변을 살펴보세요.")
    st.info("예시 사례로 지금 시작할 수 있어요. 이 실험은 기록 활용을 확인하며, 진단 정확도나 실제 식물의 회복 효과를 증명하지 않습니다.")
    with st.expander("비교 방법과 참고 자료"):
        st.write("두 분석은 같은 모델·지시문·현재 상태·사진을 사용합니다. 등록 메모는 모두 제외하고, 과거 물주기·관리·제안·경과만 포함 여부를 달리합니다. 날씨는 이번 비교에서 사용하지 않습니다.")
        st.caption("질문에 과거 관리를 적으면 '기록 없이' 조건에도 전달됩니다. 현재 모습과 질문만 적어 주세요. AI 응답은 같은 조건에서도 달라질 수 있어 한 번의 비교를 성능 결론으로 삼지 마세요.")
        st.markdown('[프로젝트·모델의 실제 요청 한도 확인](https://aistudio.google.com/rate-limit) · [429 원인별 안내](https://ai.google.dev/gemini-api/docs/api-errors?hl=ko)')
        st.markdown(f"가상 사례의 원예 참고: [메릴랜드대학교 실내 식물 문제 안내]({SOURCE}). 시듦은 물 부족과 과습 모두에서 나타날 수 있다는 설명을 바탕으로 구성했습니다. 사례 날짜·관리 기록은 가상이며 원문의 실제 사례가 아닙니다.")
    trial = st.session_state.get("comparison_trial")
    with st.expander("1 · 비교할 상황 준비", expanded=trial is None):
        mode = st.radio("사용할 자료", ["예시 사례", "내 식물 기록"], horizontal=True, key="comparison_mode")
        context = None
        photo = None
        source = {}
        if mode == "예시 사례":
            case = st.selectbox("가상 사례", list(CASES), format_func=lambda value: CASES[value][0], key="comparison_case")
            st.caption(CASES[case][1] + " · 사진 없음")
            context = demo_context(case)
            source = {"kind": "synthetic", "case": case, "reference": SOURCE}
            st.write(f"**같은 현재 질문:** {context['current_state']}")
            with st.expander("가정한 과거 기록 확인"):
                st.json({name: context[name] for name in ("last_watered", "recent_care_logs", "previous_suggestions")})
        elif not plants:
            st.info("실제 식물을 등록하면 내 기록으로도 비교할 수 있어요. 지금은 예시 사례를 선택해 주세요.")
        else:
            by_id = {p["id"]: p for p in plants}
            pid = st.selectbox("비교할 식물", list(by_id), format_func=lambda value: by_id[value]["name"], key="comparison_plant")
            question = st.text_area("현재 모습과 질문", max_chars=3000, placeholder="예: 잎이 처져 있어요. 무엇을 먼저 확인할까요?", key="comparison_question")
            upload = st.file_uploader("두 분석에 공통으로 사용할 현재 사진 (선택)", type=["jpg", "jpeg", "png", "webp"], key="comparison_photo")
            if question.strip():
                context = analysis_context(store, pid, question, upload is not None)
                photo = upload.getvalue() if upload is not None else None
                source = {"kind": "garden", "plant_name": by_id[pid]["name"]}
                if not context["recent_care_logs"] and not context["previous_suggestions"]:
                    st.warning("과거 기록이 없어 두 조건에 차이가 거의 없어요. 기록을 남기거나 예시 사례로 먼저 비교해 주세요.")
            st.caption("여기서 분석한 답변은 실제 관리 제안이나 정원 기록에 추가되지 않습니다.")
        st.caption("새 비교를 준비하면 현재 화면의 이전 실험을 교체합니다. 먼저 아래에서 비교 기록을 내려받아 주세요.")
        if st.button("새 비교 준비" if trial else "비교 준비", key="comparison_prepare", type="primary", disabled=context is None, width="stretch",
                     on_click=on_refresh if mode == "내 식물 기록" else None):
            try:
                photo = prepare_photo(photo) if photo is not None else None
                st.session_state["comparison_trial"] = new_trial(context, photo, source)
                st.session_state["comparison_consent"] = False
            except ValueError as error:
                st.error(str(error))
            else:
                st.rerun()
    trial = st.session_state.get("comparison_trial")
    if trial is None:
        return
    st.subheader("2 · 같은 상황, 두 번의 분석")
    st.caption(f"고정한 자료: {'가상 사례' if trial['source']['kind'] == 'synthetic' else trial['source']['plant_name']} · 모델 {trial['model']} · 사진 {'있음' if trial['photo'] is not None else '없음'}")
    st.write(f"**이번 비교의 질문:** {trial['inputs']['history']['current_state']}")
    with st.expander("고정한 입력 확인"):
        if trial["photo"] is not None:
            display_private_photo(trial["photo"], width=250, personal=getattr(store, 'personal', False))
        st.json(trial["inputs"])
    st.caption("아래 각 버튼은 Gemini에 한 번 요청합니다. 두 조건을 모두 누르면 총 2회이며, 무료 한도에서 차감되거나 결제 프로젝트에서 과금될 수 있습니다. 무료 구간 입력은 Google 제품 개선에 사용될 수 있어요.")
    consent = st.checkbox("고정한 식물 정보·질문·선택 사진과, 기록 포함 조건에서는 과거 관리·제안·경과를 Google Gemini로 보내는 데 동의합니다.", key="comparison_consent")
    key = api_key()
    if not key:
        st.info("Gemini API 키를 설정하면 비교 분석을 요청할 수 있어요.")
    with st.container(key="comparison_results"):
        columns = st.columns(2, gap="large")
        for side, column in zip(LABELS, columns):
            with column:
                st.subheader(LABELS[side])
                count = len(trial["inputs"][side].get("recent_care_logs", []))
                st.caption(f"과거 관리 {count}건 · 같은 현재 상태와 사진")
                if st.button(f"{LABELS[side]} 분석", key=f"compare_{side}", width="stretch", disabled=not key or not consent or side in trial["attempts"]):
                    try:
                        with st.spinner(f"{LABELS[side]} 분석을 요청하고 있어요…"):
                            run_side(trial, side, key, consent)
                    except (AnalysisError, ValueError) as error:
                        st.error(str(error))
                    # rerun으로 호출 버튼을 잠근다. 응답과 실패 모두 세션에 보관한다.
                    st.rerun()
                result = trial["results"].get(side)
                if result:
                    render_insight(result["result"], trial['inputs'][side], f"compare_{side}")
                    st.caption(f"응답 전체 토큰: {result['usage'].get('total_tokens', '정보 없음')}")
                elif side in trial["attempts"]:
                    if message := trial['attempts'][side].get('message'):
                        st.error(message)
                    st.warning("이 요청의 완료 응답을 받지 못했어요. 자동 재시도하지 않습니다. 다른 조건의 결과는 유지하며, 다시 요청하려면 새 비교를 준비해 주세요.")
                else:
                    st.caption("아직 분석을 요청하지 않았어요.")
    if len(trial["results"]) == 2:
        st.subheader("3 · 사람이 두 답변을 평가하기")
        st.caption("기록을 포함했다는 이유만으로 더 좋은 답변이라고 판단하지 마세요. 아래 평가는 사용자의 의견이며 자동 정확도 점수가 아닙니다.")
        with st.form(f"comparison_review_{trial['id']}"):
            ratings = {name: st.selectbox(label, ["판단 보류", "기록 없이", "비슷함", "기록 포함"], key=f"review_{trial['id']}_{name}")
                       for name, label in (("context", "과거 상황을 적절히 반영한 답변"), ("specificity", "확인할 조건과 행동이 구체적인 답변"), ("clarity", "이해하고 사용하기 쉬운 답변"))}
            notes = st.text_area("판단 이유·틀리거나 꾸며낸 내용", max_chars=3000)
            if st.form_submit_button("평가 남기기", width="stretch"):
                trial["assessment"] = {**ratings, "notes": notes}
                st.success("평가를 남겼어요. 아래에서 비교 기록을 내려받아 주세요.")
    st.divider()
    st.caption("실험은 현재 브라우저 세션에만 보관됩니다. 새로고침·접속 종료 전에 내려받아 주세요. 정원 전체 백업에는 포함되지 않습니다.")
    download(store, "비교 기록 내려받기", export_trial(trial), file_name=f"plant-care-comparison-{trial['id']}.json", mime="application/json", width="stretch")
    if trial["photo"] is not None:
        download(store, "비교에 사용한 사진 내려받기", trial["photo"], file_name=f"comparison-{trial['id']}.jpg", mime="image/jpeg")
