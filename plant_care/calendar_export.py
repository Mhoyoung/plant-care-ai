"""User-initiated calendar export. No account access or background notifications."""
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from zoneinfo import ZoneInfo


MAX_GOOGLE_LINK_BYTES = 8000  # App budget for a shareable GET link; never truncate conditions to fit.


class CalendarLinkTooLong(ValueError):
    pass


def _event(schedule, ai_details=None):
    start = datetime.fromisoformat(f"{schedule['due_on']}T{schedule['due_time']}").replace(tzinfo=ZoneInfo('Asia/Seoul'))
    title = f"{schedule['plant_name']} · {schedule['title']}"
    sections = []
    if schedule.get('source_suggestion_id') is not None:
        if not ai_details:
            raise ValueError('원래 AI 제안과 확인 조건을 찾을 수 없어 캘린더를 준비하지 못했어요. 기록을 새로고침해 주세요.')
        sections.append(ai_details)
    if schedule['notes']:
        sections.append('[추가 메모]\n' + schedule['notes'])
    sections.append('식물 상태를 확인한 뒤 필요한 관리만 해 주세요. '
                    '이 일정은 앱과 자동 동기화되지 않습니다. 변경·취소 시 캘린더도 직접 수정해 주세요.')
    details = '\n\n'.join(sections)
    return start.astimezone(timezone.utc), title, details


def google_calendar_url(schedule, *, ai_details=None):
    start, title, details = _event(schedule, ai_details)
    stamp = lambda value: value.strftime('%Y%m%dT%H%M%SZ')
    url = 'https://calendar.google.com/calendar/render?' + urlencode({
        'action': 'TEMPLATE', 'text': title, 'dates': f'{stamp(start)}/{stamp(start + timedelta(minutes=15))}',
        'details': details, 'ctz': 'Asia/Seoul'})
    if len(url.encode('utf-8')) > MAX_GOOGLE_LINK_BYTES:
        raise CalendarLinkTooLong('설명이 길어 캘린더 파일로 전체 내용을 가져와 주세요.')
    return url


def _escape(value):
    return str(value).replace('\\', '\\\\').replace('\r\n', '\n').replace('\r', '\n').replace('\n', '\\n').replace(';', '\\;').replace(',', '\\,')


def _fold(line):
    parts, current = [], ''
    for char in line:
        if len((current + char).encode('utf-8')) > 75:
            parts.append(current)
            current = ' '
        current += char
    return '\r\n'.join([*parts, current])


def calendar_ics(schedule, *, ai_details=None):
    if schedule['status'] != 'pending':
        raise ValueError('예정된 일정만 캘린더에 추가할 수 있어요.')
    start, title, details = _event(schedule, ai_details)
    stamp = lambda value: value.strftime('%Y%m%dT%H%M%SZ')
    updated = datetime.fromisoformat(schedule['updated_at']).astimezone(timezone.utc)
    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Plant Care AI//Care Calendar//KO',
             'CALSCALE:GREGORIAN', 'METHOD:PUBLISH', 'BEGIN:VEVENT',
             f"UID:{schedule['calendar_uid']}@plant-care-ai", f"SEQUENCE:{schedule['revision']}",
             f'DTSTAMP:{stamp(updated)}', f'DTSTART:{stamp(start)}', f'DTEND:{stamp(start + timedelta(minutes=15))}',
             f'SUMMARY:{_escape(title)}', f'DESCRIPTION:{_escape(details)}', 'BEGIN:VALARM', 'ACTION:DISPLAY',
             'TRIGGER:-PT10M', f'DESCRIPTION:{_escape(title)}', 'END:VALARM', 'END:VEVENT', 'END:VCALENDAR']
    return ('\r\n'.join(_fold(line) for line in lines) + '\r\n').encode('utf-8')
