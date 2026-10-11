"""도시 대표 좌표의 실외 모델 날씨. GPS나 주소를 수집하지 않는다."""

from datetime import datetime, timedelta, timezone
import json
import math
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

REGIONS = {
    'seoul': ('서울', 37.57, 126.98),
    'incheon': ('인천', 37.46, 126.71),
    'suwon': ('수원', 37.26, 127.03),
    'chuncheon': ('춘천', 37.88, 127.73),
    'gangneung': ('강릉', 37.75, 128.90),
    'daejeon': ('대전', 36.35, 127.38),
    'cheongju': ('청주', 36.64, 127.49),
    'jeonju': ('전주', 35.82, 127.15),
    'gwangju': ('광주', 35.16, 126.85),
    'suncheon': ('순천', 34.95, 127.49),
    'daegu': ('대구', 35.87, 128.60),
    'ulsan': ('울산', 35.54, 129.31),
    'busan': ('부산', 35.18, 129.08),
    'changwon': ('창원', 35.23, 128.68),
    'jeju': ('제주시', 33.50, 126.53),
}
SOURCE_URL = 'https://open-meteo.com/'
LIMITATION = '도시 대표 좌표의 실외 모델 추정치입니다. 실내 온습도·화분의 흙 수분·실제 광량을 측정한 값이 아닙니다.'
VARIABLES = {
    'temperature_2m': ('temperature_c', '°C', -90, 65),
    'relative_humidity_2m': ('relative_humidity_percent', '%', 0, 100),
    'precipitation': ('precipitation_mm', 'mm', 0, 1000),
    'wind_speed_10m': ('wind_speed_kmh', 'km/h', 0, 500),
}

class WeatherError(Exception):
    """원문 응답을 노출하지 않는 사용자용 오류."""

def fetch_weather(region_id: str) -> dict:
    if region_id not in REGIONS:
        raise WeatherError('날씨를 참고할 지역을 선택해 주세요.')
    _, latitude, longitude = REGIONS[region_id]
    parameters = dict(latitude=latitude, longitude=longitude, current=','.join(VARIABLES),
                      timezone='UTC', forecast_days=1, temperature_unit='celsius',
                      wind_speed_unit='kmh', precipitation_unit='mm')
    request = Request('https://api.open-meteo.com/v1/forecast?' + urlencode(parameters),
                      headers={'User-Agent': 'PlantCareAI/1.0 (educational prototype)'})
    try:
        with urlopen(request, timeout=10) as response:
            raw = response.read(128_001)
        if len(raw) > 128_000:
            raise ValueError('oversized weather response')
        return weather_snapshot(json.loads(raw), region_id, datetime.now(timezone.utc))
    except HTTPError as error:
        if error.code == 429:
            raise WeatherError('날씨 요청 한도에 도달했어요. 잠시 후 다시 확인해 주세요.') from None
        raise WeatherError('날씨 서비스에 연결하지 못했어요. 날씨 없이도 분석할 수 있어요.') from None
    except (URLError, TimeoutError, OSError):
        raise WeatherError('날씨를 가져오지 못했어요. 인터넷 연결을 확인해 주세요.') from None
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        raise WeatherError('날씨 값이나 시각을 확인할 수 없어 이번 분석에서 제외했어요.') from None

def weather_snapshot(payload: dict, region_id: str, fetched_at: datetime) -> dict:
    """단위·시각·수치 검증 후 저장할 작은 스냅샷만 반환한다."""
    if payload.get('utc_offset_seconds') != 0 or payload.get('error'):
        raise ValueError('unexpected timezone or error response')
    current = payload['current']
    units = payload['current_units']
    measured = datetime.fromisoformat(current['time'])
    if measured.tzinfo is None:
        measured = measured.replace(tzinfo=timezone.utc)
    measured = measured.astimezone(timezone.utc)
    fetched_at = fetched_at.astimezone(timezone.utc)
    age = fetched_at - measured
    if not -timedelta(minutes=5) <= age <= timedelta(minutes=90):
        raise ValueError('stale or future weather')
    interval = current['interval']
    if type(interval) is not int or not 60 <= interval <= 3600 or interval % 60:
        raise ValueError('invalid interval')
    values = {}
    for variable, (field, unit, minimum, maximum) in VARIABLES.items():
        value = current[variable]
        if units[variable] != unit or type(value) not in (int, float) or not math.isfinite(value) or not minimum <= value <= maximum:
            raise ValueError('invalid unit or value')
        values[field] = value
    return dict(status='available', region_id=region_id, region=REGIONS[region_id][0],
                source='Open-Meteo', source_url=SOURCE_URL, kind='outdoor_weather_model',
                valid_at=measured.isoformat(), fetched_at=fetched_at.isoformat(),
                precipitation_interval_seconds=interval, limitation=LIMITATION, **values)

def unavailable_weather(region_id: str) -> dict:
    return dict(status='unavailable', region_id=region_id, region=REGIONS[region_id][0],
                source='Open-Meteo', source_url=SOURCE_URL,
                fetched_at=datetime.now(timezone.utc).isoformat(),
                limitation='날씨를 가져오지 못했으므로 날씨 수치를 추정하거나 이전 날씨를 현재 값으로 사용하지 마세요.')
