# 대구 아파트 부동산 데이터 수집기

대구광역시 아파트의 **현재 호가(매물 가격)**, **실거래가**, **지하철 도보시간**, **근처 초등학교** 정보를 자동 수집해 Excel 파일로 저장합니다.

## 수집 데이터

| 구분 | 출처 | API 키 | 실행 |
|------|------|--------|------|
| 호가 (현재 매물 가격) | 네이버 부동산 (Playwright) | 불필요 | `main.py` |
| 지하철·초등학교·마트·공원·어린이집 | 카카오 Local API | 카카오 키 | `main.py` |
| 실거래가 (확정 거래) | 국토교통부 공공데이터 | 국토부 키 | `main.py` 또는 `main_molit.py` |

## 설치

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

## API 키 설정

`.env` 파일에 국토교통부 API 키를 입력하면 `--molit-key` 없이 실행됩니다.

```
# daegu_apt/.env
MOLIT_API_KEY=your_key_here
```

API 키 발급: https://www.data.go.kr → "아파트매매 실거래가 상세자료" → 활용신청 (무료)

---

## 실행 방법

### 호가 수집 (`main.py`)

네이버 부동산 기반. Playwright 브라우저 사용.

```bash
# 수성구 호가 → 수성구_부동산_YYYYMMDD_HHMMSS.xlsx
python main.py --district 수성구

# 대구 전체 → 대구전체_부동산_YYYYMMDD_HHMMSS.xlsx
python main.py

# 실거래가 함께 수집
python main.py --district 수성구 --molit-key YOUR_KEY

# .env에 키 설정 시 생략 가능
python main.py --district 수성구
```

| 옵션 | 기본값 | 설명 |
|------|--------|------|
| `--district` | all | 지역: all \| 중구 \| 동구 \| 서구 \| 남구 \| 북구 \| 수성구 \| 달서구 \| 달성군 |
| `--source` | both | 소스: both \| naver \| molit |
| `--months` | 3 | 실거래가 최근 N개월 |
| `--molit-key` | .env 참조 | 국토교통부 API 키 |
| `--output` | 자동 | 출력 파일명 |

### 실거래가 단독 수집 (`main_molit.py`)

네이버 불필요. API 키만 있으면 즉시 실행.

```bash
# 수성구 최근 3개월 → 수성구_실거래가_YYYYMMDD_HHMMSS.xlsx
python main_molit.py --district 수성구

# 대구 전체 최근 12개월
python main_molit.py --months 12

# 수성구 12개월 (API 요청 12회)
python main_molit.py --district 수성구 --months 12
```

| 옵션 | 기본값 | 설명 |
|------|--------|------|
| `--district` | all | 수집 지역 |
| `--months` | 3 | 최근 N개월 |
| `--molit-key` | .env 참조 | 국토교통부 API 키 |
| `--output` | 자동 | 출력 파일명 |

> API 요청 횟수 = 구 수 × 개월 수 (수성구 12개월 = 1 × 12 = 12회)

---

## 출력 Excel 시트

### `main.py` 출력

| 시트 | 내용 | 헤더 색상 |
|------|------|---------|
| **호가_단지요약** | 단지×평형 1행, 매매/전세/월세 통계 + 위치 정보(지하철·학교·마트·공원·어린이집) + 회전률 | 파란색 |
| **매물상세** | 개별 매물 가격 목록 (매매 매물 있는 전체 단지, 전 페이지 완전 수집) + 동일매물·중개사 참고 컬럼 | 주황색 |
| **실거래가** | 국토교통부 실거래 데이터 (키 있을 때만) | 보라색 |

> 갭투자 분석은 별도 시트 없이 호가_단지요약의 매매_최저 − 전세_최고로 계산 가능.

#### 호가_단지요약 컬럼

```
지역(구) | 지역(동) | 단지명 | 건축년월 | 총세대수 | 전용평형(평)
| 매매_최저/최고/평균(만원) | 매매_매물수
| 전세_최저/최고/평균(만원) | 전세_매물수 | 월세_매물수
| 5억이하매물수(호가)
| 단지코드 | 위도 | 경도
| 근처지하철 | 지하철도보(분) | 근처초등학교 | 초등학교거리(m/분)
| 인근대형마트(5km) | 인근공원(1km) | 인근어린이집(1km)
| 회전률(N개월%)   ← molit-key 있을 때
```

- 단지×평형 1행: 단지에 25·32·59평이 있으면 3행 출력. 매매 없는 단지도 포함.

#### 매물상세 컬럼

