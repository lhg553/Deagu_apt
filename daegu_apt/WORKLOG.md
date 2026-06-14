# 대구 부동산 수집기 — 작업 일지

---

## 2026-06-12 — cortarNo 기반 수집 방식 도입

**사용자 지시**
기존 bbox 격자 방식의 단지 누락 문제 해결 요청.

**문제 원인**

기존 bbox 격자 방식의 두 가지 근본 문제:
1. `single-markers` API가 bbox당 최대 ~100개 반환 → 단지 밀집 지역에서 조용한 누락
2. 산악·공업지대 빈 격자도 모두 순회 → 불필요한 시간 소모

**해결 방안 탐색**

- 처음엔 한국부동산원 단지코드 → 네이버 단지코드 매핑 방식 검토
- 네이버 `single-markers/2.0` API가 `cortarNo`(법정동 코드) 파라미터를 지원한다는 것을 발견
- `api/cortars` 엔드포인트가 특정 좌표의 법정동 cortarNo와 중심 좌표를 반환함을 확인
- **채택 방식**: 동 단위 cortarNo로 네이버 URL 방문 → 자연 발생하는 API 콜을 인터셉트

**구현 내용**

1. `build_daegu_cortars.py` 신규: 구별 bbox 격자 순회하며 `api/cortars` 응답 인터셉트 → `daegu_cortars.json` 생성
2. `daegu_cortars.json`: 8개 구 118개 동 (중구9·동구31·서구6·남구3·북구22·수성구19·달서구19·달성군9)
3. `naver_scraper.py`: `_load_cortars()` 함수 추가, Phase 1+2를 동 순회로 전환. 파일 없으면 격자 fallback

**검증 — 남구 비교 테스트 (test_compare_namgu.py)**

| | 격자 방식 | cortarNo 방식 |
|--|---------|-------------|
| 단지 수 | 150개 | 145개 |
| 수집 시간(Phase 1+2) | ~25초 | ~17초 |

**5개 차이 단지 분석**

격자에만 있는 5개: 대명이파크(주상복합), 봉덕2차화성파크드림, 봉덕맨션, 앞산힐스테이트, 힐스테이트앞산센트럴

- **대명이파크(주상복합)**: 주소는 남구 성당로 142이나, 네이버 내부적으로 서구 cortarNo 소속으로 분류됨. 남구/서구 경계선 바로 위에 위치. SGIS 폴리곤과 Naver 내부 폴리곤 경계 불일치
- 나머지 4개: 봉덕·앞산 지역 경계 단지로 동일한 경계 불일치 가능성
- **결론**: cortarNo 방식이 오히려 더 정확. 격자 방식은 bbox 겹침으로 인접 구 단지를 잘못 포함했을 가능성. 영향 < 3% (150개 중 5개)

---

## 2026-06-12 (2) — 법정동/행정동 문제 발견 및 클러스터링 개선

**사용자 의문 제기**

> "cortarNo는 동을 지정해서 하는건데 왜 폴리곤 필터로 걸러야되는지?"  
> "naver경계단지가 naver내부적으로 인접 구 cortarNo에 매핑되어있다는 건 전혀 설득이 안 된다"  
> (남구 Naver 지도 스크린샷 첨부) "전혀 틀린 것 같아, 다른 이유가 있나봐"

**초기 가설 반박**

처음엔 누락 5개 단지가 다른 구 cortarNo 소속이라고 판단했으나, 사용자가 남구 Naver 지도 스크린샷으로 해당 단지들이 정상적으로 남구에 표시됨을 확인해 반박.

**실제 원인 파악**

Playwright로 3개 cortarNo centroid의 실제 뷰포트 스크린샷 촬영:
- **봉덕동 centroid(35.829)**: 뷰포트 왼쪽 절반이 앞산공원(산). 실제 봉덕 주거지역(봉덕2동, 봉덕3동)은 화면 밖

남구청 공식 행정구역 데이터 확인:
- 봉덕동(법정동) = 봉덕1동(0.49㎢) + 봉덕2동(3.06㎢) + 봉덕3동(2.69㎢)
- 대명동(법정동) = 대명1동~11동 (합계 ~10㎢, 대명9동=3.38㎢가 앞산 포함)
- api/cortars가 반환하는 centroid는 법정동의 임의 대표점 → 전체 동 커버 불가

