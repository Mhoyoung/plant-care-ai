"""AI 제안, 실제 실행, 이후 관찰을 연결하는 화면."""
from datetime import date, datetime
import sqlite3
from zoneinfo import ZoneInfo

import streamlit as st

from .constants import CARE_TYPES, OUTCOMES
from .time_utils import today_in_seoul

MODES = ["일반 기록", "AI 제안 실행", "실행 후 경과"]
RESULT_LABELS = {"unrecorded": "아직 모르겠어요", "improved": "좋아졌어요",
                 "unchanged": "비슷해요", "worse": "나빠졌어요"}


def open_care(plant_id, suggestion_id, mode):
    st.session_state[f"plant_tabs_{plant_id}"] = "관리 기록"
    st.session_state[f"care_mode_{plant_id}"] = mode
    st.session_state[f"care_suggestion_{plant_id}"] = suggestion_id
    change_care_mode(plant_id)


def change_care_mode(plant_id):
    mode = st.session_state[f"care_mode_{plant_id}"]
    st.session_state["care_kind"] = None if mode == MODES[1] else ("observation" if mode == MODES[2] else "watering")
    st.session_state["care_notes"] = ""
    st.session_state["care_date"] = today_in_seoul()
    st.session_state["care_outcome"] = "unrecorded"


def suggested_date(suggestion):
    return datetime.fromisoformat(suggestion["suggested_at"]).astimezone(ZoneInfo("Asia/Seoul")).date()


def suggestion_card(store, suggestion, prefix):
    """실제 기록에 근거한 상태와 다음 기록 버튼. AI를 호출하지 않는다."""
    with st.container(border=True):
        st.write(suggestion["suggestion_text"])
        execution = suggestion["execution"]
        if not execution:
            st.caption("실행 기록 없음 · 먼저 제안의 확인 조건을 살펴보세요.")
            label, mode = "관리 기록 남기기", MODES[1]
        else:
            st.caption(f"실행 기록 · {execution['occurred_on']} · {CARE_TYPES[execution['kind']]}")
            st.write(execution["notes"])
            observations = suggestion["observations"]
            if observations:
                latest = observations[-1]
                st.caption(f"최근 경과 · {latest['occurred_on']} · {RESULT_LABELS[latest['outcome']]}")
                with st.expander(f"이후 관찰 {len(observations)}건 보기"):
                    for log in observations:
                        st.write(f"**{log['occurred_on']} · {RESULT_LABELS[log['outcome']]}**")
                        if log["notes"]:
                            st.write(log["notes"])
                        if log["photo_path"]:
                            from .ui import display_photo
                            display_photo(store, log['photo_path'], width=260)
            else:
                st.caption("이후 경과 미확인 · 변화를 관찰한 뒤 남겨 주세요.")
            label, mode = "이후 상태 남기기", MODES[2]
        st.button(label, key=f"{prefix}_suggestion_{suggestion['id']}", width="stretch",
                  on_click=open_care, args=(suggestion["plant_id"], suggestion["id"], mode))
        if not execution:
            from .schedule_ui import prepare_ai_schedule
            from .ui import open_tab
            planned = any(item['status'] == 'pending' and item['source_suggestion_id'] == suggestion['id']
                          for item in store.list_schedules(suggestion['plant_id']))
            if planned:
                st.caption('이 제안으로 예정된 일정이 있어요. 실제로 관리하기 전까지 실행 기록은 생기지 않아요.')
                st.button('예정된 일정 보기', key=f"{prefix}_schedule_{suggestion['id']}", width='stretch',
                          on_click=open_tab, args=(suggestion['plant_id'], '케어 일정'))
            else:
                st.button('AI 제안으로 일정 만들기', key=f"{prefix}_schedule_{suggestion['id']}", width='stretch',
                          on_click=prepare_ai_schedule, args=(suggestion['plant_id'], suggestion['id']))


