"""식물 기록 화면 스타일. 사용자 텍스트는 출력 전에 이스케이프한다."""
from datetime import date, datetime
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo
import streamlit as st
from .private_media import photo

ROOT = Path(__file__).resolve().parents[1]

def style():
    st.html(f"<style>{(ROOT / 'assets' / 'garden.css').read_text(encoding='utf-8')}</style>")

def navigate(plant_id):
    st.session_state["selected_plant"] = plant_id if plant_id > 0 else -1
    st.session_state["_main_tab_target"] = {0: "새 식물", -2: "AI 비교"}.get(plant_id, "내 정원")
    st.session_state["_main_nav_generation"] = st.session_state.get("_main_nav_generation", 0) + 1

def select_garden_plant():
    st.session_state["_main_tab_target"] = "내 정원"
    st.session_state["_main_nav_generation"] = st.session_state.get("_main_nav_generation", 0) + 1

def open_tab(plant_id, label):
    navigate(plant_id)
    st.session_state[f"plant_tabs_{plant_id}"] = label

def start_record(plant_id, suggestion_id=None, mode="일반 기록"):
    from .care_ui import open_care
    navigate(plant_id)
    open_care(plant_id, suggestion_id, mode)
    if mode == "일반 기록":
        st.session_state["care_kind"] = "observation"

def heading(eyebrow, title, subtitle=""):
    st.html(f'<div class="page-heading"><span class="eyebrow">{escape(eyebrow)}</span>'
            f'<h1>{escape(title)}</h1><p>{escape(subtitle)}</p></div>')

def hero():
    today = datetime.now(ZoneInfo("Asia/Seoul"))
    with st.container(key="garden_hero"):
        left, right = st.columns([1.5, 1], gap="small", vertical_alignment="center")
        with left:
            st.html(f'<div class="hero-copy">'
            f'<span class="eyebrow">MY LITTLE GARDEN · {today:%Y.%m.%d}</span>'
            '<h1>오늘의 작은 관찰,<br>내 식물의 다음 한 걸음.</h1>'
            '<p>사진과 관리 기록을 쌓고,<br>이 식물에 맞는 다음 행동을 함께 찾아요.</p>'
            '<span class="hero-foot">GROW A LITTLE, EVERY DAY</span></div>')
        with right:
            st.image(str(ROOT / "assets" / "botanical.svg"), width="stretch")

def plant_photo(store, plant, detail=False):
    with st.container(key=f"photo_{'detail' if detail else 'card'}_{plant['id']}"):
        if plant['photo_path']:
            display_photo(store, plant['photo_path'], width='stretch')
        else:
            st.image(str(ROOT / 'assets' / 'botanical.svg'), width='stretch')
        if not plant["photo_path"]:
            st.caption("등록 사진이 없는 식물의 예시 일러스트")

def display_photo(store, relative, width):
    try:
        photo(store.read_photo(relative), width=width, personal=getattr(store, 'personal', False))
    except (OSError, ValueError):
        st.warning('사진을 불러오지 못했어요. 기록은 유지되며 저장소 연결 후 다시 확인할 수 있어요.')

def watering_label(value):
    if not value:
        return "아직 물주기 기록이 없어요"
    days = (datetime.now(ZoneInfo("Asia/Seoul")).date() - date.fromisoformat(value)).days
    relative = "오늘" if days == 0 else ("어제" if days == 1 else f"{days}일 전")
    return f"마지막 물주기 · {relative}"

def stat(label, value, hint):
    st.html(f'<div class="garden-stat"><span>{escape(label)}</span><strong>{escape(value)}</strong>'
            f'<small>{escape(hint)}</small></div>')

def plant_card(store, plant, logs, analyses):
    with st.container(border=True, key=f"plant_card_{plant['id']}"):
        plant_photo(store, plant)
        st.html(f'<div class="plant-card-copy"><span class="eyebrow">{escape(plant["species"] or "MY PLANT")}</span>'
                f'<h3>{escape(plant["name"])}</h3><p>{escape(plant["location"] or "키우는 장소를 기록해 보세요")}</p>'
                f'<div class="care-chip">{escape(watering_label(store.last_watered(plant["id"])))}</div>'
                f'<div class="card-counts">관리 기록 {len(logs)}건 <span>·</span> AI 관찰 {len(analyses)}건</div></div>')
        st.button("식물 살펴보기 →", key=f"open_plant_{plant['id']}", width="stretch", on_click=navigate, args=(plant["id"],))
        st.button("오늘 상태 남기기", key=f"record_plant_{plant['id']}", width="stretch", on_click=start_record, args=(plant['id'],))

def detail_hero(store, plant):
    with st.container(key="plant_detail_hero"):
        left, right = st.columns([1, 2], gap="medium", vertical_alignment="center")
        with left:
            plant_photo(store, plant, True)
        with right:
            st.html('<div class="detail-copy"><span class="eyebrow">PLANT JOURNAL</span>'
            f'<h1>{escape(plant["name"])}</h1><div class="plant-meta">{escape(plant["species"] or "종류 미입력")}'
            f' <span> / </span> {escape(plant["location"] or "장소 미입력")}</div>'
            f'<p>{escape(plant["notes"] or "이 식물과 함께한 작은 변화를 기록해 보세요.")}</p>'
            '<span class="detail-foot">하나의 식물, 쌓여가는 이야기</span></div>')

def timeline(store, logs, care_types, outcomes, limit=None):
    if not logs:
        st.html('<div class="quiet-empty"><span>아직 첫 페이지가 비어 있어요.</span>'
                '<p>물주기나 잎의 작은 변화부터 기록해 보세요.</p></div>')
    for log in logs[:limit] if limit else logs:
        with st.container(border=True, key=f"log_{log['id']}_{limit or 'all'}"):
            outcome = "" if log["outcome"] == "unrecorded" else f' · {outcomes[log["outcome"]]}'
            st.html(f'<div class="timeline-top"><span class="care-chip">{escape(care_types[log["kind"]])}</span>'
                    f'<span>{escape(log["occurred_on"])}{escape(outcome)}</span></div>')
            if log["notes"]:
                st.write(log["notes"])
            if log.get("suggestion_id"):
                label = "AI 제안 실행" if log["link_type"] == "execution" else "AI 관리 후 경과"
                st.caption(f"{label} · {log['suggestion_text']}")
            if log["photo_path"]:
                display_photo(store, log['photo_path'], width=320)