**폴리곤 필터가 필요한 이유 확인**

zoom-15 뷰포트는 약 1.5km × 1.7km 범위. `single-markers?bounds=...`(viewport-based)도 함께 발화되어 인접 구 단지를 같이 캡처함.  
남구 예: seen 345개 중 200개가 수성구·달서구·중구 단지 → 폴리곤이 걸러냄. 폴리곤 필터는 여전히 필요.

**개선 내용 (사용자 지시: "당연히 재구성해야지")**

`build_daegu_cortars.py` 전면 재작성:
- 기존: api/cortars 반환 centroid 1개 저장
- 개선: 격자 포인트 자체를 cortarNo별로 수집 → zoom-15 뷰포트 크기(CLUSTER_DLAT=0.007°, CLUSTER_DLON=0.010°) 셀로 클러스터링 → 다중 커버리지 포인트 저장

전체 8개 구 재생성: 118개 항목 → 331개 항목

**남구 검증 결과**

| | 개선 전 | 개선 후 |
|--|--------|---------|
| cortarNo 동 수 | 3개 | 2개 |
| 커버리지 포인트 | 3개 | 22개 |
| 수집 단지 | 145/150 | **150/150** |
| seen(폴리곤 전) | 345개 | 537개 |
| 폴리곤 걸러낸 단지 | 200개 | 387개 |

---

## 2026-06-13 (1) — 매물상세 공인중개사 코멘트·태그 필드 추가

**사용자 질문**

> "매물정보에 공인중개사의 코멘트를 딸 수 있는지?"

**탐색**

`test_naver_apis.py`로 `/api/articles/complex/{id}` 응답(매물 목록 API) 분석.

**발견**

- `articleFeatureDesc`: 공인중개사가 직접 입력하는 자유 텍스트 코멘트 (예: "빠른입주도 가능 방2개 욕실 1 녹지 전망")
- `tagList`: Naver 자동 분류 태그 목록 (예: ["25년이내", "탑층", "방두개", "화장실한개"])
- `realtorName`: 해당 매물을 올린 중개사 상호명
- 위 세 필드 모두 **추가 API 호출 없이** 이미 수집 중인 목록 응답에 포함됨

**논의 과정**

- 단지요약 시트에 추가 여부 검토 → 불필요 (집계값과 성격 다름)
- `sameAddrCnt > 1` 동일매물 처리: 현재 대표 1건만 수집하므로 코멘트도 그 1건 기준. 다른 중개사 코멘트는 미수집 → 별도 처리 불필요로 결론

**구현**

`naver_scraper.py` 매물 조립 부분에 3컬럼 추가 (매물상세 시트에만):
- `중개사명(참고)` ← realtorName
- `중개사_코멘트(참고)` ← articleFeatureDesc
- `태그(참고)` ← tagList (쉼표 구분 문자열)

컬럼명에 `(참고)` 명시, CLAUDE.md에 LLM 분석 시 낮은 가중치 권장 주석 추가.

---

## 2026-06-13 (2) — Naver API로 Kakao 위치정보 대체 시도 (미완료)

**사용자 질문**

> "지금 Kakao API로 가져오는 데이터들을 Naver에서 처리할 수 있는지?"

**현재 Kakao API 역할**

| 기능 | Kakao 카테고리 |
|------|--------------|
| 지하철역 이름 + 도보시간 | SW8, 반경 3km |
| 초등학교 이름 + 거리 | SC4, 반경 1~2km |
| 대형마트 이름 + 거리 | MT1, 반경 5km |

**탐색 과정**

1. `test_naver_apis.py`로 단지 페이지 방문 시 발화되는 모든 API URL 로깅
2. 단지 기본 페이지(`/complexes/{id}?a=APT&b=A1`) 방문으로 발화되는 API 목록:
   - `/api/complexes/overview/{id}`: 세대수·동수·입주일·평형 기본 정보만, 학교·교통 없음
   - `/api/articles/complex/{id}`: 매물 목록
   - `/api/cortars`, `/api/developmentplan/...` 등 지도 관련 API
