"""AI 연동에 사용할 로컬 입력 준비. 외부 호출은 gemini.py에서 수행한다."""

from .storage import PlantStore


def build_context(store: PlantStore, plant_id: int, recent_limit: int = 30) -> dict:
    """식물 정보와 최근 기록을 오래된 순서로 묶는다.

    photo_path는 로컬 참조다. gemini.analysis_context에서 경로를 제외하고,
    사용자가 선택한 사진만 별도로 전달한다.
    """
    plant = store.get_plant(plant_id)
    logs = list(reversed(store.list_logs(plant_id, limit=recent_limit)))
    return {
        "plant": plant,
        "last_watered": store.last_watered(plant_id),
        "recent_care_logs": logs,
        "previous_suggestions": store.list_suggestions(plant_id, limit=10),
    }
