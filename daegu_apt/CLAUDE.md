# 대구 부동산 데이터 수집기 — Claude 실행 가이드

대구 아파트의 **호가(네이버 부동산)**, **위치 정보(카카오 Local API)**, **실거래가(국토교통부)** 를 수집해 Excel 파일로 저장합니다.

---

## 실행 방법

### GUI 실행파일 (권장)

```
release\daegu_apt_gui\daegu_apt_gui.exe
```

더블클릭으로 실행. API 키 입력·저장, **지역 다중 선택(체크박스 + 전체선택 버튼)**, 실시간 로그 확인 가능.  
여러 구 선택 시 **2개씩 동시 수집**하고, 구별 개별 파일과 `대구통합_부동산_*.xlsx`(시트별 병합)를 함께 생성.

### CLI 실행

작업 디렉토리: `c:\Users\jk\ljk_workspace\mortgage\daegu_apt\`

```bash
python main.py --district 수성구
python main.py --district all --months 6
```

---

## 개발 환경 설정

```bash
python --version        # Python 3.10 이상 필요
pip install -r requirements.txt
python -m playwright install chromium
```

### Python 실행 시 필수: UTF-8 인코딩 설정

한글 출력이 깨지므로 Python 실행 전 반드시 설정:

```powershell
$env:PYTHONIOENCODING = "utf-8"
python main.py ...
```

또는 한 줄로:
```powershell
$env:PYTHONIOENCODING = "utf-8"; python main.py ...
```

Claude가 PowerShell에서 Python 명령을 실행할 때도 항상 `$env:PYTHONIOENCODING = "utf-8"` 먼저 설정할 것.

---

## API 키 설정 (.env)

```
KAKAO_API_KEY=...     # 카카오 지하철·학교·마트 위치 조회 (필수)
MOLIT_API_KEY=...     # 국토교통부 실거래가 (선택)
```

**카카오 키 발급**: [developers.kakao.com](https://developers.kakao.com) → 앱 생성 → REST API 키 복사  
**주의**: 앱 설정 → 카카오 로컬 → **OPEN_MAP_AND_LOCAL 활성화** 필수

**국토교통부 키 발급**: [data.go.kr](https://www.data.go.kr) → "아파트매매 실거래가 상세자료" → 활용신청 (무료·즉시)

GUI에서는 [저장] 버튼으로 .env에 직접 저장 가능.

---

## CLI 전체 옵션

| 옵션 | 기본값 | 설명 |
|------|--------|------|
| `--district` | all | 지역: all, 중구, 동구, 서구, 남구, 북구, 수성구, 달서구, 달성군 |
| `--source` | both | 소스: both, naver, molit |
| `--months` | 12 | 실거래가 최근 N개월 |
| `--molit-key` | 없음 | 국토교통부 API 키 |
| `--kakao-key` | 없음 | 카카오 REST API 키 (.env 자동 로드) |
| `--output` | 자동 | 저장 파일명 (기본: {지역}_부동산_YYYYMMDD_HHMMSS.xlsx) |
| `--test` | 없음 | 테스트 모드: 매물 많은 순 10개 단지만 수집 |

---

## 출력 Excel 시트 구성

| 시트명 | 내용 | 헤더 색상 |
|--------|------|----------|
| **호가_단지요약** | 단지×평형 1행씩 매매/전세/월세 통계 + 위치 정보 | 파란색 |
| **매물상세** | 개별 매물 가격·평형 목록 + 동일매물 정보 | 주황색 |
| **실거래가** | 국토교통부 아파트 매매 실거래 데이터 (키 있을 때만) | 보라색 |
| **분양권실거래** | 국토교통부 분양권·입주권 거래 데이터 (키 + API 승인 시) | 보라색 |

### 호가_단지요약 컬럼

```
지역(구) | 지역(동) | 단지명 | 건축년월 | 총세대수 | 전용평형(평)
| 매매_최저(만원) | 매매_최고(만원) | 매매_평균(만원) | 매매_매물수
| 전세_최저(만원) | 전세_최고(만원) | 전세_평균(만원) | 전세_매물수
| 월세_매물수 | 5억이하매물수(호가)
| 단지코드 | 위도 | 경도
| 근처지하철 | 지하철직선도보(분)
| 근처초등학교 | 초등학교직선거리(m/분)   ← 예: 350m/5분
| 근처중학교 | 중학교직선거리(m/분) | 근처고등학교 | 고등학교직선거리(m/분)
| 인근대형마트(5km)   ← 최대 5개 (예: 이마트(2200m/33분), 홈플러스(3100m/46분))
| 인근공원(1km) | 인근어린이집(1km)
| 회전률(12개월%)  ← molit-key 있을 때 (1년 기준, 아실 기준과 동일)
| 분양권거래수(12개월)  ← 분양권 API 승인 시 (단지명 기준 집계)
| ⚠️회전율주의  ← 분양권거래수 > 0 이면 "분양권포함-회전율과대평가주의" 표시
```

- 단지×평형 1행: 단지에 25평·32평·59평이 있으면 3행 출력
- 단지 공통 정보(위치·학교 등)는 모든 평형 행에 복사 (API 1회 호출)
- 매매 매물이 없는 단지도 포함 (매매_매물수=0)

### 매물상세 추가 컬럼 (동일매물 묶음)

```
동일매물수          ← 같은 물건을 올린 중개사 수 (1=단독, 2↑=복수 중개사)
동일_최저가(만원)   ← 동일매물 그룹 내 최저 호가
동일_최고가(만원)   ← 동일매물 그룹 내 최고 호가
```

### 매물상세 참고 컬럼 — 분석 시 낮은 신뢰도 적용

```
중개사명(참고)       ← 해당 매물을 올린 공인중개사 상호 (매물번호와 1:1 대응)
중개사_코멘트(참고)  ← 중개사가 직접 입력한 자유 텍스트 (articleFeatureDesc)
태그(참고)          ← Naver가 자동 분류한 특징 태그 (tagList, 쉼표 구분)
```

**주의 — LLM/자동 분석 시 낮은 가중치 권장:**
- `중개사_코멘트(참고)`: 비정형 자유 텍스트. 중개사마다 작성 기준·스타일·성실도가 다름.  
  동일 물건(`동일매물수 > 1`)이라도 수집된 대표 1건의 코멘트만 기록됨 — 다른 중개사 코멘트는 수집하지 않음.  
  공란인 경우도 많음. 가격·면적·층수 등 정형 데이터와 달리 **참고용**으로만 활용.
- `태그(참고)`: Naver 자동 분류 기준이 명확하지 않으며 일관성이 낮음. 필터링보다 탐색 참고용.

---

## 수집 소요 시간 (2026-06-13 regions 방식 실측, 2개 구 동시)

| 구 | 법정동 | 단지 | 실측 시간 |
|----|------|------|----------|
| 서구 | 9 | 132 | 3.9분 |
| 중구 | 57 | 104 | 4.3분 |
| 남구 | 3 | 143 | 4.6분 |
| 달성군 | 9 | 144 | 6.4분 |
| 북구 | 31 | 316 | 11.6분 |
| 동구 | 45 | 437 | 14.8분 |
| 수성구 | 26 | 364 | 15.6분 |
| 달서구 | 24 | 420 | 16.4분 |

- **전체 8개 구**: `run_all.py`로 2개 구 동시 실행 시 **약 41분** (순차 합산 ~80분 대비 ~1.9배).
- Phase 1/2(regions, 동당 1회 fetch)는 매우 빠르고, 시간의 대부분은 Phase 3(단지별 페이지 방문).

---

## 단지 목록 수집 방식 (naver_scraper.py) — 2026-06-13 regions/complexes 전환

### 변천

1. **bbox 격자 + single-markers** (구버전): bbox 1회당 ~100개 한도 + 빈 격자 순회 → 누락·느림.
2. **cortarNo + single-markers** (2026-06-12): 동 cortarNo URL 방문 → markers 캡처. 단, single-markers가 **뷰포트(화면 범위) 기준**이라 넓은 동에서 뷰포트 사이 단지 누락 + 옆 구 단지 누수 발생.
3. **regions/complexes** (2026-06-13, 현재): 동 단위 **전체 단지 목록** API. 뷰포트 무관, 누락·누수 없음.

### 현재 방식: regions/complexes

각 법정동 cortarNo로 아래 API를 `page.evaluate` 안 `fetch`로 호출 (브라우저와 동일 스택 → 429 회피):

```
https://new.land.naver.com/api/regions/complexes?cortarNo={cno}&realEstateType=APT&order=
```

응답이 해당 동의 모든 아파트 단지를 반환 — `complexNo`·`complexName`·`latitude/longitude`·`totalHouseholdCount`·`useApproveYmd`(건축년월)·`dealCount`·`leaseCount`·`rentCount` 포함. 가격은 Phase 3 articles에서 계산.

**장점**
- 뷰포트 한계 없음 → 넓은 동에서도 단지 누락 0
- 동(법정동) 경계로 정확히 귀속 → 옆 구 단지 누수 0
- 동당 1회 호출 → 매우 빠름 (204개 동 = 204회 fetch)

**검증 (2026-06-13, regions vs 뷰포트 single-markers)**
- 중구: 111→104. 빠진 7개 전부 다른 구 단지(동구·북구·수성구·남구·서구) — 뷰포트+폴리곤버퍼 누수를 정확히 제외.
- 달성군: 진짜 누락 2개(죽곡한신휴플러스·푸르지오2) 회수 + 옆 구 누수 2개 제외.

### 법정동 cortarNo 목록 (regions/list 행정 계층)

`build_cortars_hier.py`가 `regions/list?cortarNo={상위}`로 대구→구→법정동 계층을 받아 `daegu_cortars.json` 생성.  
뷰포트 샘플링(구버전 build_daegu_cortars.py)은 법정동을 대거 누락했음(중구 9/57, 동구 31/45 등). 현재는 **공식 행정 계층 기반 204개 법정동**으로 누락 없음.

```bash
python build_cortars_hier.py   # daegu_cortars.json 재생성
```

### 구별 법정동 수 (2026-06-13)

| 구 | 법정동 | 구 | 법정동 |
|----|------|----|------|
| 중구 | 57 | 북구 | 31 |
| 동구 | 45 | 수성구 | 26 |
| 서구 | 9 | 달서구 | 24 |
| 남구 | 3 | 달성군 | 9 |

합계 204개 법정동. `daegu_cortars.json` 없으면 자동으로 구버전 격자 single-markers fallback.

### 행정구역 폴리곤 필터

수집 완료 후 `daegu_boundaries.json` (통계청 SGIS **2025 2Q** 공식 시군구 경계)의 실제 폴리곤으로 필터링.

- **단일 구**: 해당 구 폴리곤 내 단지만 유지 → 인접 구·타 지역 완전 차단
- **전체**: 대구 9개 구·군 폴리곤 합집합 내 단지만 유지 → 대구 외 지역 완전 차단
- `shapely` 라이브러리 사용. 폴리곤 파일 없으면 bbox fallback.
- **경계 버퍼 0.0005°(≈55m)** 적용: 경계 근처 단지 좌표 미세 오차 허용, 누락 방지
- 원본: `bnd_sigungu_22_2025_2Q/` (EPSG:5179) → geopandas로 WGS84 변환

---

## 수집 후 반드시 해야 할 검증 (check_missing.py)

### 왜 검증이 필요한가

격자 스텝이 너무 크면 Naver API 100개 제한에 걸려 단지가 조용히 누락된다.  
수집 완료 후 **MOLIT 실거래가(실제 거래된 단지 목록)와 Naver 수집 결과를 교차검증**해서  
"실거래는 있는데 호가 수집 안 된 단지"를 찾는다.  
→ 누락 단지가 많고 거래 건수도 많으면 **격자 스텝을 줄여서 재수집**해야 한다.

### 실행 방법

```powershell
# 구별로 실행 후 로그 저장 (최신 엑셀 자동 탐색)
python check_missing.py 중구  2>&1 | Tee-Object 교차검증로그\중구_교차검증_$(Get-Date -f yyyyMMdd).txt
python check_missing.py 서구  2>&1 | Tee-Object 교차검증로그\서구_교차검증_$(Get-Date -f yyyyMMdd).txt
python check_missing.py 남구  2>&1 | Tee-Object 교차검증로그\남구_교차검증_$(Get-Date -f yyyyMMdd).txt
python check_missing.py 동구  2>&1 | Tee-Object 교차검증로그\동구_교차검증_$(Get-Date -f yyyyMMdd).txt
python check_missing.py 북구  2>&1 | Tee-Object 교차검증로그\북구_교차검증_$(Get-Date -f yyyyMMdd).txt
python check_missing.py 수성구 2>&1 | Tee-Object 교차검증로그\수성구_교차검증_$(Get-Date -f yyyyMMdd).txt
python check_missing.py 달서구 2>&1 | Tee-Object 교차검증로그\달서구_교차검증_$(Get-Date -f yyyyMMdd).txt