3. 단지정보 탭 클릭 시도:
   - `page.locator('text=단지정보').click()` → element not visible (headless 브라우저)
   - `page.evaluate()` JS click → `BUTTON complex_link` 클릭 (잘못된 요소)
4. `/complexes/{id}/detail` URL 직접 이동 → 지도 메인 페이지로 리다이렉트
5. `page.evaluate()` fetch 직접 호출 → **HTTP 401** (SPA 내부 라우팅에서만 인증 통과)
6. `/api/complexes/{id}?initial=Y` 한 번 우연히 캡처됨 (키: `['complex', 'areaList', 'complexExistTabs', 'photos', 'dividePhotosBySix']`) — 재현 불가

**결론: Kakao API 유지**

- 학교·교통 데이터는 Naver 단지정보 탭 클릭 시에만 로드 → headless 브라우저에서 안정적 트리거 불가
- `initial=Y` API는 SPA 내부 라우팅 전용, 직접 호출 시 401
- Phase 3 기존 단지 페이지 방문만으로는 해당 API 미발화
- 대형마트(MT1)는 Naver에 해당 데이터 자체 없음
- Kakao API가 더 단순·안정적

**미해결 사항**

`/api/complexes/{id}?initial=Y` 응답의 `complex` 객체에 실제로 학교·교통 필드가 있는지 확인하지 못함.  
만약 필요하다면, Phase 3 내 SPA 라우팅 방식(Playwright `page.evaluate`로 history.pushState 등) 추가 탐색 필요.

---

## 2026-06-13 (3) — 수집 속도 최적화 + 매물 완전 수집

**사용자 지시**

> "수집 속도가 너무 느린데 빠르게 할 방법 없니?"  
> 작은 구 → 큰 구 → 전체 순으로 테스트하며 매번 시간과 데이터 정합성 검증.  
> "매매 받을 때 전세 응답도 같이 오는지 확인해서 한 번에 처리 가능한지" (방문 횟수 절감 아이디어)

**병목 분석**

- Phase 3(단지별 페이지 방문)가 전체 시간의 대부분. `wait_until='networkidle'`이 지도 타일 스트리밍 때문에 늦게 풀리고, 단지당 sleep 1.0~2.5초까지 더해짐.
- 카카오 위치보강은 단지당 6종 API 순차 호출 + sleep.

**시도와 실패 (중요 — 같은 함정 반복 방지)**

1. **markers/articles 직접 호출(`ctx.request.get`)로 전환** → 즉시 **429**. 쿨다운 10분 후에도 첫 호출부터 429. 원인: Playwright `ctx.request`는 브라우저와 **별도 HTTP 스택**이라 TLS 지문이 달라 Naver가 봇으로 차단. (기존 `_fetch_extra_pages`도 직접 호출이었으나, 대부분 단지가 20건 미만이라 페이지네이션이 거의 발동 안 했고, 발동해도 429에 조용히 중단되어 **빅 단지 매물이 1페이지만 남고 잘리던 잠재 버그**였음)
2. **`wait_until='domcontentloaded'` + sleep** → 마커 0개 캡처. SPA가 JS 번들 실행 전이라 markers API 미발화.
3. **`page.expect_response`** → Playwright sync API의 `Waiter.reject_on_event` KeyError 폭주 (상시 `page.on('response')` 핸들러와 충돌하는 알려진 버그). 캡처 깨짐.

**채택 해법**

1. **무거운 리소스 차단** (`page.route`로 image·media·font abort): networkidle이 빠르게 풀림. markers·articles XHR은 통과 → 캡처 신뢰성 유지하며 대기 시간만 제거. (가장 큰 효과)
2. **`page.evaluate` 안 `fetch`로 페이지네이션**: 브라우저 페이지 컨텍스트에서 실행 → SPA와 동일한 네트워크 스택 → 429/401 회피. 진단 결과 page2/3 전부 status 200. 단지 6935: 옛 ~18건 → 실제 48건 완전 수집.
3. **전세 단지별 방문 제거**: A1 페이지 1회 방문으로 세션 워밍 + auth 헤더·URL 캡처 후, 전세(B1)는 navigation 없이 `page.evaluate` fetch로 수집. `tradeType=B1` 명시(빈값 `''`은 월세까지 끼어 페이지가 불어나므로 미사용). 달서구 기준 165회 방문 절약.
4. **카카오 5스레드 병렬 + `location_cache.json` 캐시**.
5. **`run_all.py`로 2개 구 동시 실행**: 2 브라우저 = 사용자 2명 수준, 429 0건 확인.

