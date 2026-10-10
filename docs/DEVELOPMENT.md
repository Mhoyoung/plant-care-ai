# 혼자 개발할 때의 Issue · PR

Issue는 할 일을 나누고, PR은 실제 수정 내용과 확인 결과를 남기는 데 사용합니다.
모든 수정에 둘 다 만들 필요는 없습니다. 짧은 문구 수정은 커밋으로, 기능 추가와 버그 수정은 PR로 기록하세요.

## 1. Issue에 목표와 완료 기준 적기

[새 Issue](https://github.com/Mhoyoung/plant-care-ai/issues/new/choose)에서 `기능 작업` 또는 `버그 보고`를 선택합니다.
처음에는 동시에 진행할 작업을 하나로 정하고 나머지는 목록에 남겨두면 충분합니다.

예를 들어 `AI 첫 분석 결과 저장` 작업은 다음처럼 나눌 수 있습니다.

- 목표: 식물의 현재 사진·상태를 분석하고 결과를 나중에 다시 볼 수 있게 저장
- 완료 기준: 결과 표시, 식물별 저장, 재실행 후 조회, 연결 실패 시 안내
- 이번 범위: 한 번의 분석과 저장. 과거 제안의 효과 비교는 다음 작업

## 2. 작업 브랜치 만들기

Git으로 복제한 폴더에서, 저장하지 않은 변경이 없는 상태로 시작합니다.

```powershell
git switch main
git pull --ff-only origin main
git switch -c codex/ai-first-analysis
```

`codex/ai-first-analysis`는 예시입니다. 작업마다 다른 이름을 사용하세요.
처음 코드를 읽을 때는 `app.py` → `plant_care/storage.py` → `plant_care/media.py` 순서로 읽어보세요.

## 3. 수정하고 확인하기

직접 실행해 바뀐 동작을 확인합니다. 앱 로직을 바꿨다면 관련 테스트도 실행하세요.
확인한 동작과 아직 확인하지 못한 내용을 간단히 메모합니다.

```powershell
git diff
git diff --check
git add app.py plant_care tests
git diff --cached
git commit -m "Add first AI analysis"
git push -u origin codex/ai-first-analysis
```

위 파일 경로와 커밋 메시지는 예시입니다. 실제 바꾼 파일을 선택하세요.
API 키·개인 사진·DB 파일은 올리지 않습니다. 실제 AI 호출을 추가할 때 비밀키는 환경변수로 관리하세요.

## 4. PR에서 확인하고 병합하기

GitHub의 **Pull requests → New pull request**에서 `base: main`, `compare: 작업 브랜치`를 선택합니다.
자동으로 나오는 양식에 무엇을 바꿨는지, 왜 필요한지, 어떻게 확인했는지 적습니다.
관련 Issue가 있다면 실제 번호로 `Closes #번호`를 적습니다.

**Files changed**에서 수정 내용을 다시 확인하고 준비가 끝나면 직접 병합합니다.
진행 중이면 Draft PR로 남겨둘 수 있습니다. 혼자 쓰는 저장소이므로 다른 사람의 승인 없이도 확인하고 병합할 수 있습니다.
현재 이 저장소에 별도의 리뷰 의무나 브랜치 보호 규칙은 추가하지 않았습니다.

병합 후에는 로컬의 `main`도 갱신합니다.

```powershell
git switch main
git pull --ff-only origin main
```

## 이 저장소에 있는 양식

| 양식 | 작성 내용 |
|---|---|
| 기능 작업 | 목표, 작업 범위, 완료 기준 |
| 버그 보고 | 재현 순서, 기대한 결과, 실제 결과, 실행 환경 |
| PR | 변경 내용, 이유, 검증 결과, 관련 Issue |

양식은 기본 브랜치 `main`에 반영되어야 새 Issue·PR에서 사용할 수 있습니다.
[GitHub 공식 템플릿 안내](https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests/about-issue-and-pull-request-templates)
