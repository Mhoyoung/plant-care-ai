"""동일 상태의 기록 제외/포함 비교. 정원 DB에는 실험 데이터를 쓰지 않는다."""
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import json
from uuid import uuid4
from zoneinfo import ZoneInfo

from .gemini import AnalysisError, MODEL, SYSTEM, analyze

SOURCE = "https://www.extension.umd.edu/resource/diagnose-indoor-plant-problems"
CASES = {
    "wet": ("흙이 계속 젖어 있는 경우", "최근 물을 줬고, 이후에도 흙이 젖어 있다는 가상 기록"),
    "dry": ("흙이 말라 있는 경우", "최근 물주기 기록이 오래됐고, 흙이 말랐다는 가상 기록"),
    "followup": ("이전 제안 후 경과가 있는 경우", "제안·실행·관찰을 연결한 가상 기록. 관리 효과는 확정하지 않음"),
}


def demo_context(case_id):
    """원예 자료로 만든 가상 입력. 실제 사진·실제 관찰·정답 응답이 아니다."""
    if case_id not in CASES:
        raise ValueError("비교할 예시를 선택해 주세요.")
    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    day = lambda offset: (today - timedelta(days=offset)).isoformat()
    log = lambda kind, offset, notes: dict(kind=kind, occurred_on=day(offset), notes=notes, outcome="unrecorded")
    context = {
        "plant": {"name": "비교용 가상 관엽식물", "species": "종류 미확인", "location": "실내 창가", "notes": ""},
        "today": day(0), "current_state": "잎이 처져 있어요. 물을 더 줘야 할까요?",
        "has_photo": False, "last_watered": None, "recent_care_logs": [], "previous_suggestions": [],
        "evaluation_demo": "원예 자료를 참고해 만든 가상 시나리오입니다. 실제 관찰이나 실제 회복 결과가 아닙니다. 가정된 기록에 따라 먼저 확인할 사항을 제안하세요.",
    }
    if case_id == "wet":
        context["last_watered"] = day(1)
        context["recent_care_logs"] = [log("watering", 1, "물을 줬어요."), log("observation", 0, "흙을 만져보니 여전히 젖어 있고 화분이 무거워요.")]
    elif case_id == "dry":
        context["last_watered"] = day(12)
        context["recent_care_logs"] = [log("watering", 12, "물을 줬어요."), log("observation", 0, "흙 표면이 마르고 화분이 전보다 가벼워요. 안쪽 흙은 아직 확인하지 않았어요.")]
    else:
        execution = log("observation", 2, "흙이 젖어 있어서 물을 더 주지 않고 배수구를 확인했어요.")
        observation = log("observation", 0, "잎은 여전히 처져 있고 흙은 전보다 덜 젖어 있어요.")
        context["last_watered"] = day(3)
        context["recent_care_logs"] = [log("watering", 3, "물을 줬어요."), execution, observation]
        context["previous_suggestions"] = [{"suggested_at": f"{day(2)}T09:00:00+09:00", "suggestion": "흙이 젖어 있다면 추가 물주기 전에 배수구와 흙 상태를 확인하세요.", "execution": execution, "observations": [observation]}]
    return context


def new_trial(context, photo=None, source=None):
    history = deepcopy(context)
    # 등록 메모에 과거 관리가 들어 있을 수 있어 두 조건 모두에서 제외한다.
    history["plant"]["notes"] = ""
    history["has_photo"] = photo is not None
    baseline = deepcopy(history)
    for name in ("last_watered", "recent_care_logs", "previous_suggestions"):
        baseline.pop(name, None)
    return {"version": 1, "id": uuid4().hex, "created_at": datetime.now(ZoneInfo("Asia/Seoul")).isoformat(),
            "model": MODEL, "system_instruction": SYSTEM, "source": source or {},
            "inputs": {"baseline": baseline, "history": history}, "photo": photo,
            "photo_sha256": hashlib.sha256(photo).hexdigest() if photo is not None else None,
            "results": {}, "attempts": {}, "assessment": {}}


def run_side(trial, side, key, consent):
    """수동 버튼 하나당 최대 한 요청. 실패도 기록해 재실행의 중복 호출을 막는다."""
    if side not in ("baseline", "history"):
        raise ValueError("비교 조건이 올바르지 않아요.")
    if not consent:
        raise ValueError("Google 전송 안내를 확인하고 동의해 주세요.")
    if side in trial["attempts"]:
        raise ValueError("이 조건은 이미 요청했어요. 다시 비교하려면 새 비교를 준비해 주세요.")
    trial["attempts"][side] = {"at": datetime.now(ZoneInfo("Asia/Seoul")).isoformat(), "status": "requested"}
    try:
        result, usage = analyze(key, deepcopy(trial["inputs"][side]), trial["photo"])
    except (AnalysisError, ValueError) as error:
        trial["attempts"][side]["status"] = "failed"
        trial["attempts"][side]["message"] = str(error)
        if isinstance(error, AnalysisError):
            trial["attempts"][side]["error"] = {"http_status": error.http_status, "error_code": error.error_code,
                                                 "retry_after_seconds": error.retry_after_seconds}
        raise
    trial["results"][side] = {"result": result, "usage": usage}
    trial["attempts"][side]["status"] = "completed"


def export_trial(trial):
    """키와 사진 원본을 제외한 비교 기록. 사진은 별도 다운로드한다."""
    return json.dumps({key: value for key, value in trial.items() if key != "photo"}, ensure_ascii=False, indent=2)