**검증 (verify_run.py 신규)**

기준 엑셀 vs 신규 엑셀 비교: 단지 집합 일치, 요약↔상세 매물수 일치, 위치 채움률, 가격 이상치, 참고 컬럼 존재 체크.

| 단계 | 결과 |
|------|------|
| 남구 (small) | 6분26초, 150/150 일치, 통과 |
| 달서구 (big) | 19~24분, 430/430 일치, 통과 |
| 전체 8구 | wall-clock 52.9분(2개 동시), 8/8 통과, 429 0건 |

- 단지 집합은 8개 구 전부 직전 베이스라인과 정확히 일치(누락 0).
- 매물상세 총 ~2만 → ~4.7만건(2.4배). 과수집 아니라 옛 1페이지 절단 버그를 고쳐 같은 단지의 누락 페이지를 회수한 것.

**미해결/후속**

- 동시 실행 수를 3개 이상으로 올리면 더 빠르나 429 위험 미검증 (현재 2개로 안전 확인).

---

## 2026-06-13 (4) — regions/complexes 전환 (누락·구 오귀속 동시 해결)

**사용자 의문**

> "실질누락이 있으면 안 되는 거 아니야? 매물 없어도 단지가 있으면 요약엔 단지정보라도 쓰게 했잖아. 왜 자꾸 누락? 실거래보다 무조건 요약에 단지가 많아야지."

**원인 규명**

달성군 누락 단지(다사세천한라비발디 등)를 추적:
- single-markers는 cortarNo가 아니라 **지도 뷰포트(화면 범위)** 기준으로 단지를 반환 → 넓은 동(다사읍)에서 뷰포트 사이 틈에 단지가 빠짐.
- check_missing의 "누락 19개"는 대부분 **가짜**였음(이름 불일치): 대구세천한라비발디↔다사세천한라비발디, 대실역e-편한세상↔대실역이편한세상, 서재보성타운1차↔서재보성1 등.
- 진짜 누락은 소수(죽곡한신휴플러스·푸르지오2 등).

**해법 발견 — regions/complexes API**

`new.land.naver.com/api/regions/complexes?cortarNo={동}&realEstateType=APT` 가
**동 단위 전체 단지**(뷰포트·매물 여부 무관)를 complexNo·이름·좌표·세대수·건축년월·dealCount/leaseCount까지 반환.
`page.evaluate` fetch로 호출(429 회피). Phase 1/2를 뷰포트 markers → regions/complexes로 교체.

**법정동 목록 권위화 — regions/list**

`regions/list?cortarNo={상위}` 로 대구 → 구 → 법정동 계층을 받아 `build_cortars_hier.py`로 재생성.
- 기존 daegu_cortars.json(뷰포트 샘플링)은 법정동 대거 누락: 중구 9/57, 동구 31/45, 북구 22/31 등.
- 신규: 8개 구 **204개 법정동** (공식 행정 계층, 누락 없음).

**검증 (regions vs 기존 뷰포트)**

- **달성군**: 진짜 누락 2개(죽곡한신휴플러스·푸르지오2) 회수, 옆 구 누수 2개(대곡역화성타운=달서구·드림팰리스) 제외.
- **중구**: 111→104. 빠진 7개 전부 **다른 구 단지**(신천주공2차=동구, 양지=북구, 태왕아너스클럽=수성구, 이랜드피어대명1·2=남구, 제네스빌=서구) — 뷰포트+폴리곤버퍼가 잘못 포함했던 누수. regions가 법정동 경계로 정확히 제외.

**결론**: regions 방식이 (1) 뷰포트 누락 제거 (2) 옆 구 오귀속 제거 → 더 완전하고 정확. 기존 viewport single-markers는 cortars 파일 없을 때 fallback으로만 유지.