# 파일 직접 지정할 경우
python check_missing.py 중구 중구_부동산_YYYYMMDD_HHMMSS.xlsx 2>&1 | Tee-Object 교차검증로그\중구_교차검증_$(Get-Date -f yyyyMMdd).txt
```

> **로그 보관 위치**: `교차검증로그/` 폴더. 구별 수집 완료 후 반드시 로그 저장할 것.

> **주의**: 엑셀에 실거래가 시트가 있어야 검증 가능. 수집 시 `--molit-key` 필수.

### 검증 로직

1. 실거래가 시트에서 해당 구 단지명 추출
2. 호가_단지요약 단지명과 비교
3. **정확 일치** → 정상 수집
4. **퍼지 매칭** (이름 포함 관계) → 이름만 다를 뿐 수집 정상
   - Naver는 주상복합에 `(주상복합)` 접미사 추가 / MOLIT은 공식 등기명 사용
5. **매칭 실패** → 실질 누락 → 카카오 API로 좌표 조회 후 폴리곤 통과 여부 확인

### 결과 해석 및 대응

| 분류 | 의미 | 대응 |
|------|------|------|
| 정확 일치 | 정상 수집 | 없음 |
| 이름 불일치(퍼지) | 수집됨, 이름 차이만 | 없음 |
| 실질 누락, 거래 1~2건 | 현재 Naver 매물 없음 → 정상 | 없음 |
| 실질 누락, 거래 3건↑ | 격자 셀이 너무 커서 잘렸을 가능성 | 해당 구 스텝 줄여 재수집 |
| 내당시영 등 재건축 단지 | Naver ABYG 분류 → 수집 대상 아님 | 없음 (정상 제외) |

### 검증 완료 현황

| 구 | 검증 여부 | 결과 요약 |
|----|----------|---------|
| 중구 | ✓ 완료 | 실거래 50개 → 47개 수집, 실질누락 3개 (모두 현재 매물없음) |
| 서구 | ✓ 완료 | 실거래 34개 → 30개 수집, 실질누락 4개 (내당시영 재건축, 나머지 매물없음) |
| 남구 | ✓ 완료 | 실거래 56개 → 52개 수집, 실질누락 4개 (공공임대·노후단지, 매물없음) |
| 북구 | ✓ 완료 | 실거래 187개 → 152개 수집, 실질누락 35개 (노후단지·공공임대 매물없음) |
| 수성구 | ✓ 완료 | 실거래 218개 → 194개 수집, 실질누락 24개 (노후단지 매물없음) |
| 달서구 | ✓ 완료 | 실거래 216개 → 182개 수집, 실질누락 34개 (노후단지·공공임대 매물없음) |
| 동구 | ✓ 완료 | 실거래 138개 → 123개 수집, 실질누락 15개 (매물없음), 전세 55/63격자 수집 |
| 달성군 | ✓ 완료 | 실거래 115개 → 96개 수집(61 정확+35 퍼지), 실질누락 19개 (전부 폴리곤 통과·현재 Naver 매물 없음). 2026-06-13 검증 |

### 단지 수 현황 (2026-06-13 regions 방식 재수집 기준)

> 8개 구 전부 regions/complexes + 권위 법정동 목록으로 재수집. 매물상세는 전 페이지 완전 수집.

| 구 | 단지 수 | 매물상세 |
|----|--------|---------|
| 중구 | 104 | 2,545 |
| 서구 | 132 | 1,740 |
| 남구 | 143 | 2,202 |
| 북구 | 316 | 7,226 |
| 수성구 | 364 | 11,050 |
| 달서구 | 420 | 10,712 |
| 동구 | 437 | 6,452 |
| 달성군 | 144 | 5,028 |

- **8개 구 합계 2,060개 고유 단지** (구간 중복 0 — 각 단지가 정확히 한 구에만 귀속). 매물상세 합계 약 4.7만건.
- 직전 viewport 방식 대비: 옆 구 누수 단지(8구 합 42개)가 제거됨(중구 -7, 남구 -7, 북구 -10 등). 동구는 뷰포트 틈 메움으로 421→437 증가.
- 요약↔상세 매물수 8개 구 전부 정확히 일치. 통합본: `대구전체_부동산_*.xlsx` (단지요약 4,347 / 매물상세 46,955 / 실거래가 4,343).

### 전체 수집 실행 (2026-06-13 도입)

```bash
# 8개 구를 2개씩 동시 실행 (전체 약 53분) + 구별 시간 측정
python run_all.py

