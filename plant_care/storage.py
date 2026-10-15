"""SQLite 저장소. Streamlit 없이도 사용할 수 있다."""

from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
import sqlite3
import json
from zoneinfo import ZoneInfo
from uuid import uuid4
from .time_utils import today_in_seoul

from .constants import CARE_TYPES, OUTCOMES
from .media import save_photo
from .weather import REGIONS


def _text(value: str, label: str, maximum: int, required: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label}은 글자로 입력해 주세요.")
    value = value.strip()
    if required and not value:
        raise ValueError(f"{label}을 입력해 주세요.")
    if len(value) > maximum:
        raise ValueError(f"{label}은 {maximum}자 이내로 입력해 주세요.")
    return value


class PlantStore:
    backend = 'local'

    def __init__(self, data_root: Path | str):
        self.data_root = Path(data_root).resolve()
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_root / "plants.db"
        with self._connection() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS plant_weather_regions (
                    plant_id INTEGER PRIMARY KEY REFERENCES plants(id),
                    region_id TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS plants (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL CHECK(length(trim(name)) > 0),
                    species TEXT NOT NULL DEFAULT '',
                    location TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT '',
                    photo_path TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS care_logs (
                    id INTEGER PRIMARY KEY,
                    plant_id INTEGER NOT NULL REFERENCES plants(id),
                    kind TEXT NOT NULL CHECK(kind IN ('watering', 'fertilizing', 'repotting', 'observation')),
                    occurred_on TEXT NOT NULL,
                    notes TEXT NOT NULL DEFAULT '',
                    outcome TEXT NOT NULL DEFAULT 'unrecorded'
                        CHECK(outcome IN ('unrecorded', 'improved', 'unchanged', 'worse')),
                    photo_path TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS care_logs_plant_date
                    ON care_logs(plant_id, occurred_on DESC, id DESC);
                CREATE TABLE IF NOT EXISTS ai_analyses (
                    id INTEGER PRIMARY KEY,
                    plant_id INTEGER NOT NULL REFERENCES plants(id),
                    model TEXT NOT NULL,
                    input_json TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    usage_json TEXT NOT NULL,
                    photo_path TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ai_analyses_plant
                    ON ai_analyses(plant_id, id DESC);
                CREATE TABLE IF NOT EXISTS ai_suggestions (
                    id INTEGER PRIMARY KEY,
                    analysis_id INTEGER NOT NULL REFERENCES ai_analyses(id),
                    action_index INTEGER NOT NULL CHECK(action_index >= 0),
                    suggestion_text TEXT NOT NULL,
                    UNIQUE(analysis_id, action_index)
                );
                CREATE TABLE IF NOT EXISTS care_schedules (
                    id INTEGER PRIMARY KEY,
                    plant_id INTEGER NOT NULL REFERENCES plants(id),
                    title TEXT NOT NULL CHECK(length(trim(title)) > 0),
                    kind TEXT NOT NULL CHECK(kind IN ('watering', 'fertilizing', 'repotting', 'observation')),
                    due_on TEXT NOT NULL,
                    due_time TEXT NOT NULL,
                    notes TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','completed','cancelled')),
                    completed_log_id INTEGER UNIQUE REFERENCES care_logs(id),
                    calendar_uid TEXT NOT NULL UNIQUE,
                    revision INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    CHECK((status = 'completed') = (completed_log_id IS NOT NULL))
                );
                CREATE INDEX IF NOT EXISTS schedules_due ON care_schedules(status, due_on, due_time);
            """)
            # Additive migration: old logs remain unlinked; original snapshots are unchanged.
            columns = {row['name'] for row in connection.execute('PRAGMA table_info(care_logs)')}
            if 'suggestion_id' not in columns:
                connection.execute('ALTER TABLE care_logs ADD COLUMN suggestion_id INTEGER REFERENCES ai_suggestions(id)')
            if 'link_type' not in columns:
                connection.execute("ALTER TABLE care_logs ADD COLUMN link_type TEXT CHECK(link_type IN ('execution', 'outcome'))")
            connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS suggestion_execution_once "
                               "ON care_logs(suggestion_id) WHERE link_type = 'execution'")
            connection.execute('CREATE INDEX IF NOT EXISTS care_logs_suggestion ON care_logs(suggestion_id, occurred_on, id)')
            for row in connection.execute('SELECT a.id, a.result_json FROM ai_analyses a '
                                          'WHERE NOT EXISTS (SELECT 1 FROM ai_suggestions s WHERE s.analysis_id = a.id)'):
                self._insert_suggestions(connection, row['id'], json.loads(row['result_json']))

    @staticmethod
    def _insert_suggestions(connection, analysis_id, result):
        actions = result.get('actions', []) if isinstance(result, dict) else []
        if not isinstance(actions, list):
            return
        for index, text in enumerate(actions):
            if isinstance(text, str) and text.strip():
                connection.execute('INSERT OR IGNORE INTO ai_suggestions(analysis_id, action_index, suggestion_text) '
                                   'VALUES (?, ?, ?)', (analysis_id, index, text))

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def photo_path(self, relative: str) -> Path:
        target = (self.data_root / relative).resolve()
        if not target.is_relative_to((self.data_root / "photos").resolve()):
            raise ValueError("사진 경로가 올바르지 않아요.")
        return target

    def _remove_photo(self, relative: str | None):
        if relative:
            self.photo_path(relative).unlink(missing_ok=True)

    def read_photo(self, relative: str) -> bytes:
        return self.photo_path(relative).read_bytes()

    def _save_photo(self, photo: bytes | None) -> str | None:
        return save_photo(photo, self.data_root)

    def add_plant(self, name: str, species: str = "", location: str = "", notes: str = "", photo: bytes | None = None) -> int:
        name = _text(name, "식물 이름", 100, required=True)
        species = _text(species, "종류", 100)
        location = _text(location, "장소", 200)
        notes = _text(notes, "메모", 3000)
        photo_path = self._save_photo(photo)
        try:
            with self._connection() as connection:
                cursor = connection.execute(
                    "INSERT INTO plants(name, species, location, notes, photo_path, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (name, species, location, notes, photo_path, datetime.now(timezone.utc).isoformat()),
                )
                plant_id = cursor.lastrowid
        except Exception:
            self._remove_photo(photo_path)
            raise
        return plant_id

    def list_plants(self) -> list[dict]:
        with self._connection() as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM plants ORDER BY id DESC")]

    def get_plant(self, plant_id: int) -> dict:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM plants WHERE id = ?", (plant_id,)).fetchone()
        if row is None:
            raise ValueError("등록된 식물을 찾을 수 없어요.")
        return dict(row)

    def add_log(self, plant_id: int, kind: str, occurred_on: date | str, notes: str = "", outcome: str = "unrecorded", photo: bytes | None = None,
                suggestion_id: int | None = None, link_type: str | None = None) -> int:
        self.get_plant(plant_id)
        if kind not in CARE_TYPES:
            raise ValueError("관리 종류를 선택해 주세요.")
        if outcome not in OUTCOMES:
            raise ValueError("관찰 결과를 선택해 주세요.")
        if (suggestion_id is None) != (link_type is None) or (link_type is not None and link_type not in ('execution', 'outcome')):
            raise ValueError("연결할 AI 제안과 기록 종류를 함께 선택해 주세요.")
        notes = _text(notes, "실제로 한 관리" if link_type == 'execution' else "메모", 3000,
                      required=link_type == 'execution')
        if link_type == 'execution' and outcome != 'unrecorded':
            raise ValueError("실행 후 상태는 별도의 경과 기록으로 남겨 주세요.")
        if link_type == 'outcome' and (kind != 'observation' or (outcome == 'unrecorded' and not notes and photo is None)):
            raise ValueError("관찰한 상태나 메모·사진을 남겨 주세요. 경과는 상태 관찰로 저장합니다.")
        try:
            log_date = date.fromisoformat(str(occurred_on))
        except (TypeError, ValueError) as error:
            raise ValueError("날짜를 올바르게 입력해 주세요.") from error
        if log_date > today_in_seoul():
            raise ValueError("오늘까지의 관리 기록만 저장할 수 있어요.")
        photo_path = None
        try:
            with self._connection() as connection:
                if suggestion_id is not None:
                    self._validate_link(connection, plant_id, suggestion_id, link_type, log_date)
                photo_path = self._save_photo(photo)
                cursor = connection.execute(
                    "INSERT INTO care_logs(plant_id, kind, occurred_on, notes, outcome, photo_path, created_at, suggestion_id, link_type) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (plant_id, kind, log_date.isoformat(), notes, outcome, photo_path, datetime.now(timezone.utc).isoformat(), suggestion_id, link_type),
                )
                log_id = cursor.lastrowid
        except Exception:
            self._remove_photo(photo_path)
            raise
        return log_id

    def list_logs(self, plant_id: int, limit: int | None = None) -> list[dict]:
        query = ("SELECT l.*, s.suggestion_text FROM care_logs l LEFT JOIN ai_suggestions s ON s.id = l.suggestion_id "
                 "WHERE l.plant_id = ? ORDER BY l.occurred_on DESC, l.id DESC")
        parameters = [plant_id]
        if limit is not None:
            if not isinstance(limit, int) or not 1 <= limit <= 100:
                raise ValueError("기록 개수는 1~100 사이로 선택해 주세요.")
            query += " LIMIT ?"
            parameters.append(limit)
        with self._connection() as connection:
            return [dict(row) for row in connection.execute(query, parameters)]

    def last_watered(self, plant_id: int) -> str | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT MAX(occurred_on) AS last_watered FROM care_logs WHERE plant_id = ? AND kind = 'watering'",
                (plant_id,),
            ).fetchone()
        return row["last_watered"]

    def export_plant(self, plant_id: int) -> dict:
        return {"schema_version": 2, "plant": self.get_plant(plant_id), "care_logs": self.list_logs(plant_id),
                "ai_analyses": self.list_analyses(plant_id), "ai_suggestions": self.list_suggestions(plant_id),
                "weather_region": self.get_weather_region(plant_id), "care_schedules": self.list_schedules(plant_id)}

    @staticmethod
    def _schedule_values(title, kind, due_on, due_time, notes):
        from datetime import time
        title = _text(title, '할 일', 100, required=True)
        notes = _text(notes, '일정 메모', 1000)
        if kind not in CARE_TYPES:
            raise ValueError('관리 종류를 선택해 주세요.')
        try:
            day = date.fromisoformat(str(due_on))
            clock = time.fromisoformat(str(due_time))
            if clock.tzinfo is not None:
                raise ValueError
        except (ValueError, TypeError) as error:
            raise ValueError('일정 날짜와 시간을 확인해 주세요.') from error
        return title, kind, day.isoformat(), clock.strftime('%H:%M'), notes

    def add_schedule(self, plant_id, title, kind, due_on, due_time='09:00', notes=''):
        self.get_plant(plant_id)
        values = self._schedule_values(title, kind, due_on, due_time, notes)
        now = datetime.now(timezone.utc).isoformat()
        with self._connection() as connection:
            cursor = connection.execute('INSERT INTO care_schedules '
                '(plant_id,title,kind,due_on,due_time,notes,calendar_uid,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)',
                (plant_id, *values, uuid4().hex, now, now))
            return cursor.lastrowid

    def list_schedules(self, plant_id=None):
        with self._connection() as connection:
            query = 'SELECT s.*, p.name AS plant_name FROM care_schedules s JOIN plants p ON p.id=s.plant_id'
            args = ()
            if plant_id is not None:
                query += ' WHERE s.plant_id=?'
                args = (plant_id,)
            return [dict(row) for row in connection.execute(query + ' ORDER BY s.due_on,s.due_time,s.id', args)]

    @staticmethod
    def _pending_schedule(connection, schedule_id):
        row = connection.execute('SELECT * FROM care_schedules WHERE id=?', (schedule_id,)).fetchone()
        if row is None or row['status'] != 'pending':
            raise ValueError('이미 완료·취소했거나 찾을 수 없는 일정이에요. 새로고침해 확인해 주세요.')
        return row

    def update_schedule(self, schedule_id, title, kind, due_on, due_time, notes=''):
        values = self._schedule_values(title, kind, due_on, due_time, notes)
        with self._connection() as connection:
            self._pending_schedule(connection, schedule_id)
            connection.execute('UPDATE care_schedules SET title=?,kind=?,due_on=?,due_time=?,notes=?, '
                'revision=revision+1,updated_at=? WHERE id=?', (*values, datetime.now(timezone.utc).isoformat(), schedule_id))

    def cancel_schedule(self, schedule_id):
        with self._connection() as connection:
            self._pending_schedule(connection, schedule_id)
            connection.execute("UPDATE care_schedules SET status='cancelled',revision=revision+1,updated_at=? WHERE id=?",
                               (datetime.now(timezone.utc).isoformat(), schedule_id))

    def complete_schedule(self, schedule_id, kind, occurred_on, notes):
        # One SQLite transaction and one cloud CAS write: no orphan log or duplicate completion.
        notes = _text(notes, '실제로 한 관리', 3000, required=True)
        if kind not in CARE_TYPES:
            raise ValueError('실제로 한 관리 종류를 선택해 주세요.')
        try:
            day = date.fromisoformat(str(occurred_on))
        except (TypeError, ValueError) as error:
            raise ValueError('기록 날짜를 확인해 주세요.') from error
        if day > today_in_seoul():
            raise ValueError('오늘까지의 실제 관리만 완료로 남길 수 있어요.')
        now = datetime.now(timezone.utc).isoformat()
        with self._connection() as connection:
            row = self._pending_schedule(connection, schedule_id)
            cursor = connection.execute('INSERT INTO care_logs(plant_id,kind,occurred_on,notes,created_at) VALUES (?,?,?,?,?)',
                (row['plant_id'], kind, day.isoformat(), notes, now))
            log_id = cursor.lastrowid
            connection.execute("UPDATE care_schedules SET status='completed',completed_log_id=?,revision=revision+1,updated_at=? WHERE id=?",
                               (log_id, now, schedule_id))
            return log_id

    def get_weather_region(self, plant_id: int) -> str | None:
        self.get_plant(plant_id)
        with self._connection() as connection:
            row = connection.execute('SELECT region_id FROM plant_weather_regions WHERE plant_id = ?', (plant_id,)).fetchone()
        return row['region_id'] if row and row['region_id'] in REGIONS else None

    def set_weather_region(self, plant_id: int, region_id: str | None):
        self.get_plant(plant_id)
        if region_id is not None and region_id not in REGIONS:
            raise ValueError('목록에서 날씨 참고 지역을 선택해 주세요.')
        with self._connection() as connection:
            if region_id is None:
                connection.execute('DELETE FROM plant_weather_regions WHERE plant_id = ?', (plant_id,))
            else:
                connection.execute('INSERT INTO plant_weather_regions(plant_id, region_id) VALUES (?, ?) '
                                   'ON CONFLICT(plant_id) DO UPDATE SET region_id = excluded.region_id', (plant_id, region_id))

    def add_analysis(self, plant_id: int, model: str, context: dict, result: dict,
                     usage: dict, photo: bytes | None = None) -> int:
        self.get_plant(plant_id)
        values = [json.dumps(value, ensure_ascii=False) for value in (context, result, usage)]
        photo_path = self._save_photo(photo)
        try:
            with self._connection() as connection:
                cursor = connection.execute(
                    "INSERT INTO ai_analyses(plant_id, model, input_json, result_json, usage_json, photo_path, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (plant_id, model, *values, photo_path, datetime.now(timezone.utc).isoformat()),
                )
                analysis_id = cursor.lastrowid
                self._insert_suggestions(connection, analysis_id, result)
                return analysis_id
        except Exception:
            self._remove_photo(photo_path)
            raise

    def list_analyses(self, plant_id: int) -> list[dict]:
        with self._connection() as connection:
            rows = connection.execute("SELECT * FROM ai_analyses WHERE plant_id = ? ORDER BY id DESC", (plant_id,))
            analyses = []
            for row in rows:
                analysis = dict(row)
                for name in ("input", "result", "usage"):
                    analysis[name] = json.loads(analysis.pop(f"{name}_json"))
                analyses.append(analysis)
            return analyses

    def _validate_link(self, connection, plant_id, suggestion_id, link_type, log_date):
        suggestion = connection.execute('SELECT a.plant_id, a.created_at FROM ai_suggestions s '
                                        'JOIN ai_analyses a ON a.id = s.analysis_id WHERE s.id = ?', (suggestion_id,)).fetchone()
        if suggestion is None or suggestion['plant_id'] != plant_id:
            raise ValueError("이 식물의 AI 제안을 선택해 주세요.")
        suggested_on = datetime.fromisoformat(suggestion['created_at']).astimezone(ZoneInfo('Asia/Seoul')).date()
        if log_date < suggested_on:
            raise ValueError("AI가 제안한 날 이후의 관리만 연결할 수 있어요.")
        execution = connection.execute("SELECT occurred_on FROM care_logs WHERE suggestion_id = ? AND link_type = 'execution'",
                                       (suggestion_id,)).fetchone()
        if link_type == 'execution' and execution:
            raise ValueError("이미 실행 기록이 연결된 제안이에요. 이후 상태는 경과로 남겨 주세요.")
        if link_type == 'outcome' and (execution is None or log_date < date.fromisoformat(execution['occurred_on'])):
            raise ValueError("실행 기록을 먼저 남기고, 실행한 날 이후의 경과를 기록해 주세요.")

    def list_suggestions(self, plant_id: int, limit: int | None = None) -> list[dict]:
        query = ('SELECT s.*, a.plant_id, a.created_at AS suggested_at FROM ai_suggestions s '
                 'JOIN ai_analyses a ON a.id = s.analysis_id WHERE a.plant_id = ? '
                 'ORDER BY s.analysis_id DESC, s.action_index')
        parameters = [plant_id]
        if limit is not None:
            if type(limit) is not int or not 1 <= limit <= 100:
                raise ValueError("제안 개수는 1~100 사이로 선택해 주세요.")
            query += ' LIMIT ?'
            parameters.append(limit)
        with self._connection() as connection:
            suggestions = [dict(row) for row in connection.execute(query, parameters)]
            for suggestion in suggestions:
                logs = [dict(row) for row in connection.execute(
                    'SELECT * FROM care_logs WHERE suggestion_id = ? ORDER BY occurred_on, id', (suggestion['id'],))]
                suggestion['execution'] = next((log for log in logs if log['link_type'] == 'execution'), None)
                suggestion['observations'] = [log for log in logs if log['link_type'] == 'outcome']
        return suggestions
