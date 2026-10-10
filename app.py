"""식물 등록과 관리 기록을 위한 첫 Streamlit 화면."""

from datetime import date
import json
import os
from pathlib import Path
import sqlite3

import streamlit as st

from plant_care.constants import CARE_TYPES, OUTCOMES
from plant_care.storage import PlantStore


APP_ROOT = Path(__file__).resolve().parent
DATA_ROOT = Path(os.environ.get("PLANT_CARE_DATA_DIR", str(APP_ROOT / "data")))

st.set_page_config(page_title="내 식물 기록", page_icon="🌿", layout="centered")
store = PlantStore(DATA_ROOT)
plants = store.list_plants()
plant_by_id = {plant["id"]: plant for plant in plants}

if "_select_after_save" in st.session_state:
    st.session_state["selected_plant"] = st.session_state.pop("_select_after_save")
if st.session_state.get("selected_plant", 0) not in [0, *plant_by_id]:
    st.session_state["selected_plant"] = 0

with st.sidebar:
    st.header("🌿 내 식물")
    selected_id = st.selectbox(
        "식물 선택",
        options=[0, *plant_by_id],
        format_func=lambda value: "＋ 새 식물 등록" if value == 0 else plant_by_id[value]["name"],
        key="selected_plant",
    )
    st.caption(f"등록한 식물 {len(plants)}개")

st.title("내 식물 기록")
st.caption("물 준 날과 작은 변화를 남겨보세요.")
if notice := st.session_state.pop("_notice", None):
    st.success(notice)

if selected_id == 0:
    st.subheader("새 식물 등록")
    if not plants:
        st.info("첫 식물을 등록하면 관리 기록을 남길 수 있어요.")
    with st.form("register_plant"):
        name = st.text_input("식물 이름 *", max_chars=100, placeholder="예: 몬스테라 A", key="plant_name")
        species = st.text_input("종류", max_chars=100, placeholder="알고 있는 경우 입력", key="plant_species")
        location = st.text_input("키우는 장소", max_chars=200, placeholder="예: 거실 창가", key="plant_location")
        notes = st.text_area("처음 상태와 메모", max_chars=3000, key="plant_notes")
        photo = st.file_uploader("식물 사진", type=["jpg", "jpeg", "png", "webp"], key="plant_photo")
        register = st.form_submit_button("식물 등록", type="primary")
    if register:
        try:
            new_id = store.add_plant(
                name=name, species=species, location=location, notes=notes,
                photo=photo.getvalue() if photo is not None else None,
            )
        except ValueError as error:
            st.error(str(error))
        except (OSError, sqlite3.Error):
            st.error("식물을 저장하지 못했어요. 저장 폴더와 디스크 공간을 확인해 주세요.")
        else:
            st.session_state["_select_after_save"] = new_id
            st.session_state["_notice"] = "식물을 등록했어요. 첫 관리 기록을 남겨보세요."
            st.rerun()
else:
    plant = plant_by_id[selected_id]
    st.subheader(plant["name"])
    st.write(" · ".join(value for value in (plant["species"], plant["location"]) if value) or "종류와 장소 미입력")
    if plant["photo_path"]:
        st.image(str(store.photo_path(plant["photo_path"])), width=320)
    if plant["notes"]:
        st.write(plant["notes"])

    logs = store.list_logs(selected_id)
    last_watered = store.last_watered(selected_id)
    left, right = st.columns(2)
    left.metric("마지막 물주기", last_watered or "기록 없음")
    right.metric("관리 기록", f"{len(logs)}개")

    st.subheader("관리 기록 남기기")
    with st.form(f"care_log_{selected_id}", clear_on_submit=True):
        kind = st.selectbox("관리 종류", list(CARE_TYPES), format_func=CARE_TYPES.get, key="care_kind")
        occurred_on = st.date_input("기록 날짜", value=date.today(), max_value=date.today(), key="care_date")
        outcome = st.selectbox(
            "이전 기록과 비교한 상태", list(OUTCOMES), format_func=OUTCOMES.get,
            help="경과를 아직 확인하지 않았다면 '미확인'을 선택하세요.", key="care_outcome",
        )
        log_notes = st.text_area("상태와 메모", max_chars=3000, placeholder="예: 흙이 말랐는지 확인했고, 잎이 조금 처져 있어요.", key="care_notes")
        log_photo = st.file_uploader("오늘의 사진", type=["jpg", "jpeg", "png", "webp"], key="care_photo")
        save_log = st.form_submit_button("기록 저장", type="primary")
    if save_log:
        try:
            store.add_log(
                plant_id=selected_id, kind=kind, occurred_on=occurred_on,
                notes=log_notes, outcome=outcome,
                photo=log_photo.getvalue() if log_photo is not None else None,
            )
        except ValueError as error:
            st.error(str(error))
        except (OSError, sqlite3.Error):
            st.error("기록을 저장하지 못했어요. 저장 폴더와 디스크 공간을 확인해 주세요.")
        else:
            st.session_state["_notice"] = "관리 기록을 저장했어요."
            st.rerun()

    st.subheader("관리 타임라인")
    if not logs:
        st.info("아직 기록이 없어요. 물주기나 상태 관찰부터 남겨보세요.")
    for log in logs:
        with st.container(border=True):
            st.write(f"**{log['occurred_on']} · {CARE_TYPES[log['kind']]}**")
            if log["outcome"] != "unrecorded":
                st.caption(f"이전 기록과 비교: {OUTCOMES[log['outcome']]}")
            if log["notes"]:
                st.write(log["notes"])
            if log["photo_path"]:
                st.image(str(store.photo_path(log["photo_path"])), width=320)

    st.download_button(
        "이 식물의 기록 내려받기",
        data=json.dumps(store.export_plant(selected_id), ensure_ascii=False, indent=2),
        file_name=f"plant-{selected_id}-records.json",
        mime="application/json",
        help="기록을 JSON 파일로 저장합니다. 사진 원본은 data/photos 폴더에 별도로 있습니다.",
    )
