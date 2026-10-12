"""관리 기록의 날짜는 서버 위치와 관계없이 한국 시간을 기준으로 한다."""
from datetime import datetime
from zoneinfo import ZoneInfo


def today_in_seoul():
    return datetime.now(ZoneInfo("Asia/Seoul")).date()
