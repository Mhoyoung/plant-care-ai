"""Planned care stays separate from observed, completed care."""
from datetime import date, time
from html import escape
import sqlite3
import streamlit as st
from .constants import CARE_TYPES
from .time_utils import today_in_seoul
from .calendar_export import calendar_ics, google_calendar_url
from . import ui


def due_label(schedule):
    day, today = date.fromisoformat(schedule['due_on']), today_in_seoul()
    days = (day - today).days
    label = '오늘' if days == 0 else ('내일' if days == 1 else f'{-days}일 지남' if days < 0 else day.strftime('%m월 %d일'))
    return f"{label} · {schedule['due_time']}"


def garden_schedule_summary(store):
    schedules = [item for item in store.list_schedules() if item['status'] == 'pending']
    st.subheader('다가오는 케어')
    if not schedules:
        st.caption('식물 상세의 케어 일정에서 다음에 확인할 일을 정해 보세요.')
        return
    today = today_in_seoul().isoformat()
    due = sum(item['due_on'] <= today for item in schedules)
    st.caption(f'오늘까지 확인할 일정 {due}건 · 전체 예정 {len(schedules)}건')
    for item in schedules[:3]:
        with st.container(border=True, key=f"due_card_{item['id']}"):
            st.caption(due_label(item))
            st.write(f"**{item['plant_name']} · {item['title']}**")
            st.button('일정 살펴보기', key=f"due_open_{item['id']}", width='stretch',
                      on_click=ui.open_tab, args=(item['plant_id'], '케어 일정'))
    if len(schedules) > 3:
        st.caption('나머지 일정은 각 식물의 케어 일정에서 확인할 수 있어요.')


def _save(operation, *args, **kwargs):
    try:
        operation(*args, **kwargs)
    except (ValueError, OSError, sqlite3.Error) as error:
        from .cloud_store import CloudError
        st.error(str(error) if isinstance(error, (ValueError, CloudError)) else '일정을 저장하지 못했어요. 연결 상태를 확인해 주세요.')
        return False
    st.session_state['_notice'] = '일정을 저장했어요.'
    return True


def _fields(prefix, item=None):
    kind = st.selectbox('관리 종류', list(CARE_TYPES), index=list(CARE_TYPES).index(item['kind']) if item else 3,
                        format_func=CARE_TYPES.get, key=f'{prefix}_kind')
    title = st.text_input('할 일 *', value=item['title'] if item else '', max_chars=100,
                          placeholder='예: 흙 상태를 확인하고 물주기 판단', key=f'{prefix}_title')
    left, right = st.columns(2)
    with left:
        day = st.date_input('예정 날짜', value=date.fromisoformat(item['due_on']) if item else today_in_seoul(), key=f'{prefix}_day')
    with right:
        clock = st.time_input('예정 시간 · 한국 기준', value=time.fromisoformat(item['due_time']) if item else time(9), key=f'{prefix}_time')
    notes = st.text_area('일정 메모', value=item['notes'] if item else '', max_chars=1000, key=f'{prefix}_notes')
    return dict(title=title, kind=kind, due_on=day, due_time=clock, notes=notes)


def render_schedules(store, plant):
    plant_id = plant['id']
    st.subheader('작은 케어를 잊지 않도록')
    st.caption('일정은 관리할 예정이에요. 물을 주기 전에는 흙 상태부터 확인하고, 실제로 한 일은 완료할 때 남겨 주세요.')
    items = store.list_schedules(plant_id)
    pending = [item for item in items if item['status'] == 'pending']
    generation = st.session_state.get(f'schedule_generation_{plant_id}', 0)
    with st.expander('＋ 새 케어 일정', expanded=not pending):
        prefix = f'schedule_new_{plant_id}_{generation}'
        with st.form(prefix):
            values = _fields(prefix)
            added = st.form_submit_button('일정 추가', type='primary', width='stretch')
        if added and _save(store.add_schedule, plant_id, **values):
            st.session_state[f'schedule_generation_{plant_id}'] = generation + 1
            st.rerun()
    if pending:
        st.caption(f'예정 {len(pending)}건 · 날짜가 지난 일정도 실제 완료 전까지 유지돼요.')
    for item in pending:
        sid = item['id']
        prefix = f'schedule_{sid}'
        with st.container(border=True, key=f'schedule_card_{sid}'):
            st.html(f'<div class="schedule-due">{escape(due_label(item))}</div><h3 class="schedule-title">{escape(item["title"])}</h3>')
            st.caption(CARE_TYPES[item['kind']])
            if item['notes']:
                st.write(item['notes'])
            with st.expander('휴대폰 캘린더에 추가'):
                st.link_button('Google 캘린더에 추가', google_calendar_url(item), width='stretch')
                st.download_button('다른 캘린더 파일 (.ics)', calendar_ics(item), file_name=f'plant-care-{sid}.ics',
                                   mime='text/calendar', key=f'{prefix}_ics', width='stretch', on_click='ignore')
                st.caption('Google은 저장 화면에서 알림을 직접 설정해 주세요. .ics에는 10분 전 알림이 들어 있지만 캘린더에 따라 적용되지 않을 수 있어요. 추가 후 휴대폰 캘린더의 알림과 권한을 확인해 주세요.')
                st.caption('앱과 캘린더는 자동 동기화되지 않아요. 여기서 수정·취소해도 캘린더 일정은 남으므로 캘린더에서도 직접 변경해 주세요.')
            with st.expander('실제로 관리했어요 · 완료 기록'):
                with st.form(f'{prefix}_complete'):
                    actual_kind = st.selectbox('실제로 한 관리', list(CARE_TYPES), index=list(CARE_TYPES).index(item['kind']),
                                               format_func=CARE_TYPES.get, key=f'{prefix}_actual_kind')
                    actual_day = st.date_input('실제 관리 날짜', value=today_in_seoul(), max_value=today_in_seoul(), key=f'{prefix}_actual_day')
                    actual_notes = st.text_area('실제로 한 일 *', max_chars=3000,
                                                placeholder='물을 주지 않고 확인만 했다면 상태 관찰을 선택해 주세요.', key=f'{prefix}_actual_notes')
                    completed = st.form_submit_button('완료하고 관리 기록 저장', type='primary', width='stretch')
                if completed and _save(store.complete_schedule, sid, actual_kind, actual_day, actual_notes):
                    st.session_state['_notice'] = '일정을 완료하고 실제 관리 기록을 남겼어요.'
                    st.rerun()
            with st.expander('일정 수정·취소'):
                with st.form(f'{prefix}_edit'):
                    values = _fields(prefix, item)
                    edited = st.form_submit_button('변경 저장', width='stretch')
                if edited and _save(store.update_schedule, sid, **values):
                    st.rerun()
                with st.form(f'{prefix}_cancel'):
                    confirmed = st.checkbox('이 일정을 취소할게요', key=f'{prefix}_cancel_confirm')
                    cancelled = st.form_submit_button('일정 취소', width='stretch')
                if cancelled:
                    if not confirmed:
                        st.error('취소할 일정을 확인해 주세요.')
                    elif _save(store.cancel_schedule, sid):
                        st.rerun()
    history = [item for item in items if item['status'] != 'pending']
    if history:
        with st.expander(f'완료·취소한 일정 {len(history)}건'):
            for item in reversed(history):
                label = '완료 · 관리 기록에 저장됨' if item['status'] == 'completed' else '취소'
                st.write(f"**{item['title']}**")
                st.caption(f"{item['due_on']} {item['due_time']} · {label}")
