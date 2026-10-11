"""식물 기록 화면 스타일. 사용자 텍스트는 출력 전에 이스케이프한다."""
from datetime import date, datetime
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]

def style():
    st.html(f"<style>{(ROOT / 'assets' / 'garden.css').read_text(encoding='utf-8')}</style>")

def navigate(plant_id):
    st.session_state["selected_plant"] = plant_id

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
            '<h1>작은 관찰이 쌓여,<br>더 푸른 일상이 돼요.</h1>'
            '<p>물 준 날부터 새로 돋은 잎까지.<br>내 식물의 이야기를 한곳에 모아보세요.</p>'
            '<span class="hero-foot">GROW A LITTLE, EVERY DAY</span></div>')
        with right:
            st.image(str(ROOT / "assets" / "botanical.svg"), width="stretch")

def plant_photo(store, plant, detail=False):
    with st.container(key=f"photo_{'detail' if detail else 'card'}_{plant['id']}"):
        path = store.photo_path(plant["photo_path"]) if plant["photo_path"] else ROOT / "assets" / "botanical.svg"
        st.image(str(path), width="stretch")
        if not plant["photo_path"]:
            st.caption("등록 사진이 없는 식물의 예시 일러스트")

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
            if log["photo_path"]:
                st.image(str(store.photo_path(log["photo_path"])), width=320)
