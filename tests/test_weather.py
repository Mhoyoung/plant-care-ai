from copy import deepcopy
from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse

from streamlit.testing.v1 import AppTest
from plant_care.gemini import analysis_context, SYSTEM
from plant_care.storage import PlantStore
from plant_care.weather import fetch_weather, weather_snapshot, WeatherError
from test_app import click_button, APP_PATH
from test_gemini import RESULT


def payload_at(now=None):
    now = now or datetime.now(timezone.utc)
    return {
        'utc_offset_seconds': 0,
        'current': dict(time=now.replace(tzinfo=None).isoformat(timespec='minutes'), interval=900,
                        temperature_2m=24.5, relative_humidity_2m=65, precipitation=0.2, wind_speed_10m=8.1),
        'current_units': dict(temperature_2m='°C', relative_humidity_2m='%', precipitation='mm', wind_speed_10m='km/h'),
    }


class WeatherTests(unittest.TestCase):
    def test_request_sends_only_city_coordinates_and_validates_snapshot(self):
        with patch('plant_care.weather.urlopen', return_value=BytesIO(json.dumps(payload_at()).encode())) as api:
            snapshot = fetch_weather('seoul')
        api.assert_called_once()
        request = api.call_args.args[0]
        query = parse_qs(urlparse(request.full_url).query)
        self.assertEqual(query['latitude'], ['37.57'])
        self.assertEqual(query['timezone'], ['UTC'])
        self.assertNotIn('apikey', query)
        self.assertNotIn('notes', query)
        self.assertEqual(snapshot['kind'], 'outdoor_weather_model')
        self.assertEqual(snapshot['relative_humidity_percent'], 65)
        self.assertEqual(snapshot['precipitation_interval_seconds'], 900)
        self.assertTrue(snapshot['valid_at'].endswith('+00:00'))
        self.assertIn('실내', snapshot['limitation'])
        self.assertIn('실외 날씨를 실내 온습도', SYSTEM)

    def test_null_boolean_invalid_units_stale_and_future_data_are_rejected(self):
        now = datetime(2026, 10, 12, 3, 30, tzinfo=timezone.utc)
        base = payload_at(now)
        changes = [
            ('current', 'temperature_2m', None), ('current', 'relative_humidity_2m', True),
            ('current', 'relative_humidity_2m', 101), ('current', 'wind_speed_10m', float('nan')),
            ('current_units', 'temperature_2m', '°F'), ('current', 'interval', 0),
            ('current', 'time', (now - timedelta(hours=2)).isoformat()),
            ('current', 'time', (now + timedelta(hours=1)).isoformat()),
        ]
        for section, key, value in changes:
            bad = deepcopy(base)
            bad[section][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                weather_snapshot(bad, 'seoul', now)

    def test_network_errors_and_bad_json_are_sanitized_without_retry(self):
        errors = [URLError('private transport details'), TimeoutError('private timeout'),
                  HTTPError('https://example.test', 429, 'private body', {}, None)]
        for error in errors:
            with patch('plant_care.weather.urlopen', side_effect=error) as api, self.assertRaises(WeatherError) as caught:
                fetch_weather('seoul')
            api.assert_called_once()
            self.assertNotIn('private', str(caught.exception))
        for raw in (b'{}', b'[]', b'invalid', b'x' * 128_001):
            with patch('plant_care.weather.urlopen', return_value=BytesIO(raw)), self.assertRaises(WeatherError):
                fetch_weather('seoul')
        with patch('plant_care.weather.urlopen') as api, self.assertRaises(WeatherError):
            fetch_weather('not-a-city')
        api.assert_not_called()

    def test_region_persistence_is_per_plant_and_old_analysis_is_immutable(self):
        with tempfile.TemporaryDirectory() as folder:
            store = PlantStore(folder)
            plant = store.add_plant('첫 식물')
            other = store.add_plant('다른 식물')
            original = analysis_context(store, plant, '이전 질문', False)
            store.add_analysis(plant, 'test', original, RESULT, {})
            store.set_weather_region(plant, 'seoul')
            reopened = PlantStore(folder)
            self.assertEqual(reopened.get_weather_region(plant), 'seoul')
            self.assertIsNone(reopened.get_weather_region(other))
            self.assertEqual(reopened.list_analyses(plant)[0]['input'], original)
            self.assertNotIn('outdoor_weather', original)
            self.assertEqual(reopened.export_plant(plant)['weather_region'], 'seoul')
            with self.assertRaises(ValueError):
                reopened.set_weather_region(plant, 'arbitrary-address')
            with self.assertRaises(ValueError):
                reopened.set_weather_region(999, 'seoul')
            reopened.set_weather_region(plant, None)
            self.assertIsNone(PlantStore(folder).get_weather_region(plant))


class WeatherAppTests(unittest.TestCase):
    def test_manual_preview_and_analysis_persist_the_exact_weather_without_extra_calls(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'PLANT_CARE_DATA_DIR': folder}), \
                patch('plant_care.ai_ui.api_key', return_value='test-key'), \
                patch('plant_care.ai_ui.analyze', return_value=(RESULT, {})) as ai, \
                patch('plant_care.ai_ui.fetch_weather') as weather, \
                patch('plant_care.weather_ui.fetch_weather') as preview:
            store = PlantStore(folder)
            plant = store.add_plant('테스트 식물')
            snapshot = weather_snapshot(payload_at(), 'seoul', datetime.now(timezone.utc))
            weather.return_value = snapshot
            preview.return_value = snapshot
            app = AppTest.from_file(str(APP_PATH)).run(timeout=15)
            app.selectbox(key='selected_plant').select(plant).run()
            app.selectbox(key=f'weather_region_{plant}').select('seoul')
            click_button(app, '지역 저장')
            weather.assert_not_called()
            preview.assert_not_called()
            click_button(app, '지역 날씨 확인')
            preview.assert_called_once_with('seoul')
            self.assertTrue(any(metric.label == '실외 기온' for metric in app.metric))
            app.text_area(key='ai_state').set_value('잎 상태가 궁금해요')
            app.checkbox(key=f'ai_weather_{plant}').check()
            click_button(app, 'Gemini로 분석')
            weather.assert_not_called()
            ai.assert_not_called()
            app.checkbox(key='ai_consent').check()
            click_button(app, 'Gemini로 분석')
            self.assertEqual(len(app.exception), 0)
            weather.assert_called_once_with('seoul')
            ai.assert_called_once()
            self.assertEqual(ai.call_args.args[1]['outdoor_weather'], snapshot)
            self.assertEqual(store.list_analyses(plant)[0]['input']['outdoor_weather'], snapshot)
            store.set_weather_region(plant, 'busan')
            relaunched = AppTest.from_file(str(APP_PATH)).run(timeout=15)
            relaunched.selectbox(key='selected_plant').select(plant).run()
            self.assertEqual(relaunched.selectbox(key=f'weather_region_{plant}').value, 'busan')
            self.assertEqual(store.list_analyses(plant)[0]['input']['outdoor_weather']['region'], '서울')
            weather.assert_called_once()
            preview.assert_called_once()
            ai.assert_called_once()

    def test_weather_failure_continues_analysis_with_explicit_unavailable_snapshot(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'PLANT_CARE_DATA_DIR': folder}), \
                patch('plant_care.ai_ui.api_key', return_value='test-key'), \
                patch('plant_care.ai_ui.analyze', return_value=(RESULT, {})) as ai, \
                patch('plant_care.ai_ui.fetch_weather', side_effect=WeatherError('날씨 연결 실패')) as weather:
            store = PlantStore(folder)
            plant = store.add_plant('테스트 식물')
            store.set_weather_region(plant, 'seoul')
            app = AppTest.from_file(str(APP_PATH)).run(timeout=15)
            app.selectbox(key='selected_plant').select(plant).run()
            app.text_area(key='ai_state').set_value('상태 확인')
            app.checkbox(key=f'ai_weather_{plant}').check()
            app.checkbox(key='ai_consent').check()
            click_button(app, 'Gemini로 분석')
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(len(app.warning), 1)
            weather.assert_called_once()
            self.assertEqual(ai.call_args.args[1]['outdoor_weather']['status'], 'unavailable')
            self.assertNotIn('temperature_c', store.list_analyses(plant)[0]['input']['outdoor_weather'])

    def test_opt_out_and_no_region_never_call_weather(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'PLANT_CARE_DATA_DIR': folder}), \
                patch('plant_care.ai_ui.api_key', return_value='test-key'), \
                patch('plant_care.ai_ui.analyze', return_value=(RESULT, {})) as ai, \
                patch('plant_care.ai_ui.fetch_weather') as weather:
            store = PlantStore(folder)
            plant = store.add_plant('테스트 식물')
            app = AppTest.from_file(str(APP_PATH)).run(timeout=15)
            app.selectbox(key='selected_plant').select(plant).run()
            self.assertTrue(app.checkbox(key=f'ai_weather_{plant}').disabled)
            app.text_area(key='ai_state').set_value('날씨 없이 확인')
            app.checkbox(key='ai_consent').check()
            click_button(app, 'Gemini로 분석')
            store.set_weather_region(plant, 'seoul')
            app.run()
            click_button(app, 'Gemini로 분석')
            weather.assert_not_called()
            self.assertEqual(ai.call_count, 2)
            self.assertNotIn('outdoor_weather', ai.call_args.args[1])


if __name__ == '__main__':
    unittest.main()
