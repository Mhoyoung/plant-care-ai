"""SQLite 저장소. Streamlit 없이도 사용할 수 있다."""

from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
import sqlite3

from .constants import CARE_TYPES, OUTCOMES
from .media import save_photo


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
    def __init__(self, data_root: Path | str):
        self.data_root = Path(data_root).resolve()
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_root / "plants.db"
        with self._connection() as connection:
            connection.executescript("""
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
            """)

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

    def add_plant(self, name: str, species: str = "", location: str = "", notes: str = "", photo: bytes | None = None) -> int:
        name = _text(name, "식물 이름", 100, required=True)
        species = _text(species, "종류", 100)
        location = _text(location, "장소", 200)
        notes = _text(notes, "메모", 3000)
        photo_path = save_photo(photo, self.data_root)
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

    def add_log(self, plant_id: int, kind: str, occurred_on: date | str, notes: str = "", outcome: str = "unrecorded", photo: bytes | None = None) -> int:
        self.get_plant(plant_id)
        if kind not in CARE_TYPES:
            raise ValueError("관리 종류를 선택해 주세요.")
        if outcome not in OUTCOMES:
            raise ValueError("관찰 결과를 선택해 주세요.")
        notes = _text(notes, "메모", 3000)
        try:
            log_date = date.fromisoformat(str(occurred_on))
        except (TypeError, ValueError) as error:
            raise ValueError("날짜를 올바르게 입력해 주세요.") from error
        if log_date > date.today():
            raise ValueError("오늘까지의 관리 기록만 저장할 수 있어요.")
        photo_path = save_photo(photo, self.data_root)
        try:
            with self._connection() as connection:
                cursor = connection.execute(
                    "INSERT INTO care_logs(plant_id, kind, occurred_on, notes, outcome, photo_path, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (plant_id, kind, log_date.isoformat(), notes, outcome, photo_path, datetime.now(timezone.utc).isoformat()),
                )
                log_id = cursor.lastrowid
        except Exception:
            self._remove_photo(photo_path)
            raise
        return log_id

    def list_logs(self, plant_id: int, limit: int | None = None) -> list[dict]:
        query = "SELECT * FROM care_logs WHERE plant_id = ? ORDER BY occurred_on DESC, id DESC"
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
        return {"schema_version": 1, "plant": self.get_plant(plant_id), "care_logs": self.list_logs(plant_id)}
