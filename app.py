"""내 정원, 식물별 관리 기록과 AI 관찰 화면."""
import json
import os
from pathlib import Path
import sqlite3
import streamlit as st
from plant_care.constants import CARE_TYPES, OUTCOMES
from plant_care.store_factory import create_store
from plant_care.cloud_store import CloudError
from plant_care.data_ui import data_tools
from plant_care.ai_ui import render_analysis
from plant_care.comparison_ui import comparison_screen
from plant_care.insight_ui import partner_note
from plant_care.care_ui import care_form, open_care, suggestion_card
from plant_care import ui

APP_ROOT = Path(__file__).resolve().parent
DATA_ROOT = Path(os.environ.get("PLANT_CARE_DATA_DIR", str(APP_ROOT / "data")))
st.set_page_config(page_title="내 식물 기록 · 내 정원", page_icon="🌿", layout="wide", initial_sidebar_state="collapsed")
ui.style()
try:
    settings = st.secrets.to_dict()
except (FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
    settings = {}
try:
    store = create_store(DATA_ROOT, settings)
    plants = store.list_plants()
except (CloudError, OSError, sqlite3.Error) as error:
    st.error(str(error) if isinstance(error, CloudError) else '기록 저장소에 연결하지 못했어요.')
    if st.button('저장소 다시 연결'):
        st.rerun()
    st.stop()
plant_by_id = {plant["id"]: plant for plant in plants}
if "_select_after_save" in st.session_state:
    st.session_state["selected_plant"] = st.session_state.pop("_select_after_save")
if "selected_plant" not in st.session_state:
    st.session_state["selected_plant"] = -1 if plants else 0
if st.session_state["selected_plant"] not in [-2, -1, 0, *plant_by_id]:
    st.session_state["selected_plant"] = -1 if plants else 0
with st.sidebar:
    st.html('<div class="eyebrow">A LITTLE GREEN, EVERY DAY</div><div class="sidebar-brand">내 식물 기록</div><div class="sidebar-note">함께 자라는 나의 작은 정원</div>')
    selected_id = st.selectbox("둘러보기", options=[-1, 0, -2, *plant_by_id],
        format_func=lambda value: {-1: "내 정원", 0: "＋ 새 식물 등록", -2: "AI 비교 실험"}.get(value, plant_by_id.get(value, {}).get("name", "")), key="selected_plant")
    st.caption(f"함께 키우는 식물 {len(plants)}개")
    data_tools(store)
    st.html('<div class="sidebar-footer">PLANT JOURNAL<br>오늘의 작은 변화를 남겨보세요.</div>')
with st.container(key="top_nav"):
    st.html('<div class="mobile-brand">🌿 내 식물 기록 <span>작은 관찰, 함께 자라는 하루</span></div>')
    nav = st.columns(3, gap="small")
    for column, target, label in zip(nav, [-1, 0, -2], ["내 정원", "새 식물", "AI 비교"]):
        column.button(label, key=f"nav_{target}", width="stretch", type="primary" if selected_id == target else "secondary", on_click=ui.navigate, args=(target,))
if notice := st.session_state.pop("_notice", None):
    st.success(notice)

def register_plant():
    ui.heading("NEW COMPANION", "새로운 초록을 들여요", "이름과 사진을 남기면, 이 식물만의 기록이 시작돼요.")
    with st.form("register_plant"):
        left, right = st.columns(2)
        with left:
            name = st.text_input("식물 이름 *", max_chars=100, placeholder="예: 몬스테라 A", key="plant_name")
        with right:
            species = st.text_input("종류", max_chars=100, placeholder="알고 있는 경우 입력", key="plant_species")
        location = st.text_input("키우는 장소", max_chars=200, placeholder="예: 거실 창가", key="plant_location")
        notes = st.text_area("처음 상태와 메모", max_chars=3000, placeholder="처음 만난 날의 모습이나 기억하고 싶은 내용을 적어주세요.", key="plant_notes")
        photo = st.file_uploader("식물 사진", type=["jpg", "jpeg", "png", "webp"], key="plant_photo")
        register = st.form_submit_button("식물 등록", type="primary", width="stretch")
    if register:
        try:
            new_id = store.add_plant(name=name, species=species, location=location, notes=notes, photo=photo.getvalue() if photo is not None else None)
        except ValueError as error:
            st.error(str(error))
        except CloudError as error:
            st.error(str(error))
        except (OSError, sqlite3.Error):
            st.error("식물을 저장하지 못했어요. 저장 폴더와 디스크 공간을 확인해 주세요.")
        else:
            st.session_state["_select_after_save"] = new_id
            st.session_state["_notice"] = "식물을 등록했어요. 첫 관리 기록을 남겨보세요."
            st.rerun()

def garden():
    ui.hero()
    records = {p["id"]: store.list_logs(p["id"]) for p in plants}
    analyses = {p["id"]: store.list_analyses(p["id"]) for p in plants}
    with st.container(key="garden_stats"):
        columns = st.columns(3)
        with columns[0]:
            ui.stat("함께 키우는 식물", f"{len(plants)}개", "나의 초록 동반자")
        with columns[1]:
            ui.stat("쌓인 관리 기록", f"{sum(map(len, records.values()))}건", "물주기부터 작은 관찰까지")
        with columns[2]:
            ui.stat("AI 관찰", f"{sum(map(len, analyses.values()))}건", "기록을 참고한 관리 제안")
    st.subheader("오늘, 이렇게 시작해요")
    st.caption("물주기 날짜만으로 필요한 관리를 정하지 않아요. 현재 모습과 흙 상태를 먼저 확인해 주세요.")
    if plants:
        for plant in plants[:3]:
            followups = [s for s in store.list_suggestions(plant['id']) if s['execution'] and not s['observations']]
            with st.container(border=True):
                st.write(f"**{plant['name']}**")
                st.caption("실행한 관리 이후의 변화가 아직 기록되지 않았어요." if followups else "오늘 확인한 흙 상태나 잎의 모습을 짧게 남겨보세요.")
                if followups:
                    st.button("관리 후 변화 남기기", key=f"today_{plant['id']}", width="stretch", on_click=ui.start_record, args=(plant['id'], followups[0]['id'], "실행 후 경과"))
                else:
                    st.button("오늘 상태 남기기", key=f"today_{plant['id']}", width="stretch", on_click=ui.start_record, args=(plant['id'],))
    else:
        st.info("첫 식물을 등록하면 사진과 관리 기록을 차곡차곡 남길 수 있어요. 실제 식물이 없다면 AI 비교의 예시 사례로 먼저 둘러보세요.")
    st.write("")
    st.subheader("나의 식물들")
    st.caption("식물을 선택해 최근 변화와 관리 기록을 살펴보세요.")
    for start in range(0, len(plants) + 1, 2):
        slots = st.columns(2)
        for offset, slot in enumerate(slots):
            index = start + offset
            with slot:
                if index < len(plants):
                    plant = plants[index]
                    ui.plant_card(store, plant, records[plant["id"]], analyses[plant["id"]])
                elif index == len(plants):
                    st.html('<div class="add-plant-card"><b>＋</b><h3>새로운 초록을 만나보세요</h3><p>작은 화분 하나가<br>새로운 이야기의 시작이 돼요.</p></div>')
                    st.button("＋ 새 식물 등록", key="garden_add", width="stretch", on_click=ui.navigate, args=(0,))

def plant_detail(plant):
    if target := st.session_state.pop(f"care_after_save_{plant['id']}", None):
        open_care(plant["id"], *target)
    st.button("← 내 정원", key="back_to_garden", type="tertiary", on_click=ui.navigate, args=(-1,))
    with st.container(key="detail_actions"):
        actions = st.columns(2, gap="small")
        actions[0].button("오늘 상태 남기기", key="detail_record", width="stretch", type="primary", on_click=ui.start_record, args=(plant['id'],))
        actions[1].button("AI로 살펴보기", key="detail_ai", width="stretch", on_click=ui.open_tab, args=(plant['id'], "AI 분석"))
    ui.detail_hero(store, plant)
    logs = store.list_logs(plant["id"])
    analyses = store.list_analyses(plant["id"])
    last_watered = store.last_watered(plant["id"])
    with st.container(key="detail_stats"):
        columns = st.columns(3)
        with columns[0]:
            ui.stat("마지막 물주기", last_watered or "기록 없음", ui.watering_label(last_watered))
        with columns[1]:
            ui.stat("관리 기록", f"{len(logs)}건", "이 식물과 함께한 순간")
        with columns[2]:
            ui.stat("AI 관찰", f"{len(analyses)}건", "저장한 분석 결과")
    overview, care, ai = st.tabs(["한눈에 보기", "관리 기록", "AI 분석"], key=f"plant_tabs_{plant['id']}", on_change="rerun")
    with overview:
        left, right = st.columns([1.15, 1], gap="large")
        with left:
            st.subheader("최근의 작은 변화")
            ui.timeline(store, logs, CARE_TYPES, OUTCOMES, limit=3)
        with right:
            st.subheader("최근 AI 관찰")
            if analyses:
                latest_result = analyses[0]['result']
                partner_note(latest_result['summary'], analyses[0]['input'], latest_result['checks'][0] if latest_result['checks'] else None)
                st.caption("전체 제안과 확인할 사항은 AI 분석 탭에서 살펴보세요.")
            else:
                st.html('<div class="quiet-empty"><span>이 식물에 대해 궁금한 게 있나요?</span><p>AI 분석 탭에서 현재 모습과 기록을 함께 살펴보세요.</p></div>')
            followed = [s for s in store.list_suggestions(plant["id"]) if s["execution"]][:3]
            if followed:
                st.subheader("제안 이후의 변화")
                for suggestion in followed:
                    suggestion_card(store, suggestion, "overview")
    with care:
        left, right = st.columns(2, gap="large")
        with left:
            care_form(store, plant["id"])
        with right:
            st.subheader("관리 타임라인")
            st.caption("남겨둔 기록을 시간순으로 모았어요.")
            ui.timeline(store, logs, CARE_TYPES, OUTCOMES)
    with ai:
        render_analysis(store, plant)
    st.divider()
    st.download_button("이 식물의 기록 내려받기", data=json.dumps(store.export_plant(plant["id"]), ensure_ascii=False, indent=2), file_name=f"plant-{plant['id']}-records.json", mime="application/json", help="사진까지 보관하려면 메뉴의 '기록 보관과 백업'에서 전체 정원 백업을 준비하세요.")

if selected_id == -2:
    comparison_screen(store, plants)
elif selected_id == -1:
    garden()
elif selected_id == 0:
    register_plant()
else:
    plant_detail(plant_by_id[selected_id])