**코드 변경**
- `naver_scraper.py` collect(): Phase 1/2를 regions/complexes(page.evaluate fetch)로 교체, `_add_complex()` 추가. 격자/뷰포트 경로는 fallback.
- `build_cortars_hier.py` 신규: regions/list 계층으로 daegu_cortars.json 재생성.
- `daegu_cortars.json`: 331 뷰포트포인트 → 204 법정동(권위).

**전체 재수집 결과 (2026-06-13, regions)**
- 8개 구 2,060개 고유 단지, 구간 중복 0 (옛 viewport는 42개 중복). 전체 41.1분.
- 결과물은 `대구부동산_수집결과_20260613/` 폴더에 8개 구 + 대구전체 통합본 + 엑셀_데이터_명세.md.

---

## 2026-06-13 (5) — GUI 다중선택·2개 동시 실행 + EXE 재빌드

**사용자 지시**: GUI 편의성 개선 — 대구전체 옵션 제거+전체선택 버튼, 구 다중 체크박스, 여러 구 수집 후 개별+통합 파일, 2개씩 동시 실행. EXE에 모든 변경 반영.

**구현**
- `gui.py`: 단일 라디오 → 8개 구 체크박스 + 전체선택/해제. 저장은 폴더 선택. 워커가 `ThreadPoolExecutor(max_workers=2)`로 2개 구 인프로세스 동시 수집 → 개별 파일 + `대구통합_부동산_*.xlsx`.
  - Playwright sync API 2스레드 동시 실행 가능함을 검증(greenlet 충돌 없음). EXE는 subprocess로 스크립트 실행 불가라 인프로세스 방식 채택.
  - `_LogWriter`를 스레드별 버퍼 + `[구명]` 접두사로 개편(병렬 로그 구분).
- `combine.py` 신규: 시트별 병합(통합 파일).
- `location_enricher.py`: `_save_loc_cache` 병합 저장(동시 수집 캐시 클로버 방지).
- `build_gui.bat`: `daegu_cortars.json`·`combine` 누락 추가, `--noconfirm`. (기존 EXE엔 cortars가 빠져 격자 fallback이었음)

**EXE 재빌드**: dist2\daegu_apt_gui — regions 방식 + 204 법정동 cortars + 2개 동시 GUI 반영, 정상 기동 확인. (+ 사용설명서.txt 동봉, GUI에 API키 힌트·❓사용법 버튼 추가)

---

## 2026-06-13 (6) — 지역(구)/(동) 출처를 cortarNo로 + 달성군 남부 누락 수정

**사용자 지적**: 대구전체 통합본에 일부 행(달성군)의 지역(구)·지역(동)·근처지하철 이하가 비어 있음.

**원인**
1. 지역(구)/(동)을 Kakao 역지오코딩(`_kakao_region`)으로 채우는데, 정작 우리는 법정동 cortarNo로 조회 중이라 구·동을 이미 알고 있음 — 불필요한 경로였고 실패 지점.
2. `location_enricher`의 대구 좌표 게이트 `DAEGU_LAT=(35.70,36.05)`가 너무 좁아 **달성군 남부(구지면·유가읍, 위도 35.65)** 34개 단지(72행)가 범위 밖으로 판정 → Kakao 호출 전체 스킵 → 구·동·지하철·마트 모두 공란.

**수정**
- `naver_scraper.py`: `_add_complex(c, gu, dong)` — 조회 중인 cortarNo의 구(=district 또는 _CORTARS 매핑)·동 이름을 단지 레코드에 직접 기록. 요약 rows에 `지역(구)`·`지역(동)` 포함.
- `location_enricher.py`: df에 `지역(구)`가 이미 있으면 Kakao 역지오코딩 생략(`need_region=False`, 호출 1개 절약)·삽입 안 함. `DAEGU_LAT=(35.55,36.10)`, `DAEGU_LON=(128.30,128.90)`로 확장.

**검증**: 달성군 재수집 → 지역(구)/(동)·지하철 공란 0, 남부 72행도 지하철·마트 정상. 대구전체 재통합 후 공란 0 (4,347행).

---

## 2026-06-13 (7) — 실거래가 12개월·배포 구조 개선

