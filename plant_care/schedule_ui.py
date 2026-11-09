"""Planned care stays separate from observed, completed care."""
from datetime import date, time, datetime
from html import escape
import sqlite3
from zoneinfo import ZoneInfo
import streamlit as st
from .private_media import download
from .constants import CARE_TYPES
from .time_utils import today_in_seoul
from .calendar_export import CalendarLinkTooLong, calendar_ics, google_calendar_url
from .schedule_text import ai_schedule_description, short_proposal_title
from . import ui


def due_label(schedule):
    day, today = date.fromisoformat(schedule['due_on']), today_in_seoul()
    days = (day - today).days
    label = '오늘' if days == 0 else ('내일' if days == 1 else f'{-days}일 지남' if days < 0 else day.strftime('%m월 %d일'))
    return f"{label} · {schedule['due_time']}"


def garden_schedule_summary(store):
    schedules = [item for item in store.list_schedules() if item['status'] == 'pending']
    st.subheader('오늘 챙길 일')
    if not schedules:
        st.html('<div class="home-schedule-empty"><b>예정된 케어가 없어요</b>'
                '<p>식물의 현재 모습과 흙 상태부터 살펴보세요.</p></div>')
        plants = store.list_plants()
        if plants:
            st.button('오늘 상태 남기기', key=f"today_{plants[0]['id']}", width='stretch',
                      on_click=ui.start_record, args=(plants[0]['id'],))
            st.caption(f"{plants[0]['name']} · 다른 식물은 아래 카드에서 선택하세요.")
        else:
            st.caption('식물을 등록하면 기록과 케어 일정을 함께 관리할 수 있어요.')
        return
    today = today_in_seoul().isoformat()
    due = sum(item['due_on'] <= today for item in schedules)
    st.caption(f'오늘까지 확인할 일정 {due}건 · 전체 예정 {len(schedules)}건')
    for item in schedules[:3]:
        with st.container(border=True, key=f"due_card_{item['id']}"):
            with st.container(key=f"home_due_row_{item['id']}"):
                copy, action = st.columns([3, 1], vertical_alignment='center')
                with copy:
                    st.html(f'<div class="home-due-meta">{escape(due_label(item))} · {escape(item["plant_name"])}</div>'
                            f'<div class="home-due-title">{escape(item["title"])}</div>')
                with action:
                    st.button('일정 보기', key=f"due_open_{item['id']}", width='stretch',
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


def _calendar_details(source, analyses):
    analysis = analyses.get(source['analysis_id']) if source else None
    if not analysis:
        return None
    result = analysis['result']
    return ai_schedule_description(source['suggestion_text'], result['checks'], result['uncertainty'])


def _schedule_candidates(plant_id, suggestions, analyses, pending):
    planned = {item['source_suggestion_id'] for item in pending}
    candidates = [item for item in suggestions.values() if not item['execution'] and item['id'] not in planned]
    if not candidates:
        st.caption('아직 일정으로 만들 수 있는 AI 제안이 없어요. 아래에서 직접 입력하거나 AI 분석에서 먼저 살펴보세요.')
        st.button('AI 분석에서 살펴보기', key=f'schedule_analysis_{plant_id}', width='stretch',
                  on_click=ui.open_tab, args=(plant_id, 'AI 분석'))
        return
    st.subheader('AI 제안으로 시작하기')
    st.caption('이미 저장한 분석의 제안이에요. 현재 상태와 확인 조건을 살펴보고 일정을 정해 주세요. 추가 AI 요청은 없어요.')

    def candidate_card(item):
        with st.container(border=True, key=f"candidate_card_{item['id']}"):
            timestamp = datetime.fromisoformat(item['suggested_at']).astimezone(ZoneInfo('Asia/Seoul'))
            demo = analyses.get(item['analysis_id'], {}).get('input', {}).get('evaluation_demo')
            st.caption(f"{timestamp:%Y.%m.%d} 분석에서 제안" + (' · 가상 사례' if demo else ''))
            st.write(item['suggestion_text'])
            st.button('이 제안으로 일정 만들기', key=f"schedule_candidate_{item['id']}", width='stretch',
                      on_click=prepare_ai_schedule, args=(plant_id, item['id']))

    for item in candidates[:3]:
        candidate_card(item)
    if len(candidates) > 3:
        with st.expander(f'이전 제안 {len(candidates) - 3}개 더 보기'):
            for item in candidates[3:]:
                candidate_card(item)


def _fields(prefix, item=None, source=None):
    kind = st.selectbox('관리 종류', list(CARE_TYPES), index=list(CARE_TYPES).index(item['kind']) if item else (None if source else 3),
                        placeholder='계획할 관리 종류를 선택해 주세요',
                        format_func=CARE_TYPES.get, key=f'{prefix}_kind')
    source_title = short_proposal_title(source['suggestion_text']) if source else ''
    if source:
        st.caption('제목은 확인할 주제로 짧게 채웠어요. 직접 바꿀 수 있고, 원래 제안·확인 조건·분석 한계는 캘린더 설명에 모두 들어가요.')
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
    items = store.list_schedules(plant_id)
    pending = [item for item in items if item['status'] == 'pending']
    history = [item for item in items if item['status'] != 'pending']
    suggestions = {item['id']: item for item in store.list_suggestions(plant_id)}
    analyses = {item['id']: item for item in store.list_analyses(plant_id)}
    draft_id = st.session_state.get(f'schedule_draft_{plant_id}')
    source = suggestions.get(draft_id)
    today = today_in_seoul().isoformat()
    overdue = sum(item['due_on'] < today for item in pending)
    due_today = sum(item['due_on'] == today for item in pending)
    with st.container(key='schedule_workspace'):
        st.html('<section class="schedule-intro" aria-label="케어 일정 요약">'
                '<span class="schedule-label">나의 케어 플랜</span><h3>작은 케어를 잊지 않도록</h3>'
                '<p>확인할 날을 정하고, 실제로 한 관리는 완료할 때 남겨요.</p>'
                f'<div class="schedule-totals"><span>오늘 확인 <b>{due_today}</b></span>'
                f'<span>예정일 지남 <b>{overdue}</b></span><span>전체 예정 <b>{len(pending)}</b></span></div></section>')
        if draft_id is not None and (source is None or source['execution'] or any(item['source_suggestion_id'] == draft_id for item in pending)):
            st.warning('이 제안은 이미 실행했거나 일정에 추가했거나 찾을 수 없어요. 아래 기록과 일정을 확인해 주세요.')
            clear_ai_draft(plant_id)
            source = None
        _schedule_creator(store, plant_id, pending, source, suggestions, analyses)
        _pending_sections(store, pending, suggestions, analyses, today)
        _schedule_history(plant_id, history)


def _schedule_creator(store, plant_id, pending, source, suggestions, analyses):
    with st.container(key='schedule_creator'), st.expander(
            'AI 제안 일정 초안' if source else '＋ 새 케어 일정', expanded=bool(source) or not pending):
        if source:
            st.info('AI 제안에서 만든 일정 초안이에요. AI 응답의 시점과 확인 조건을 참고해 날짜·시간·관리 종류를 직접 정해 주세요.')
            with st.expander('원래 AI 제안과 확인 조건', expanded=True):
                _source_details(source, analyses)
            st.button('일반 일정으로 입력', key=f'schedule_clear_{plant_id}', on_click=clear_ai_draft, args=(plant_id,))
        else:
            with st.expander('AI 제안에서 일정 만들기', expanded=False):
                _schedule_candidates(plant_id, suggestions, analyses, pending)
        generation = st.session_state.get(f'schedule_generation_{plant_id}', 0)
        st.subheader('AI 제안으로 일정 추가' if source else '직접 일정 추가')
        st.caption('할 일과 확인할 시점을 정해 주세요. 일정 등록만으로 관리 기록이 생기지는 않아요.')
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


def _pending_sections(store, pending, suggestions, analyses, today):
    with st.container(key='schedule_pending'):
        st.subheader('예정된 케어')
        if not pending:
            st.html('<div class="schedule-empty"><b>아직 예정된 케어 일정이 없어요</b>'
                    '<p>새 케어 일정에서 다음에 확인할 일을 정해 보세요.<br>물을 주기 전에는 흙 상태부터 살펴봐 주세요.</p></div>')
            return
        st.caption(f'예정 {len(pending)}건 · 날짜가 지난 일정도 실제 완료 전까지 유지돼요.')
        groups = [('먼저 확인해 주세요', [item for item in pending if item['due_on'] <= today]),
                  ('다가오는 일정', [item for item in pending if item['due_on'] > today])]
        for title, group in groups:
            if group:
                st.html(f'<div class="schedule-group-heading"><h4>{title}</h4><span>{len(group)}건</span></div>')
                for item in group:
                    _schedule_card(store, item, suggestions, analyses, today)


def _schedule_card(store, item, suggestions, analyses, today):
    sid = item['id']
    prefix = f'schedule_{sid}'
    status, label = ('overdue', '예정일 지남') if item['due_on'] < today else (
        ('today', '오늘') if item['due_on'] == today else ('upcoming', '예정'))
    linked = suggestions.get(item['source_suggestion_id'])
    origin = 'AI 제안에서 만든 일정' if item['source_suggestion_id'] is not None else '직접 등록한 일정'
    with st.container(border=True, key=f'schedule_card_{sid}'):
        st.html(f'<div class="schedule-card-meta"><span class="schedule-status {status}">{label}</span>'
                f'<span>{escape(item["due_on"])} · {escape(item["due_time"])} · 한국 시간</span></div>'
                f'<h3 class="schedule-title">{escape(item["title"])}</h3>'
                f'<div class="schedule-card-kind"><span>{escape(CARE_TYPES[item["kind"]])}</span><span>{origin}</span></div>')
        if item['notes']:
            with st.expander('일정 메모'):
                st.write(item['notes'])
        if linked:
            with st.expander('이 일정의 AI 제안·확인 조건'):
                _source_details(linked, analyses)
        with st.container(key=f'schedule_complete_{sid}'), st.expander('실제로 관리했어요 · 완료 기록'):
            _schedule_completion(store, item, prefix)
        with st.expander('휴대폰 캘린더에 추가'):
            _schedule_calendar(store, item, linked, analyses, prefix)
        with st.expander('일정 수정·취소'):
            _schedule_editor(store, item, prefix)


def _schedule_completion(store, item, prefix):
    st.caption('예정과 달라도 실제로 한 관리를 선택해 주세요. 물을 주지 않고 확인만 했다면 상태 관찰로 남겨요.')
    with st.form(f'{prefix}_complete'):
        actual_kind = st.selectbox('실제로 한 관리', list(CARE_TYPES), index=list(CARE_TYPES).index(item['kind']),
                                   format_func=CARE_TYPES.get, key=f'{prefix}_actual_kind')
        actual_day = st.date_input('실제 관리 날짜', value=today_in_seoul(), max_value=today_in_seoul(), key=f'{prefix}_actual_day')
        actual_notes = st.text_area('실제로 한 일 *', max_chars=3000,
                                   placeholder='물을 주지 않고 확인만 했다면 상태 관찰을 선택해 주세요.', key=f'{prefix}_actual_notes')
        completed = st.form_submit_button('완료하고 관리 기록 저장', type='primary', width='stretch')
    if completed and _save(store.complete_schedule, item['id'], actual_kind, actual_day, actual_notes):
        st.session_state['_notice'] = '일정을 완료하고 실제 관리 기록을 남겼어요.'
        st.rerun()


def _schedule_calendar(store, item, linked, analyses, prefix):
    ai_details = _calendar_details(linked, analyses)
    if item['source_suggestion_id'] is not None and not ai_details:
        st.warning('원래 AI 제안과 확인 조건을 찾을 수 없어요. 내 기록을 새로고침한 뒤 다시 시도해 주세요.')
    else:
        if ai_details:
            with st.expander('캘린더에 들어갈 AI 설명'):
                st.text(ai_details)
        try:
            calendar_url = google_calendar_url(item, ai_details=ai_details)
        except CalendarLinkTooLong as error:
            calendar_url = None
            st.info(str(error) + ' Google 캘린더는 PC 웹 설정의 가져오기 및 내보내기에서 파일을 가져올 수 있어요.')
        if calendar_url:
            google, other = st.columns(2, gap='small')
            with google:
                st.link_button('Google 캘린더에 추가', calendar_url, width='stretch')
            with other:
                download(store, '다른 캘린더 파일 (.ics)', calendar_ics(item, ai_details=ai_details),
                         file_name=f'plant-care-{item["id"]}.ics', mime='text/calendar', key=f'{prefix}_ics', width='stretch', on_click='ignore')
        else:
            download(store, '다른 캘린더 파일 (.ics)', calendar_ics(item, ai_details=ai_details),
                     file_name=f'plant-care-{item["id"]}.ics', mime='text/calendar', key=f'{prefix}_ics', width='stretch', on_click='ignore')
    st.caption('Google은 저장 화면에서 알림을 직접 설정해 주세요. .ics에는 10분 전 알림이 들어 있지만 캘린더에 따라 적용되지 않을 수 있어요. 추가 후 휴대폰 캘린더의 알림과 권한을 확인해 주세요.')
    st.caption('앱과 캘린더는 자동 동기화되지 않아요. 여기서 수정·취소해도 캘린더 일정은 남으므로 캘린더에서도 직접 변경해 주세요.')


def _schedule_editor(store, item, prefix):
    st.caption('날짜·할 일을 바꾸거나, 더 이상 필요하지 않은 일정을 취소할 수 있어요.')
    with st.form(f'{prefix}_edit'):
        values = _fields(prefix, item)
        edited = st.form_submit_button('변경 저장', width='stretch')
    if edited and _save(store.update_schedule, item['id'], **values):
        st.rerun()
    with st.form(f'{prefix}_cancel'):
        confirmed = st.checkbox('이 일정을 취소할게요', key=f'{prefix}_cancel_confirm')
        cancelled = st.form_submit_button('일정 취소', width='stretch')
    if cancelled:
        if not confirmed:
            st.error('취소할 일정을 확인해 주세요.')
        elif _save(store.cancel_schedule, item['id']):
            st.rerun()


def _schedule_history(plant_id, history):
    if not history:
        return
    with st.container(key='schedule_history'), st.expander(f'완료·취소한 일정 {len(history)}건'):
        for item in reversed(history):
            completed = item['status'] == 'completed'
            label = '완료' if completed else '취소'
            with st.container(key=f'schedule_history_{item["id"]}'):
                st.html(f'<div class="schedule-history-row"><span class="schedule-status {"done" if completed else "cancelled"}">{label}</span>'
                        f'<div><b>{escape(item["title"])}</b><small>예정 {escape(item["due_on"])} · {escape(item["due_time"])}</small></div></div>')
                if completed:
                    st.caption('완료 · 실제로 한 관리가 기록에 저장됐어요.')
                    st.button('관리 기록 보기', key=f'schedule_history_log_{item["id"]}', width='stretch',
                              on_click=ui.open_tab, args=(plant_id, '관리 기록'))
