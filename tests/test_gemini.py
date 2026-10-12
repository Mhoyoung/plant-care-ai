from datetime import date
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from PIL import Image

from plant_care.gemini import AnalysisError, MODEL, analyze, analysis_context
from plant_care.storage import PlantStore

RESULT = {"summary": "기록을 참고한 제안", "observations": ["최근 물주기 기록이 있습니다."],
          "checks": ["흙 상태를 확인하세요."], "actions": ["흙이 젖었다면 물을 더 주지 마세요."],
          "uncertainty": "사진만으로 흙 수분을 판단할 수 없습니다."}


def response_bytes(result=RESULT, status="completed"):
    return json.dumps({"status": status, "steps": [{"type": "model_output", "content": [
        {"type": "text", "text": json.dumps(result)}]}], "usage": {"total_tokens": 100}}).encode()


class GeminiTests(unittest.TestCase):
    def test_429_codes_are_distinguished_without_exposing_raw_message_or_retrying(self):
        for code, text in (("rate_limit_exceeded", "분당·초당"), ("quota_exceeded", "일일"), ("too_many_requests", "집중")):
            payload = json.dumps({"error": {"code": code, "message": "private key and project information"}}).encode()
            error = HTTPError("https://example.invalid", 429, "private detail", {"Retry-After": "45"}, BytesIO(payload))
            with self.subTest(code=code), patch("plant_care.gemini.urlopen", side_effect=error) as http:
                with self.assertRaises(AnalysisError) as raised:
                    analyze("test-secret-key", {})
                safe = raised.exception
                self.assertEqual(safe.http_status, 429)
                self.assertEqual(safe.error_code, code)
                self.assertEqual(safe.retry_after_seconds, 45)
                self.assertIn(text, str(safe))
                self.assertNotIn("private", str(safe))
                self.assertNotIn("test-secret-key", str(safe))
                self.assertEqual("45초" in str(safe), code != "quota_exceeded")
                self.assertTrue(error.fp.closed)
                http.assert_called_once()

    def test_unknown_malformed_oversized_429_does_not_guess_daily_or_free_limit(self):
        for payload in (b"invalid", b"[]", b'null', b'{"error":{"code":429,"message":"private secret"}}',
                        b'{"error":{"code":"private secret"}}', b'{"error":{"code":[]}}', b'x' * 65_537):
            for header in ("private secret", "99999999999", "-1", "86401", "Wed, 21 Oct 2026 07:28:00 GMT"):
                error = HTTPError("https://example.invalid", 429, "private detail", {"Retry-After": header}, BytesIO(payload))
                with self.subTest(payload=payload[:30], header=header), patch("plant_care.gemini.urlopen", side_effect=error) as http:
                    with self.assertRaises(AnalysisError) as raised:
                        analyze("test-secret-key", {})
                    self.assertIsNone(raised.exception.error_code)
                    self.assertIsNone(raised.exception.retry_after_seconds)
                    self.assertIn("세부 원인은 확인되지", str(raised.exception))
                    self.assertNotIn("일일 할당량에 도달", str(raised.exception))
                    self.assertNotIn("무료", str(raised.exception))
                    self.assertNotIn("private", str(raised.exception))
                    http.assert_called_once()

    def test_missing_key_never_calls_network(self):
        with patch("plant_care.gemini.urlopen") as http, self.assertRaises(AnalysisError):
            analyze("", {})
        http.assert_not_called()

    def test_request_uses_header_key_photo_structured_output_and_no_server_storage(self):
        image = Image.new("RGB", (20, 20), "green")
        buffer = BytesIO()
        image.save(buffer, "PNG")
        with patch("plant_care.gemini.urlopen") as http:
            http.return_value.__enter__.return_value.read.return_value = response_bytes()
            result, usage = analyze("local-test-key", {"has_photo": True}, buffer.getvalue())
        self.assertEqual(result, RESULT)
        self.assertEqual(usage, {"total_tokens": 100})
        http.assert_called_once()
        request = http.call_args.args[0]
        payload = json.loads(request.data)
        self.assertNotIn("local-test-key", request.full_url)
        self.assertEqual(request.get_header("X-goog-api-key"), "local-test-key")
        self.assertFalse(payload["store"])
        self.assertEqual(payload["model"], MODEL)
        self.assertEqual(payload["input"][1]["mime_type"], "image/jpeg")
        self.assertEqual(payload["response_format"]["mime_type"], "application/json")

    def test_bad_responses_are_rejected(self):
        for raw in (b"invalid", response_bytes({}, "incomplete"), response_bytes({}),
                    response_bytes({**RESULT, "actions": "not a list"}),
                    response_bytes({**RESULT, "summary": ""})):
            with self.subTest(raw=raw), patch("plant_care.gemini.urlopen") as http:
                http.return_value.__enter__.return_value.read.return_value = raw
                with self.assertRaises(AnalysisError):
                    analyze("test-key", {})

    def test_http_errors_hide_response_and_do_not_retry(self):
        for code in (400, 401, 403, 404, 429, 500):
            error = HTTPError("https://example.invalid", code, "secret-error-detail", {}, None)
            with self.subTest(code=code), patch("plant_care.gemini.urlopen", side_effect=error) as http:
                with self.assertRaises(AnalysisError) as raised:
                    analyze("test-key", {})
                self.assertNotIn("secret-error-detail", str(raised.exception))
                if code == 429:
                    self.assertIn("한도", str(raised.exception))
                http.assert_called_once()

    def test_timeout_and_invalid_photo_do_not_produce_results(self):
        for error in (TimeoutError(), URLError("private details")):
            with patch("plant_care.gemini.urlopen", side_effect=error), self.assertRaises(AnalysisError):
                analyze("test-key", {})
        with patch("plant_care.gemini.urlopen") as http, self.assertRaises(ValueError):
            analyze("test-key", {}, b"invalid photo")
        http.assert_not_called()

    def test_existing_records_survive_new_table_and_analysis_persists_with_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            store = PlantStore(folder)
            plant = store.add_plant("몬스테라", notes="처음 상태")
            other = store.add_plant("다른 식물")
            store.add_log(plant, "watering", date.today(), notes="첫 물주기")
            store.add_log(other, "watering", date.today(), notes="다른 식물 메모")
            context = analysis_context(store, plant, "잎이 처져요", False)
            self.assertNotIn("photo_path", json.dumps(context))
            self.assertNotIn("다른 식물 메모", json.dumps(context, ensure_ascii=False))
            store.add_analysis(plant, MODEL, context, RESULT, {"total_tokens": 100})
            store.add_log(plant, "observation", date.today(), notes="나중에 추가한 기록")
            reopened = PlantStore(folder)
            analysis = reopened.list_analyses(plant)[0]
            self.assertEqual(analysis["result"], RESULT)
            self.assertEqual(len(analysis["input"]["recent_care_logs"]), 1)
            self.assertEqual(reopened.list_analyses(other), [])
            self.assertEqual(len(reopened.list_logs(plant)), 2)
            self.assertEqual(reopened.export_plant(plant)["ai_analyses"][0]["usage"]["total_tokens"], 100)
            self.assertNotIn("test-key", Path(reopened.db_path).read_bytes().decode("utf-8", errors="ignore"))