**사용자 지시**
- 아실 기준(1년 회전율)에 맞춰 실거래가 조회 기간 12개월로 변경
- 배포 폴더 이름 `dist2` → `release`로 정비
- 배포본에 사용설명서·엑셀 명세 파일 자동 포함

**변경 내용**

1. **`--months` 기본값 3 → 12** (`main.py`, `gui.py`, `run_districts.py`)
   - 회전률 컬럼명 `회전률(3개월%)` → `회전률(12개월%)`(months 파라미터 반영 자동)
   - 아실이 국토부 실거래분석 데이터를 1년 기준으로 집계하는 것과 통일

2. **배포 폴더 `dist2` → `release`** (폴더 rename + `build_gui.bat`, CLAUDE.md 전수 수정)

3. **`daegu_apt_gui.spec` post-build hook 추가**
   - `사용설명서.txt`, `엑셀_데이터_명세.md`를 spec 파일 내 Python 코드로 EXE 옆에 자동 복사
   - `build_gui.bat`을 `--add-data` 나열 방식 → `daegu_apt_gui.spec` 기반으로 단순화
   - 효과: `pyinstaller ... spec` 어떤 방식으로 빌드해도 문서 파일이 항상 포함됨

4. **Python UTF-8 인코딩 설정** CLAUDE.md에 명시 (`$env:PYTHONIOENCODING = "utf-8"`)

**대명자이그랜드시티 분석** (MOLIT API 미수록 원인 조사)
- 호가_단지요약에는 존재 (남구 대명동, 단지코드 153197, 2023세대)
- 남구 실거래가 181건 전체에 해당 단지 없음 — 이름 불일치 가능성 배제(전수 검색)
- 아실이 3·4·5월 거래를 '국토부 실거래분석' 출처로 표기
- **결론**: data.go.kr `getRTMSDataSvcAptTradeDev`(아파트 매매 실거래가)는 등기 완료 거래만 수록. 신규 대단지 초기 거래가 **분양권 전매**(`getRTMSDataSvcSilvTrade`)로 등록됐을 가능성이 높음. 현재 수집 범위 밖 — 향후 분양권 API 추가 시 포함 가능.

---

## 2026-06-14 — Naver↔MOLIT 단지명 매핑 시스템 도입 (회전률 커버리지 개선)

**사용자 지시**
> 요약 시트와 실거래가 시트의 아파트명이 맞지 않아 회전률이 안 나오는 문제 해결.
> 단지코드↔아파트명 매핑 데이터를 미리 만들어서 매번 재계산 대신 재사용.

**문제 원인**

`_add_turnover()`가 Naver 단지명과 MOLIT 아파트명을 공백 제거 후 직접 비교.
- Naver는 `(주상복합)`, `(도시형)` 등 suffix 추가
- MOLIT은 공식 등기명 사용 (예: `동인동삼정그린코아` vs `동인삼정그린코아`, `e편한세상남산` → 그대로)
- 기존 커버리지: 2,060개 단지 중 678개(33%)만 회전률 계산

**해법: `complex_molit_map.json` 정적 매핑 파일**

`make_complex_map.py` 신규 작성. 4단계 자동 매칭:

| 단계 | 방식 | 매칭 수 |
|------|------|---------|
| 1 | 정확 매칭 (공백 제거) | 682개 |
| 2 | suffix 제거 후 매칭 `(주상복합)·(도시형)` 등 | 190개 |
| 3 | 같은 구+동 내 fuzzy (cutoff 0.78) | 234개 ★ |
| 4 | 같은 구+건축년도 내 fuzzy (cutoff 0.65) | 177개 ★ |
| — | 미매칭 | 777개 |

★ fuzzy 매칭 — 차수(1차/2차), 동호(A동/B동), 단지번호, 지구번호 충돌 시 자동 거부.

**결과**

- 총 **1,283개** 자동 매핑 완료 (`complex_molit_map.json`)
- 고유 단지 회전률 커버리지: **678 → 1,105개 (33% → 54%)**
- fuzzy 422개 + 미매칭 777개는 `complex_molit_map_review.xlsx` → `수동검토` 시트에서 검토 가능
- 수동 검토 후 `python make_complex_map.py --from-review` 로 JSON 반영

**코드 변경**