```
지역 | 단지명 | 단지코드 | 거래유형 | 가격(만원)
| 공급평형 | 전용평형 | 전용률(%) | 공급면적㎡ | 전용면적㎡ | 층 | 방향 | 등록일 | 매물번호
| 동일매물수 | 동일_최저가(만원) | 동일_최고가(만원)
| 중개사명(참고) | 중개사_코멘트(참고) | 태그(참고)
```

- 전 페이지 완전 수집(page.evaluate fetch). `(참고)` 컬럼은 비정형 데이터로 분석 시 낮은 가중치 권장.

### `main_molit.py` 출력

| 시트 | 내용 | 헤더 색상 |
|------|------|---------|
| **실거래가** | 국토교통부 실거래 전체 필드 + 지하철 근사치 | 보라색 |

#### 실거래가 컬럼

```
구 | 법정동 | 도로명 | 아파트명 | 건축년도 | 전용면적㎡ | 층
| 거래금액(만원) | 거래유형 | 거래년도 | 거래월 | 거래일 | 등기일자
| 해제여부 | 해제사유발생일
| 근처지하철 | 지하철도보(분) | 위도 | 경도
```

- **거래유형**: 직거래 / 중개거래
- **해제여부**: O = 계약 취소된 거래
- **근처지하철/도보**: 법정동 중심 좌표 기반 추정 (하드코딩 67개 역)

---

## 가격 평균 계산 방식 (`main.py`)

매물 상세를 전 페이지 완전 수집하므로 평형별 매매/전세 평균은 **수집된 개별 매물 가격의 실제 평균**으로 계산.

## 수집 소요 시간 (2026-06-13 최적화 후 실측)

| 명령 | 예상 시간 |
|------|----------|
| `main.py --district 서구/중구/남구` | 5~6분 |
| `main.py --district 수성구/달서구` | 18~20분 |
| `run_all.py` (8개 구, 2개 동시) | 약 53분 |
| `main_molit.py --district 수성구` | 수초 |
| `main_molit.py` (대구 전체 12개월) | 1분 이내 |

---

## 파일 구조

```
daegu_apt/
├── main.py              호가+실거래가 통합 수집 (Naver + 국토교통부)
├── main_molit.py        실거래가 단독 수집 (국토교통부만, Naver 불필요)
├── run_all.py           8개 구 수집 (2개 구 동시 실행 + 구별 시간 측정)
├── run_districts.py     지정 구 순차 수집 (단일 프로세스)
├── verify_run.py        정합성 검증 (기준 vs 신규 엑셀)
├── naver_scraper.py     네이버 부동산 수집 (Playwright)
│                          Phase 1: 매매 마커 수집 (cortarNo 순회)
│                          Phase 2: 전세 마커 수집 (cortarNo 순회)
│                          Phase 3: 매물 상세 (A1 방문 + page.evaluate fetch 페이지네이션)
│                          이미지·타일 차단으로 networkidle 가속
├── molit_scraper.py     국토교통부 실거래가 API + 법정동 기반 지하철 추정
├── location_enricher.py 위치 정보 보강 (카카오 Local API)
│                          - 지하철·초등학교·마트·공원·어린이집 + 좌표→구·동
│                          - 5스레드 병렬 + location_cache.json 캐시
│                          - 카카오 키 없으면 하드코딩 67개 역 좌표 fallback
├── daegu_cortars.json   8개 구 cortarNo 커버리지 포인트
├── daegu_boundaries.json 행정구역 폴리곤 (SGIS)
├── location_cache.json  카카오 위치조회 캐시 (자동 생성)
├── .env                 API 키 (KAKAO_API_KEY, MOLIT_API_KEY)
├── requirements.txt     패키지 목록
├── build_gui.bat        GUI EXE 빌드
├── CLAUDE.md            Claude AI 실행 가이드
└── README.md            이 파일
```

---

## 기술 노트

### 네이버 수집 방식

- **마커 수집**: `page.goto()`로 동(cortarNo) URL 방문 → 브라우저가 markers API 자연 호출. 이미지·타일을 차단해 networkidle을 빠르게 해소.
- **매물 상세**: A1(매매) 페이지 1회 방문으로 세션을 데운 뒤, 2페이지 이후·전세는 `page.evaluate` 안 `fetch`로 수집. 브라우저와 동일한 네트워크 스택이라 직접 호출(`ctx.request.get`)이 받는 429/401을 회피하고 전 페이지를 완전 수집.

### 가격 파싱

```
"3억 2,000" → 32,000만원
"8,500"     → 8,500만원
```

## EXE 빌드

```bat
build.bat
```

생성 후: `dist\daegu_apt.exe --district 수성구`
