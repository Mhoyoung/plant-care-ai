"""User-initiated calendar export. No account access or background notifications."""
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from zoneinfo import ZoneInfo


def _event(schedule):
    start = datetime.fromisoformat(f"{schedule['due_on']}T{schedule['due_time']}").replace(tzinfo=ZoneInfo('Asia/Seoul'))
    title = f"{schedule['plant_name']} · {schedule['title']}"
    details = (schedule['notes'] + '\n\n식물 상태를 확인한 뒤 필요한 관리만 해 주세요. '
               '이 일정은 앱과 자동 동기화되지 않습니다. 변경·취소 시 캘린더도 직접 수정해 주세요.')
    return start.astimezone(timezone.utc), title, details


def google_calendar_url(schedule):
    start, title, details = _event(schedule)
    stamp = lambda value: value.strftime('%Y%m%dT%H%M%SZ')
    return 'https://calendar.google.com/calendar/render?' + urlencode({
        'action': 'TEMPLATE', 'text': title, 'dates': f'{stamp(start)}/{stamp(start + timedelta(minutes=15))}',
        'details': details, 'ctz': 'Asia/Seoul'})


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


def calendar_ics(schedule):
    if schedule['status'] != 'pending':
        raise ValueError('예정된 일정만 캘린더에 추가할 수 있어요.')
    start, title, details = _event(schedule)
    stamp = lambda value: value.strftime('%Y%m%dT%H%M%SZ')
    updated = datetime.fromisoformat(schedule['updated_at']).astimezone(timezone.utc)
    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Plant Care AI//Care Calendar//KO',
             'CALSCALE:GREGORIAN', 'METHOD:PUBLISH', 'BEGIN:VEVENT',
             f"UID:{schedule['calendar_uid']}@plant-care-ai", f"SEQUENCE:{schedule['revision']}",
             f'DTSTAMP:{stamp(updated)}', f'DTSTART:{stamp(start)}', f'DTEND:{stamp(start + timedelta(minutes=15))}',
             f'SUMMARY:{_escape(title)}', f'DESCRIPTION:{_escape(details)}', 'BEGIN:VALARM', 'ACTION:DISPLAY',
             'TRIGGER:-PT10M', f'DESCRIPTION:{_escape(title)}', 'END:VALARM', 'END:VEVENT', 'END:VCALENDAR']
    return ('\r\n'.join(_fold(line) for line in lines) + '\r\n').encode('utf-8')
