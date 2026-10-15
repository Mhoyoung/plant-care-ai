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


def prepare_ai_schedule(plant_id, suggestion_id):
    ui.open_tab(plant_id, '케어 일정')
    st.session_state[f'schedule_draft_{plant_id}'] = suggestion_id
    st.session_state[f'schedule_generation_{plant_id}'] = st.session_state.get(f'schedule_generation_{plant_id}', 0) + 1


def clear_ai_draft(plant_id):
    st.session_state.pop(f'schedule_draft_{plant_id}', None)
    st.session_state[f'schedule_generation_{plant_id}'] = st.session_state.get(f'schedule_generation_{plant_id}', 0) + 1


def _source_details(source, analyses):
    st.write(source['suggestion_text'])
    analysis = analyses.get(source['analysis_id'])
    if analysis:
        st.write('**먼저 확인할 것**')
        for check in analysis['result']['checks']:
            st.write('• ' + check)
        st.caption(analysis['result']['uncertainty'])


def _fields(prefix, item=None, source=None):
    kind = st.selectbox('관리 종류', list(CARE_TYPES), index=list(CARE_TYPES).index(item['kind']) if item else (None if source else 3),
                        placeholder='계획할 관리 종류를 선택해 주세요',
                        format_func=CARE_TYPES.get, key=f'{prefix}_kind')
    source_title = source['suggestion_text'] if source else ''
    if len(source_title) > 100:
        source_title = source_title[:99] + '…'
        st.caption('할 일에는 짧은 제목을 사용해요. 전체 제안과 확인 조건은 위의 원문과 저장된 일정에 연결해 보관합니다.')
    title = st.text_input('할 일 *', value=item['title'] if item else source_title, max_chars=100,
                          placeholder='예: 흙 상태를 확인하고 물주기 판단', key=f'{prefix}_title')
    left, right = st.columns(2)
    with left:
        day = st.date_input('예정 날짜', value=date.fromisoformat(item['due_on']) if item else (None if source else today_in_seoul()), key=f'{prefix}_day')
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
    suggestions = {item['id']: item for item in store.list_suggestions(plant_id)}
    analyses = {item['id']: item for item in store.list_analyses(plant_id)}
    draft_id = st.session_state.get(f'schedule_draft_{plant_id}')
    source = suggestions.get(draft_id)
    if draft_id is not None and (source is None or source['execution'] or any(item['source_suggestion_id'] == draft_id for item in pending)):
        st.warning('이 제안은 이미 실행했거나 일정에 추가했거나 찾을 수 없어요. 아래 기록과 일정을 확인해 주세요.')
        clear_ai_draft(plant_id)
        source = None
    if source:
        st.info('AI 제안에서 만든 일정 초안이에요. AI 응답의 시점과 확인 조건을 참고해 날짜·시간·관리 종류를 직접 정해 주세요.')
        with st.expander('원래 AI 제안과 확인 조건', expanded=True):
            _source_details(source, analyses)
        st.button('일반 일정으로 입력', key=f'schedule_clear_{plant_id}', on_click=clear_ai_draft, args=(plant_id,))
    generation = st.session_state.get(f'schedule_generation_{plant_id}', 0)
    with st.expander('＋ 새 케어 일정', expanded=bool(source) or not pending):
        prefix = f'schedule_new_{plant_id}_{generation}'
        with st.form(prefix):
            values = _fields(prefix, source=source)
            confirmed = st.checkbox('AI 제안의 확인 조건과 예정 날짜를 확인했어요', key=f'{prefix}_confirmed') if source else True
            added = st.form_submit_button('일정 추가', type='primary', width='stretch')
        if added:
            if not confirmed:
                st.error('AI 제안의 조건과 날짜를 확인한 뒤 체크해 주세요.')
            elif _save(store.add_schedule, plant_id, **values, source_suggestion_id=source['id'] if source else None):
                clear_ai_draft(plant_id)
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
            if linked := suggestions.get(item['source_suggestion_id']):
                st.caption('저장된 AI 제안에서 만든 일정 · 실제 완료 시 해당 제안의 실행 기록으로 연결돼요.')
                with st.expander('이 일정의 AI 제안·확인 조건'):
                    _source_details(linked, analyses)
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
