# Android 시험 설치 앱

기존 [공유 모바일 웹](https://plant-care-ai-bh5dtxenovacdz7hc4bdvj.streamlit.app/)을 Android WebView에서 여는 첫 시험판입니다. 웹과 같은 Supabase 계정·개인 정원을 사용합니다. Gemini 키나 Supabase 서버 키는 설치 파일에 넣지 않습니다.

## 준비와 첫 빌드

1. [Android Studio](https://developer.android.com/studio)를 설치하고 첫 실행에서 Android SDK와 에뮬레이터를 설정합니다. 현재 개발 PC에는 Studio·SDK·Java가 없어 아직 APK 빌드를 검증하지 못했습니다.
2. Android Studio에서 **Open**으로 이 `android` 폴더를 선택합니다. Gradle JDK는 Android Studio에 포함된 JDK 17 이상을 사용합니다.
3. SDK Platform 35가 없으면 설치하고 Gradle 동기화를 마칩니다.
4. Device Manager에서 에뮬레이터를 만들고 `app` 구성을 실행합니다. 또는 `android` 폴더에서 `gradlew.bat assembleDebug`로 빌드한 뒤 `app/build/outputs/apk/debug/app-debug.apk`를 시험 기기에 설치합니다.

앱은 사진 선택에 Android 시스템 파일 선택기를 사용합니다. **전체 사진 접근·카메라 권한을 요청하지 않습니다.** 사용자가 선택한 사진만 웹 업로드 입력으로 전달합니다. 직접 촬영, 백업 다운로드, Google 캘린더로 이동, 로그인 유지, 뒤로 가기는 에뮬레이터와 실기기에서 검증할 항목입니다.

## 첫 시험 순서

1. 앱 실행 → 이메일 로그인 → 내 정원의 식물이 보이는지 확인합니다.
2. 새 식물 화면에서 사진 선택 창을 열고 사진 한 장을 고른 뒤 미리보기·저장을 확인합니다. 실제 개인 정원에 새 시험 식물을 만들기 전에는 이름에 `[테스트]`를 붙입니다.
3. 관리 기록에서 사진 선택·저장·재조회와 집 식물 1의 자동 AI 관찰을 확인합니다. AI 요청은 중복해서 누르지 않습니다.
4. AI 분석과 케어 일정, Google 캘린더 링크를 확인합니다. 외부 링크는 휴대폰 브라우저나 해당 앱에서 열려야 합니다.

기기에서 확인하지 않은 항목을 완료로 표시하지 않습니다. 현재 단계는 **소스 준비 완료, APK 빌드·설치 미검증**입니다.