def care_form(store, plant_id):
    mode = st.radio("남길 기록", MODES, horizontal=True, key=f"care_mode_{plant_id}",
                    on_change=change_care_mode, args=(plant_id,))
    suggestions = store.list_suggestions(plant_id)
    eligible = [s for s in suggestions if (not s["execution"] if mode == MODES[1] else bool(s["execution"]))]
    suggestion = None
    if mode != MODES[0]:
        if not eligible:
            st.info("연결할 AI 제안이 없어요. AI 분석 탭에서 분석을 먼저 남겨 주세요." if mode == MODES[1]
                    else "AI 제안에 연결한 실행 기록을 먼저 남겨 주세요.")
            return
        choices = {s["id"]: s for s in eligible}
        selection_key = f"care_suggestion_{plant_id}"
        if st.session_state.get(selection_key) not in [None, *choices]:
            st.session_state[selection_key] = None
        selected = st.selectbox("연결할 AI 제안", [None, *choices], key=selection_key,
                                format_func=lambda sid: "제안을 선택해 주세요" if sid is None else
                                f"{suggested_date(choices[sid])} · {choices[sid]['suggestion_text'][:60]}")
        if selected is None:
            return
        suggestion = choices[selected]
        st.info(suggestion["suggestion_text"])

    titles = {MODES[0]: "오늘의 관리 기록", MODES[1]: "제안에 따라 관리했어요", MODES[2]: "관리 후, 어떻게 달라졌나요?"}
    st.subheader(titles[mode])
    if mode == MODES[1]:
        st.caption("실제로 한 관리를 적어 주세요. 물을 주지 않고 지켜봤다면 '상태 관찰'을 선택하세요.")
    elif mode == MODES[2]:
        st.caption("관찰한 변화만 남겨 주세요. 상태 변화만으로 관리의 효과를 확정하지 않습니다.")
    else:
        st.caption("무엇을 했는지, 이후 상태는 어떤지 차근차근 남겨주세요.")
    earliest = None
    if suggestion:
        earliest = (date.fromisoformat(suggestion["execution"]["occurred_on"]) if mode == MODES[2] else
                    suggested_date(suggestion))
    with st.form(f"care_log_{plant_id}", clear_on_submit=True):
        left, right = st.columns(2)
        with left:
            options = ["observation"] if mode == MODES[2] else list(CARE_TYPES)
            kind = st.selectbox("관리 종류", options, format_func=CARE_TYPES.get, key="care_kind",
                                index=None if mode == MODES[1] else 0, disabled=mode == MODES[2],
                                placeholder="실제로 한 관리를 선택하세요")
        with right:
            today = today_in_seoul()
            if st.session_state.get("care_date") is None:
                st.session_state["care_date"] = today
            occurred_on = st.date_input("기록 날짜", value=None, min_value=earliest, max_value=today, key="care_date")
        outcome = "unrecorded"
        if mode != MODES[1]:
            outcome = st.selectbox("관리 후 관찰한 상태" if mode == MODES[2] else "이전 기록과 비교한 상태",
                                   list(OUTCOMES), format_func=(RESULT_LABELS.get if mode == MODES[2] else OUTCOMES.get),
                                   help="경과를 아직 확인하지 않았다면 미확인으로 남겨 주세요.", key="care_outcome")
        notes = st.text_area("실제로 한 관리 *" if mode == MODES[1] else "상태와 메모", max_chars=3000,
                             placeholder="확인한 흙 상태, 실제로 한 관리나 이후 잎의 변화를 적어주세요.", key="care_notes")
        photo = st.file_uploader("오늘의 사진", type=["jpg", "jpeg", "png", "webp"], key="care_photo")
        label = "기록 저장" if mode == MODES[0] else ("실행 기록 저장" if mode == MODES[1] else "경과 기록 저장")
        save = st.form_submit_button(label, type="primary", width="stretch")
    if save:
        try:
            store.add_log(plant_id=plant_id, kind=kind, occurred_on=occurred_on, notes=notes, outcome=outcome,
                          photo=photo.getvalue() if photo is not None else None,
                          suggestion_id=suggestion["id"] if suggestion else None,
                          link_type=("execution" if mode == MODES[1] else "outcome") if suggestion else None)
        except ValueError as error:
            st.error(str(error))
        except OSError as error:
            from .cloud_store import CloudError
            st.error(str(error) if isinstance(error, CloudError) else '기록을 저장하지 못했어요. 저장소 상태를 확인해 주세요.')
        except sqlite3.Error:
            st.error("기록을 저장하지 못했어요. 저장 폴더와 디스크 공간을 확인해 주세요.")
        else:
            st.session_state["_notice"] = "관리 기록을 저장했어요." if not suggestion else "AI 제안과 연결해 기록을 저장했어요."
            if mode == MODES[1]:
                st.session_state[f"care_after_save_{plant_id}"] = (suggestion["id"], MODES[2])
            st.rerun()