- `main.py`:
  - `_load_complex_map()` 추가 — EXE 옆 → `_MEIPASS` → 스크립트 디렉터리 순 탐색
  - `_add_turnover()` 개선 — 단지코드로 매핑 우선 적용, fallback은 기존 이름 정규화
- `daegu_apt_gui.spec`:
  - `datas`에 `complex_molit_map.json` 추가 (`_internal/` 번들)
  - post-build hook에 `complex_molit_map.json` 추가 (EXE 옆 복사 → 사용자 수정 가능)

---

## 2026-06-14 (2) — 미매칭 단지 원인 분석 (lookup_unmatched_molit.py)

**사용자 질문**
> complex_molit_map_review.xlsx 의 미매칭 단지에 실거래가 데이터가 왜 없는지, MOLIT API로 찾아볼 수 있는지?

**분석 방법**

`lookup_unmatched_molit.py` 작성: 미매칭 777개 단지에 대해 구별 MOLIT 실거래가(최근 12개월)를 조회 후 같은 동 내 이름 퍼지 매칭으로 원인 분류.

**결과 (complex_molit_unmatched_analysis.xlsx)**

| 원인 | 건수 | 설명 |
|------|------|------|
| 동내 거래있으나 이름 불일치 | 639 | 같은 동 다른 아파트는 거래됐으나 이 단지는 12개월 내 거래 없음 |
| 퍼지 후보 있음 | 85 | 이름 유사 MOLIT 단지 발견 → 수동 확인 필요 |
| 해당동 최근12개월 거래없음 | 36 | 동 전체 거래 없음 (소규모·노후 지역) |
| 이름 달라 정확매칭 | 17 | 정규화 후 동일하나 주소번지 달라 실제 다른 건물 |

**핵심 결론**
- 639개 대부분은 1970~1990년대 노후 단지로 최근 12개월 MOLIT 실거래 자체가 없음 (매물만 있고 거래 없음)
- 퍼지 후보 85개는 동호수/별칭 차이 (예: `동촌미소타운(104동)` → MOLIT `동촌미소타운101동`·`102동`·`103동` 각각 등록)
- 회전률 0%로 표시되는 것이 맞는 상태

---

## 2026-06-14 (3) — 분양권 API 추가 + aptSeq 매핑 구축

**배경**

Naver 단지 overview의 `realPrice`(최근 실거래)가 MOLIT 아파트 매매 API에 없는 경우 조사:
- **분양권 전매** (`RTMSDataSvcSilvTrade`): 준공 전 분양권 거래는 아파트 매매 API에 없음
- 신규 대단지(대명자이그랜드시티 등) 초기 거래가 분양권 전매로 등록돼 회전율이 비정상적으로 높게 나올 수 있음

**molit_scraper.py 변경**

1. `aptSeq` 필드를 아파트 실거래 row에 추가 (MOLIT 시군구별 고유 단지 식별자, 형식: "27260-78")
2. 페이지네이션 수정: 기존 `numOfRows=1000` 단일 호출 → `totalCount` 기반 페이지 루프
3. `SILV_URL` 상수 추가 (분양권 API)
4. `_fetch_silv_page()` / `_fetch_silv()` / `collect_silv()` 추가
   - API 미승인(401/403/500 Unexpected) 시 빈 DataFrame 반환 (경고 출력)
   - 분양권 API는 `aptSeq` 미제공 → `jibun`(지번) 포함

**main.py 변경**

- `_add_turnover(silv_df=None)` 파라미터 추가
  - 분양권 거래수 > 0인 단지에 `분양권거래수(N개월)`, `⚠️회전율주의` 컬럼 추가
  - `⚠️회전율주의` = "분양권포함-회전율과대평가주의"
- MOLIT 수집 시 `scraper.collect_silv()` 호출 → `분양권실거래` 시트 저장 (보라색)

**build_aptseq_map.py 신규** + **complex_aptseq_map.json 신규**

Phase 1: `complex_molit_map.json` 기 매핑 1,283개 → MOLIT 12개월 실거래에서 (구, 정규화명) 키로 aptSeq 조회  
Phase 2: 미매칭 777개 단지 → Naver `realPrice` Playwright 캡처 → (구, 연, 월, 일, 금액) 복합키로 MOLIT 거래 매칭 → aptSeq 취득  
결과: **1,388 / 2,060개 (67.4%)** aptSeq 확보

