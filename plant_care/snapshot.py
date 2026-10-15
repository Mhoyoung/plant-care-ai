"""검증된 SQLite 모델을 팀 정원 스냅샷과 사진 백업으로 옮긴다."""
from io import BytesIO
import json
import re
from zipfile import ZipFile, ZIP_DEFLATED

LEGACY_TABLES = ('plants', 'ai_analyses', 'ai_suggestions', 'care_logs', 'plant_weather_regions')
TABLES = (*LEGACY_TABLES, 'care_schedules')
MAX_STATE_BYTES = 16 * 1024 * 1024
MAX_BACKUP_BYTES = 100 * 1024 * 1024


def photo_name(relative):
    if not isinstance(relative, str) or not re.fullmatch(r'photos/[0-9a-f]{32}\.jpg', relative):
        raise ValueError('사진 경로가 올바르지 않아요.')
    return relative


def dump_connection(connection):
    return {'version': 1, 'tables': {table: [dict(row) for row in connection.execute(f'SELECT * FROM {table} ORDER BY 1')]
                                    for table in TABLES}}


def dump_store(store):
    with store._connection() as connection:
        return dump_connection(connection)


def restore_connection(connection, state):
    # Additive extension inside the existing server envelope. Old gardens/backups have no schedules.
    if not isinstance(state, dict) or state.get('version') != 1 or not isinstance(state.get('tables'), dict) or \
            set(state['tables']) not in (set(TABLES), set(LEGACY_TABLES)):
        raise ValueError('정원 데이터 형식을 확인할 수 없어요.')
    if any(connection.execute(f'SELECT 1 FROM {table} LIMIT 1').fetchone() for table in TABLES):
        raise ValueError('기존 기록이 있는 정원에는 백업을 덮어쓰지 않아요.')
    for table in TABLES:
        columns = [row['name'] for row in connection.execute(f'PRAGMA table_info({table})')]
        rows = state['tables'].get(table, [])
        if not isinstance(rows, list):
            raise ValueError('정원 데이터 형식을 확인할 수 없어요.')
        for row in rows:
            if not isinstance(row, dict) or set(row) != set(columns):
                raise ValueError('정원 데이터 형식을 확인할 수 없어요.')
            if row.get('photo_path'):
                photo_name(row['photo_path'])
            values = [row[column] for column in columns]
            connection.execute(f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})", values)
    if connection.execute('PRAGMA foreign_key_check').fetchall():
        raise ValueError('정원 기록의 연결 관계를 확인할 수 없어요.')


def photo_names(state):
    return sorted({photo_name(row['photo_path']) for table in ('plants', 'care_logs', 'ai_analyses')
                   for row in state['tables'][table] if row.get('photo_path')})


def make_backup(store):
    state = dump_store(store)
    manifest = json.dumps(state, ensure_ascii=False).encode('utf-8')
    if len(manifest) > MAX_STATE_BYTES:
        raise ValueError('정원 데이터가 너무 커요. 관리자에게 백업을 요청해 주세요.')
    total = len(manifest)
    buffer = BytesIO()
    with ZipFile(buffer, 'w', ZIP_DEFLATED) as archive:
        archive.writestr('garden.json', manifest)
        for name in photo_names(state):
            data = store.read_photo(name)
            total += len(data)
            if total > MAX_BACKUP_BYTES:
                raise ValueError('전체 백업은 100MB까지 준비할 수 있어요. 사진을 별도로 백업해 주세요.')
            archive.writestr(name, data)
    return buffer.getvalue()


def read_backup(data):
    if len(data) > MAX_BACKUP_BYTES:
        raise ValueError('백업 파일은 100MB 이하로 선택해 주세요.')
    with ZipFile(BytesIO(data)) as archive:
        entries = archive.infolist()
        if len(entries) > 5000 or sum(info.file_size for info in entries) > MAX_BACKUP_BYTES:
            raise ValueError('백업 파일이 너무 커요.')
        names = [info.filename for info in entries]
        if len(names) != len(set(names)) or 'garden.json' not in names:
            raise ValueError('정원 백업 파일을 선택해 주세요.')
        manifest = archive.read('garden.json')
        if len(manifest) > MAX_STATE_BYTES:
            raise ValueError('정원 데이터가 너무 커요.')
        state = json.loads(manifest)
        required = photo_names(state)
        if set(names) != {'garden.json', *required}:
            raise ValueError('백업에 필요한 사진이 없거나 알 수 없는 파일이 있어요.')
        return state, {name: archive.read(name) for name in required}
