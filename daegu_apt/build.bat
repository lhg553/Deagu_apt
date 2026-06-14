@echo off
echo [1/4] 패키지 설치 중...
pip install -r requirements.txt
pip install pyinstaller

echo [2/4] Playwright 브라우저 설치 중...
python -m playwright install chromium

echo [3/4] 실행파일 빌드 중...
pyinstaller --onefile --name daegu_apt ^
  --add-binary "%LOCALAPPDATA%\ms-playwright\chromium-*\chrome-win\chrome.exe;playwright/driver/package/.local-browsers/chromium-1148/chrome-win" ^
  main.py

echo [4/4] 완료!
echo dist\daegu_apt.exe 파일이 생성되었습니다.
echo.
echo [참고] EXE 파일을 실행하려면 dist\ 폴더에서:
echo   daegu_apt.exe --district 수성구
echo   daegu_apt.exe --district all --trade 전세
echo   daegu_apt.exe --molit-key YOUR_KEY
pause