**complex_molit_map.json 업데이트**

Phase 2에서 aptSeq 역방향(aptSeq → 아파트명)으로 105개 신규 이름 매핑 추가  
1,283개 → **1,388개** (미매칭 777 → **672**)

---

## 2026-06-14 (4) — 10년 MOLIT로 매핑 확장 + 회전율 커버리지 확인

**expand_map_10y.py 신규**

- 8구 × 120개월(960 API 호출, 267,355건) 수집 → 더 큰 MOLIT 풀로 fuzzy 재매핑
- 결과: 354개 추가 → name_map 1,388 → **1,742개** / aptSeq 1,388 → **1,742개 (84.6%)**
- 미매핑 672 → **318개**. 나머지는 10년간 MOLIT 실거래 없는 초노후·공공임대 단지

**회전율 커버리지 검증 (check_molit_coverage.py)**

대구통합_부동산_20260613_220927.xlsx 기준:
- 실거래가 고유 단지 1,442개 중 **1,317개 매칭 (91.3%)**
- 미매핑 125개 원인: ①노후단지(Naver 매물 없음) ②MOLIT 동(棟) 단위 등록(동촌미소타운101동·캐슬골드파크1단지 등)
- aptSeq 있으나 호가없음: 0개 — aptSeq로 연결된 건 전부 호가에 존재 확인

**엑셀_데이터_명세.md 주의사항 추가**

- 회전률 컬럼 설명에 "★아래 주의사항 참고" 및 분양권거래수·⚠️회전율주의 컬럼 추가
- 데이터 한계 요약에 회전률 미매핑 9% 한계 및 분양권 과대평가 주의사항 명시

---

## 2026-06-14 (5) — 근처중학교·고등학교 버그 수정 + combine.py 컬럼 순서 수정

**발견된 문제**

1. **중학교·고등학교 데이터 NaN**: location_cache.json의 기존 항목(2,060개 대부분)이 2026-06-13 이전에 저장된 것으로 `mid_name`/`high_name` 필드 자체가 없음. 캐시 hit 조건이 `key in cache`만 확인해 학교 필드 없는 오래된 항목도 hit 처리 → 모든 단지 중학교·고등학교 빈 값.

2. **combine 시 컬럼 위치 이상**: 일부 구는 중학교 컬럼이 있고(has_mid=True, 1개 단지), 나머지는 없음. 여러 구 파일을 `pd.concat` 하면 중학교 없는 파일이 앞에 와서 중학교 컬럼이 맨 뒤(회전률 뒤)에 붙음.

3. **combine.py 인수 순서 실수(재발)**: `중구_부동산_20260614_223000.xlsx`에 다른 7개 구 데이터가 덮어씌워져 **중구 원본 데이터 소실**. 통합본도 7개 구가 각 2번 중복.

**수정 내용**

**`location_enricher.py`**  
캐시 hit 조건에 `'mid_name' in cache[key]` 추가:
```python
# 변경 전
elif key and key in cache:
# 변경 후
elif key and key in cache and 'mid_name' in cache[key]:
```
→ 오래된 항목(mid_name 없음)은 캐시 미스로 처리 → 다음 수집 시 Kakao SC4 API 재조회 → 학교 데이터 정상 수집.

**`combine.py`**  
`_SUMMARY_COL_ORDER` 추가 + concat 후 `_reorder_summary()` 호출:
- 근처중학교·중학교직선거리(m/분)·근처고등학교·고등학교직선거리(m/분)가 인근대형마트(5km) 앞에 오도록 보장.

**조치 결과**

- 중구 데이터 재수집 완료 (229단지, 캐시 0개·신규 조회 104개, 중학교·고등학교 229행 전체 정상)
- 8개 구 통합본 재생성 → `대구통합_부동산_재생성_20260614.xlsx` (호가_단지요약 4,339행)
- 컬럼 순서 정상: [23] 근처중학교 → [24] 중학교직선거리 → [25] 근처고등학교 → [26] 고등학교직선거리 → [27] 인근대형마트
