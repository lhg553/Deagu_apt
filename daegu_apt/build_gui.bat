@echo off
chcp 65001 > nul
echo ============================================
echo   대구 아파트 부동산 수집기  ^|  GUI 빌드
echo ============================================
echo.

echo [1/4] 패키지 설치 중...
pip install -r requirements.txt
pip install pyinstaller pyinstaller-hooks-contrib
if errorlevel 1 (
    echo [오류] 패키지 설치 실패
    pause & exit /b 1
)

echo.
echo [2/4] Playwright Chromium 설치 중...
python -m playwright install chromium
if errorlevel 1 (
    echo [오류] Playwright 브라우저 설치 실패
    pause & exit /b 1
)

echo.
echo [3/4] 실행파일 빌드 중 (몇 분 소요)...
pyinstaller --noconfirm --distpath release daegu_apt_gui.spec
if errorlevel 1 (
    echo [오류] 빌드 실패
    pause & exit /b 1
)

echo.
echo ============================================
echo   빌드 완료!
echo   release\daegu_apt_gui\daegu_apt_gui.exe
echo ============================================
echo.
echo [참고] .env 파일을 EXE 옆에 복사하면
echo        API 키가 자동으로 불러와집니다.
echo        (GUI 내 [저장] 버튼으로도 설정 가능)
echo.
pause