# 지정 구만 단일 프로세스로 순차 (세션 타임아웃 회피)
python run_districts.py 달서구 동구 달성군

# 수집 후 정합성 검증 (기준 엑셀 vs 신규 엑셀)
python verify_run.py 기준파일.xlsx 신규파일.xlsx
```

---

## 주의사항

- 네이버 부동산은 Playwright 헤드리스 브라우저로 수집
- 위치 정보(지하철·학교·마트)는 카카오 Local API 사용
  - 지역(구)/(동)은 네이버 cortarNo에서 채움 (카카오 역지오코딩·좌표 게이트 없음)
  - 좌표가 없거나 (0,0)인 단지만 위치 보강 스킵
  - 카카오가 대형마트를 못 찾으면 공란 (MT1 카테고리, 반경 5km)
- ★ **학교는 "가장 가까운" 학교일 뿐 배정(학군) 학교가 아님** — 초등학교는 거주지 주소로 배정되므로
  바로 옆 학교라도 배정 안 될 수 있음. 실제 배정은 사용자가 교육청·네이버 단지정보에서 직접 확인해야 함.
- ★ 모든 거리·도보(분)는 직선거리 ÷ 67m/분 추정치 (길찾기 아님, 실제 도보보다 짧음). 컬럼명에 "직선" 표기.
- ★ 중개사명/중개사_코멘트/태그(참고)는 추천·분석에 사용하지 않음(가중치 0)
- API 오류는 `[WARNING]` 로그로 출력

---

## EXE 빌드

```bash
# GUI 빌드 (권장) — daegu_apt_gui.spec 기반
build_gui.bat

