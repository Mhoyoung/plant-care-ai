"""사용자가 선택한 도시와 수동 조회한 날씨를 표시한다."""
from datetime import datetime
import sqlite3
from zoneinfo import ZoneInfo
import streamlit as st
from .weather import REGIONS, WeatherError, fetch_weather
from .cloud_store import CloudError

def show_weather(snapshot):
    if snapshot.get('status') != 'available':
        st.caption('이번 분석에는 지역 날씨를 참고하지 못했어요.')
        return
    timestamp = datetime.fromisoformat(snapshot['valid_at']).astimezone(ZoneInfo('Asia/Seoul'))
    st.write(f"**{snapshot['region']} · 실외 날씨 참고**")
    columns = st.columns(3)
    columns[0].metric('실외 기온', f"{snapshot['temperature_c']:g} °C")
    columns[1].metric('실외 습도', f"{snapshot['relative_humidity_percent']:g} %")
    columns[2].metric('실외 바람', f"{snapshot['wind_speed_kmh']:g} km/h")
    minutes = snapshot['precipitation_interval_seconds'] // 60
    st.caption(f"{timestamp:%Y.%m.%d %H:%M} 기준 · 직전 {minutes}분 강수량 {snapshot['precipitation_mm']:g} mm")
    st.caption(snapshot['limitation'])
    st.caption('날씨 출처: [Open-Meteo](https://open-meteo.com/) · [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)')

def region_settings(store, plant_id):
    region = store.get_weather_region(plant_id)
    with st.expander('지역 날씨 함께 살펴보기', expanded=True):
        st.caption('식물을 키우는 곳과 가까운 도시를 선택하세요. 정확한 주소나 GPS 위치는 사용하지 않아요.')
        with st.form(f'weather_region_form_{plant_id}'):
            options = [None, *REGIONS]
            chosen = st.selectbox('날씨 참고 지역', options, index=options.index(region),
                                  format_func=lambda value: REGIONS[value][0] if value else '지역 선택 안 함',
                                  key=f'weather_region_{plant_id}')
            saved = st.form_submit_button('지역 저장')
        if saved:
            try:
                store.set_weather_region(plant_id, chosen)
            except CloudError as error:
                st.error(str(error))
            except (ValueError, OSError, sqlite3.Error):
                st.error('지역을 저장하지 못했어요. 다시 시도해 주세요.')
            else:
                region = chosen
                st.session_state.pop(f'weather_preview_{plant_id}', None)
                st.success('날씨 참고 지역을 저장했어요.' if region else '날씨 참고 지역을 해제했어요.')
        st.caption('날씨 확인을 누르면 선택한 도시의 대표 좌표를 Open-Meteo로 보냅니다. 화면을 열거나 지역을 저장할 때는 날씨를 요청하지 않아요.')
        if st.button('지역 날씨 확인', key=f'weather_check_{plant_id}', disabled=region is None):
            try:
                with st.spinner('지역 날씨를 확인하고 있어요…'):
                    st.session_state[f'weather_preview_{plant_id}'] = fetch_weather(region)
            except WeatherError as error:
                st.session_state.pop(f'weather_preview_{plant_id}', None)
                st.warning(str(error))
        preview = st.session_state.get(f'weather_preview_{plant_id}')
        if preview and preview['region_id'] == region:
            show_weather(preview)
            st.caption('확인 버튼을 누른 시점의 날씨예요. AI 분석에 포함할 때는 새로 확인합니다.')
    return region
