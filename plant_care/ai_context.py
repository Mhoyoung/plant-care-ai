"""다음 단계의 AI 연동에 사용할 입력 준비. 외부 API는 호출하지 않는다."""

from .storage import PlantStore


def build_context(store: PlantStore, plant_id: int, recent_limit: int = 30) -> dict:
    """식물 정보와 최근 기록을 오래된 순서로 묶는다.

    photo_path는 로컬 파일 참조다. 비전 API 연동 시 사진 바이트를 별도로
    읽어 공급자가 요구하는 형식으로 전달해야 한다.
    """
    plant = store.get_plant(plant_id)
    logs = list(reversed(store.list_logs(plant_id, limit=recent_limit)))
    return {
        "plant": plant,
        "last_watered": store.last_watered(plant_id),
        "recent_care_logs": logs,
    }