# 또는 spec 직접 실행
pyinstaller --noconfirm --distpath release daegu_apt_gui.spec

# 결과: release\daegu_apt_gui\
#   daegu_apt_gui.exe       실행파일
#   _internal\              런타임 의존성
#   사용설명서.txt           자동 포함 (spec post-build hook)
#   엑셀_데이터_명세.md      자동 포함 (spec post-build hook)
# Playwright Chromium은 %LOCALAPPDATA%\ms-playwright\ 에서 자동 탐색
```

---

## 파일 구조

```
daegu_apt/
├── main.py                진입점 · CLI · Excel 저장 · run(args) 함수
├── gui.py                 tkinter GUI (구 다중선택 체크박스 + 실시간 로그)
│                            여러 구 선택 시 2개씩 동시 수집(인프로세스 스레드),
│                            구별 개별 파일 + 대구통합 파일 생성. 로그는 [구명] 접두사로 구분
├── naver_scraper.py       네이버 부동산 수집 (Playwright)
│                            Phase 1/2: regions/complexes API로 동(cortarNo) 단위
│                              전체 단지 목록 수집 (complexNo·좌표·세대수·매물수)
│                              - page.evaluate 안 fetch로 호출 (429/뷰포트 한계 회피)
│                              - 뷰포트 누락·옆 구 오귀속 없음
│                            Phase 3: 매물 상세 (매매 있는 전체 단지)
│                              - A1 페이지 방문으로 매매 1페이지 캡처 + 세션 워밍
│                              - 2페이지 이후·전세는 page.evaluate 안 fetch로 수집
│                              - 이미지·타일 차단(page.route)으로 networkidle 가속
│                            폴리곤 필터: daegu_boundaries.json 기반 (안전망)
│                            daegu_cortars.json 없으면 bbox 격자 single-markers fallback
├── molit_scraper.py       국토교통부 실거래가 API
│                            - 아파트 매매 실거래 (RTMSDataSvcAptTradeDev): aptSeq 필드 포함
│                            - 분양권·입주권 거래 (RTMSDataSvcSilvTrade): collect_silv()
│                            - 페이지네이션: totalCount 기반 1000건/페이지 자동 루프
│                            - API 미승인(401/403) 시 collect_silv() 빈 DataFrame 반환
├── location_enricher.py   위치 정보 보강 (카카오 Local API)
│                            - SW8: 지하철역 + 도보시간 / SC4: 초·중·고등학교 / MT1: 대형마트
│                            - PS3: 어린이집 / 키워드: 공원
│                            - 5스레드 병렬 + location_cache.json 캐시 (재수집 가속)
│                            - 캐시 hit 조건: 키 존재 AND 'mid_name' 필드 존재 (구버전 캐시는 miss 처리 → 재조회)
│                            - 지역(구)/(동)은 naver cortarNo에서 채움(역지오코딩 생략)
│                            - 좌표 게이트 없음 (cortarNo+폴리곤이 이미 대구 보장)
├── verify_run.py          정합성 검증 (기준 엑셀 vs 신규 엑셀 비교 + 내부 일관성)
│                            단지 집합·매물수 일치·위치 채움률·가격 이상치 체크
├── run_all.py             전체 8개 구 수집 (2개 구 동시 실행 + 구별 시간 측정)
├── run_districts.py       지정 구 목록 순차 수집 (단일 프로세스, 세션 타임아웃 회피)
├── combine.py             여러 구 엑셀을 시트별로 병합 → 통합 파일 1개
│                            - 호가_단지요약 concat 후 컬럼 순서 보정 (_reorder_summary)
│                            - 중학교·고등학교 컬럼이 마트보다 앞에 오도록 보장
│                            - 사용법: python combine.py 출력.xlsx 입력1.xlsx 입력2.xlsx ...
│                              ★ 첫 번째 인수가 출력 파일 (실수 주의: 기존 파일 덮어씀)
├── daegu_cortars.json     대구 8개 구 204개 법정동 cortarNo + 중심 좌표
│                            (형식: {"수성구": [{"cortarNo":"2726010100",
│                             "name":"범어동","centerLat":35.856,"centerLon":128.622},...]}
│                            build_cortars_hier.py 로 재생성 — 행정 계층 기반, 누락 없음)
├── build_cortars_hier.py  법정동 cortarNo 권위 수집 (regions/list 행정 계층)
│                            대구→구→법정동, 누락 없는 204개 법정동 생성 (현재 방식)
├── build_daegu_cortars.py (구버전) 뷰포트 샘플링 cortarNo 수집 — 법정동 누락 있음
├── daegu_boundaries.json  대구 9개 구·군 행정구역 폴리곤 (SGIS 2025 2Q 공식 데이터)
├── location_cache.json    카카오 위치조회 캐시 (단지코드별, 자동 생성·갱신)
├── bnd_sigungu_22_2025_2Q/  SGIS 원본 Shapefile (EPSG:5179, 변환 전)
├── .env                   API 키 (KAKAO_API_KEY, MOLIT_API_KEY)
├── requirements.txt       requests, pandas, openpyxl, playwright, python-dotenv, shapely
├── build_gui.bat          GUI EXE 빌드 스크립트 (PyInstaller — daegu_apt_gui.spec 기반)
├── daegu_apt_gui.spec     PyInstaller spec 파일
│                            - collect_all: playwright/numpy/pandas/shapely/charset_normalizer
│                            - datas: daegu_boundaries.json·daegu_cortars.json·complex_molit_map.json
│                            - post-build hook: 사용설명서.txt·엑셀_데이터_명세.md·complex_molit_map.json을
│                              EXE 옆에 자동 복사 (배포 시 별도 복사 불필요)
├── build.bat              CLI EXE 빌드 스크립트 (구버전)
├── make_complex_map.py    Naver 단지코드 ↔ MOLIT 아파트명 매핑 파일 생성 도구
│                            - 4단계 자동 매칭: exact → strip_suffix(주상복합 등) → fuzzy_동(0.78) → fuzzy_건축년도(0.65)
│                            - 차수(1차/2차)/동호(A동/B동)/단지번호 충돌 시 fuzzy 자동 거부
│                            - 결과: complex_molit_map.json + complex_molit_map_review.xlsx
│                            사용법:
│                              python make_complex_map.py 대구통합_*.xlsx  # 초기 생성
│                              python make_complex_map.py 대구통합_*.xlsx --update  # 신규 단지 추가
│                              python make_complex_map.py --from-review  # 수동 검토 결과 반영
├── complex_molit_map.json Naver 단지코드 → MOLIT 아파트명 매핑 (1,742개 매칭, 318개 미매칭)
│                            main.py _add_turnover()가 로드. 탐색 순서: EXE 옆 → _MEIPASS → 스크립트 디렉터리
│                            EXE 옆에 갱신본 배치 시 자동으로 우선 적용 (사용자 수동 수정 지원)
├── complex_molit_map_review.xlsx  매핑 검토용 Excel (자동 생성)
│                            시트: 전체매핑 / 수동검토(fuzzy+미매칭) / 미매칭
│                            'MOLIT아파트명(매핑)' 컬럼 수정 후 --from-review로 반영
├── build_aptseq_map.py    Naver 단지코드 → MOLIT aptSeq 매핑 구축
│                            Phase 1: complex_molit_map.json 기 매핑 단지 → MOLIT 12개월 데이터에서 aptSeq 조회 (빠름)
│                            Phase 2: 미매칭 단지 → Naver realPrice(Playwright)로 MOLIT 거래 매칭 → aptSeq
│                            결과: complex_aptseq_map.json (초기 1,388개)
├── expand_map_10y.py      10년 MOLIT 데이터로 미매칭 단지 추가 매핑 (연 1회 정도 재실행 권장)
│                            8구 × 120개월(960 API 호출) 수집 → fuzzy 재매핑 → 354개 추가
│                            결과: complex_molit_map.json 1,742개 / complex_aptseq_map.json 1,742개
│                            실거래 단지 대비 회전율 커버율: 91.3% (125개 미매핑 = 노후단지·동 단위 등록)
├── complex_aptseq_map.json Naver 단지코드 → MOLIT aptSeq 매핑 (1,742개, 2,060개의 84.6%)
│                            {단지코드: "27260-78"} 형식. aptSeq는 MOLIT 시군구별 고유 단지 식별자
├── check_molit_coverage.py 실거래가 단지 ↔ 호가 단지 매핑 커버율 확인 도구 (개발/검증용)
├── lookup_unmatched_molit.py  미매칭 단지 원인 분석 도구
│                            - complex_molit_map_review.xlsx 미매칭 시트 읽기
│                            - MOLIT 실거래가 API(최근 12개월)로 구별 단지 수집
│                            - 원인 4분류: 해당동 거래없음 / 이름달라정확매칭 / 퍼지후보 / 이름불일치
│                            - 결과: complex_molit_unmatched_analysis.xlsx
├── complex_molit_unmatched_analysis.xlsx  미매칭 원인 분석 결과 (자동 생성)
│                            시트: 미매칭원인분석(777행) / 후보있음_수동매칭 / MOLIT단지목록(12개월)
├── 사용설명서.txt          EXE 비개발자용 사용설명서 (spec post-build hook으로 EXE 옆 자동 포함)
├── 엑셀_데이터_명세.md      수집 결과 Excel 컬럼 상세 명세 (spec post-build hook으로 EXE 옆 자동 포함)
├── CLAUDE.md              이 파일
└── README.md              프로젝트 문서 (개발자용)
```

---

## Claude 명령어 규칙

### `md 갱신하기`

이 명령어를 받으면 **모든 `.md` 파일을 순서대로 읽고**, 현재 코드·데이터와 맞지 않는 내용을 찾아 갱신한다.

확인 대상:
- `daegu_apt/CLAUDE.md` — 수집 방식, 컬럼 설명, 소요 시간 표, 검증 현황 등
- `daegu_apt/WORKLOG.md` — 최신 작업 내역이 누락된 경우 추가

갱신 기준:
- 실제 코드(`naver_scraper.py`, `location_enricher.py`, `main.py` 등)와 설명이 다른 경우
- 수집 결과 시트·컬럼 목록이 실제와 다른 경우
- 파일 구조표(`daegu_apt/` 파일 목록)에 없는 파일이 생겼거나 삭제된 경우
- 작업 일지에 최근 변경사항이 빠진 경우

---

## 작업 일지

→ **[WORKLOG.md](WORKLOG.md)** 에서 관리
