"""
Naver Land 호가 수집기
- 매매/전세/월세 동시 수집 (단지별 전 거래유형 통합)
- 개별 매물 가격 수집 (단지당 10건 이하만 상세 조회, rate limit 방지)
- Naver 단지 상세 API로 지하철·초등학교 정보 수집 (API 키 불필요)
- 수집 결과: (summary_df, articles_df, loc_data)
"""
import time
import pandas as pd
from playwright.sync_api import sync_playwright

DISTRICT_CENTERS = {
    '중구':  [(35.870, 128.595)],
    '동구':  [(35.893, 128.678), (35.922, 128.715)],
    '서구':  [(35.869, 128.563)],
    '남구':  [(35.835, 128.600)],
    '북구':  [(35.920, 128.592), (35.952, 128.615)],
    '수성구': [(35.858, 128.627), (35.851, 128.672)],
    '달서구': [(35.848, 128.537), (35.853, 128.577)],
    '달성군': [(35.808, 128.526), (35.761, 128.500), (35.820, 128.430)],
}

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
      'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')

MARKERS_URL  = 'https://new.land.naver.com/api/complexes/single-markers/2.0'
ARTICLES_URL = 'https://new.land.naver.com/api/articles/complex/{}'
COMPLEX_URL  = 'https://new.land.naver.com/api/complexes/{}?sameAddressGroup=false'

TRADE_LABEL  = {'A1': '매매', 'B1': '전세', 'B2': '월세'}
MAX_ARTICLES = 10   # 단지당 개별 매물 조회 최대 건수 (rate limit 방지)


def _safe_int(v):
    try:
        return int(str(v).replace(',', '').strip())
    except Exception:
        return None


def _parse_price(price_str) -> int | None:
    """'3억 2,000' → 32000 (만원), '8,500' → 8500"""
    if not price_str:
        return None
    s = str(price_str).replace(',', '').strip()
    try:
        if '억' in s:
            parts = s.split('억')
            total = int(parts[0].strip()) * 10000
            rest = parts[1].strip()
            if rest:
                total += int(rest)
            return total
        return int(s.replace('만', ''))
    except Exception:
        return None


def _extract_naver_loc(data: dict) -> dict:
    """
    Naver 단지 상세 API 응답에서 지하철·초등학교 정보 추출.
    여러 필드명 패턴을 시도해 유연하게 처리.
    """
    result = {}
    if not isinstance(data, dict):
        return result

    # 응답이 중첩된 경우 여러 컨테이너 탐색
    containers = [data]
    for key in ('complexDetail', 'complex', 'complexInfo', 'landPriceInfo'):
        if isinstance(data.get(key), dict):
            containers.append(data[key])

    for obj in containers:
        if not isinstance(obj, dict):
            continue

        # ── 지하철 ──
        if 'subway_name' not in result:
            for key in ('nearbyStation', 'nearStation', 'subwayInfo', 'nearestStation', 'subway'):
                val = obj.get(key)
                if not val:
                    continue
                if isinstance(val, list):
                    val = val[0] if val else None
                if isinstance(val, dict):
                    name = (val.get('stationName') or val.get('name') or
                            val.get('subwayName') or val.get('railName') or
                            val.get('buscStopName', ''))
                    walk = (val.get('walkingTime') or val.get('walkTime') or
                            val.get('time') or val.get('travelTime', ''))
                    dist = val.get('distance') or val.get('dist', '')
                    if name:
                        name = str(name)
                        if not name.endswith('역'):
                            name += '역'
                        result['subway_name'] = name
                        result['subway_walk'] = str(walk) if walk else ''
                        result['subway_dist'] = str(dist) if dist else ''
                        break

        # ── 초등학교 ──
        if 'school_name' not in result:
            school = (obj.get('school') or obj.get('schoolInfo') or
                      obj.get('nearbySchool') or obj.get('schoolDetail') or {})
            if isinstance(school, dict):
                for key in ('elementary', 'elementarySchool', 'primarySchool',
                            'elementSchool', 'elemSchool'):
                    elem = school.get(key)
                    if not elem:
                        continue
                    if isinstance(elem, list):
                        elem = elem[0] if elem else None
                    if isinstance(elem, dict):
                        name = (elem.get('schoolName') or elem.get('name') or
                                elem.get('schNm') or elem.get('schName', ''))
                        dist = (elem.get('distance') or elem.get('dist') or
                                elem.get('distanceM', ''))
                        if name:
                            result['school_name'] = name
                            result['school_dist'] = str(dist) if dist else ''
                            break

    return result


def _refresh_session(page):
    """429 후 세션 리프레시: 지도 페이지를 탐색해 쿠키/세션을 재수립."""
    try:
        page.goto(
            'https://new.land.naver.com/?ms=35.858,128.627,15&a=APT&b=A1&e=RETAIL',
            wait_until='networkidle', timeout=25000
        )
        time.sleep(3)
    except Exception:
        pass


def _fetch_location_data(seen: dict, page) -> dict:
    """
    Naver 단지 상세 API를 page.request.get()으로 호출해 지하철·학교 정보 수집.
    현재 브라우저 세션(쿠키 포함)을 재사용해 별도 키 없이 가능.
    429 발생 시 세션 리프레시 후 무제한 재시도 (대기: 60s, 120s, 이후 120s 고정).
    """
    cids = list(seen.keys())
    loc_data: dict = {}
    print(f'  위치 정보 수집 중 ({len(cids)}개 단지)...')

    retry_count = 0
    i = 0
    while i < len(cids):
        cid = cids[i]
        status = None
        try:
            r = page.request.get(
                COMPLEX_URL.format(cid),
                headers={
                    'Accept': 'application/json, text/plain, */*',
                    'Referer': f'https://new.land.naver.com/complexes/{cid}?a=APT&b=A1',
                }
            )
            status = r.status
            if status == 200:
                loc = _extract_naver_loc(r.json())
                if loc:
                    loc_data[cid] = loc
                i += 1
                retry_count = 0
            elif status == 429:
                retry_count += 1
                wait = min(60 * retry_count, 120)
                print(f'\n  [rate limit] {i}/{len(cids)}개 완료 → 세션 리프레시 후 {wait}초 대기...')
                _refresh_session(page)
                time.sleep(wait)
            else:
                i += 1
        except Exception:
            i += 1

        if status != 429:
            time.sleep(0.15)
        if (i % 100 == 0 and i > 0) or i == len(cids):
            print(f'    [{i}/{len(cids)}] 위치 수집: {len(loc_data)}개 성공')

    return loc_data


def _fetch_articles(seen: dict, max_count: int) -> list:
    """
    각 단지 페이지를 브라우저로 직접 방문해 article API 응답을 자연 캡처.
    (page.request 직접 호출 대신 페이지 탐색으로 rate limit 우회)
    매매 1~max_count건 단지만 대상.
    """
    targets = [
        (cid, cx) for cid, cx in seen.items()
        if 0 < (cx.get('dealCount', 0) or 0) <= max_count
    ]
    if not targets:
        print('    조회 대상 없음')
        return []

    print(f'    대상: {len(targets)}개 단지 (매매 1~{max_count}건)')

    current = {'cid': None}
    buf: dict = {}

    def on_resp(resp):
        cid = current['cid']
        if not cid:
            return
        url = resp.url
        if f'articles/complex/{cid}' not in url and f'articleList?hscpNo={cid}' not in url:
            return
        if resp.status != 200:
            return
        try:
            data = resp.json()
            items = data if isinstance(data, list) else data.get('articleList', [])
            buf.setdefault(cid, []).extend(items)
        except Exception:
            pass

    fetched = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=UA, locale='ko-KR', viewport={'width': 1280, 'height': 800}
        )
        page = ctx.new_page()
        page.on('response', on_resp)

        for i, (cid, cx) in enumerate(targets):
            current['cid'] = cid
            try:
                page.goto(
                    f'https://new.land.naver.com/complexes/{cid}?a=APT&b=A1',
                    wait_until='networkidle', timeout=20000
                )
                time.sleep(1.5)
                if cid in buf:
                    fetched += 1
            except Exception:
                pass

            if (i + 1) % 10 == 0 or i == len(targets) - 1:
                print(f'    [{i+1}/{len(targets)}] 캡처 성공: {fetched}개')

        browser.close()

    articles = []
    for cid, items in buf.items():
        cx = seen.get(cid, {})
        for art in items:
            prc = _parse_price(art.get('dealOrWarrantPrc', ''))
            if prc:
                articles.append({
                    '단지명':    cx.get('complexName', ''),
                    '단지코드':  cid,
                    '거래유형':  art.get('tradeTypeName', '매매'),
                    '가격(만원)': prc,
                    '전용면적㎡': art.get('area2', ''),
                    '층':        art.get('floorInfo', ''),
                    '방향':      art.get('direction', ''),
                    '등록일':    art.get('articleConfirmYmd', ''),
                    '매물번호':  art.get('articleNo', ''),
                })

    return articles


class NaverLandScraper:
    def collect(self, district: str = 'all') -> tuple:
        """
        Returns
        -------
        summary_df  : 단지 수준 요약 (매매/전세/월세 최저·최고·평균·매물수)
        articles_df : 개별 매물 상세 (단지명, 거래유형, 가격, 면적, 층, ...)
        loc_data    : dict[cid → {subway_name, subway_walk, school_name, school_dist}]
        """
        centers = (
            [pt for pts in DISTRICT_CENTERS.values() for pt in pts]
            if district == 'all'
            else DISTRICT_CENTERS.get(district, [])
        )
        if not centers:
            print(f'  [경고] 알 수 없는 지역: {district}')
            return pd.DataFrame(), pd.DataFrame(), {}

        seen: dict = {}
        phase = {'v': ''}

        def on_resp(resp):
            if 'single-markers' not in resp.url or resp.status != 200:
                return
            for part in resp.url.split('&'):
                if part.startswith('tradeType='):
                    phase['v'] = part.split('=')[1]
                    break
            try:
                items = resp.json()
                if not isinstance(items, list):
                    return
                for cx in items:
                    mid = cx.get('markerId', '')
                    if not mid:
                        continue
                    if mid not in seen:
                        seen[mid] = cx
                    else:
                        for k, v in cx.items():
                            if k not in seen[mid] or not seen[mid][k]:
                                seen[mid][k] = v
            except Exception:
                pass

        print(f'  격자 {len(centers)}개 × 2 거래유형 순회...')
        loc_data: dict = {}

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(
                user_agent=UA, locale='ko-KR', viewport={'width': 1280, 'height': 800}
            )
            page = ctx.new_page()
            page.on('response', on_resp)

            # ── Phase 1: 매매 순회 ──────────────────────────────────
            for i, (lat, lon) in enumerate(centers):
                try:
                    page.goto(
                        f'https://new.land.naver.com/?ms={lat},{lon},15&a=APT&b=A1&e=RETAIL',
                        wait_until='networkidle', timeout=25000
                    )
                except Exception:
                    pass
                time.sleep(2.5)
                if (i + 1) % 5 == 0 or i == len(centers) - 1:
                    print(f'    매매 [{i+1}/{len(centers)}] 누적 {len(seen)}개 단지')

            # ── Phase 2: 전세 순회 ──────────────────────────────────
            pre_cnt = len(seen)
            for i, (lat, lon) in enumerate(centers):
                try:
                    page.goto(
                        f'https://new.land.naver.com/?ms={lat},{lon},15&a=APT&b=B1&e=RETAIL',
                        wait_until='networkidle', timeout=25000
                    )
                except Exception:
                    pass
                time.sleep(2.0)
            print(f'    전세 순회 완료 → 신규 {len(seen)-pre_cnt}개 단지 추가, 총 {len(seen)}개')

            # ── Phase 3: 단지별 위치 정보 (지하철·학교) ────────────
            loc_data = _fetch_location_data(seen, page)

            browser.close()

        # ── Phase 4: 개별 매물 상세 ────────────────────────────────
        print(f'  개별 매물 상세 조회 중 (매매 {MAX_ARTICLES}건 이하 단지만)...')
        articles = _fetch_articles(seen, MAX_ARTICLES)

        # ── 단지 요약 DataFrame ─────────────────────────────────────
        art_df = pd.DataFrame(articles) if articles else pd.DataFrame(
            columns=['단지코드', '거래유형', '가격(만원)'])

        def real_avg(cid, trade):
            sub = art_df[
                (art_df['단지코드'] == cid) & (art_df['거래유형'] == trade)
            ]['가격(만원)']
            return round(sub.mean()) if len(sub) > 0 else None

        def estimated_avg(mn, mx):
            a, b = _safe_int(mn), _safe_int(mx)
            if a is not None and b is not None:
                return round((a + b) / 2)
            return None

        rows = []
        for cid, cx in seen.items():
            d_cnt = cx.get('dealCount', 0) or 0
            l_cnt = cx.get('leaseCount', 0) or 0
            r_cnt = cx.get('rentCount', 0) or 0
            min_d = cx.get('minDealPrice', '')
            max_d = cx.get('maxDealPrice', '')
            min_l = cx.get('minLeasePrice', '')
            max_l = cx.get('maxLeasePrice', '')

            avg_d = real_avg(cid, '매매') or estimated_avg(min_d, max_d)
            avg_l = real_avg(cid, '전세') or estimated_avg(min_l, max_l)

            gap = gap_pct = None
            mi_d, ma_l = _safe_int(min_d), _safe_int(max_l)
            if mi_d and ma_l and mi_d > 0:
                gap     = mi_d - ma_l
                gap_pct = round(ma_l / mi_d * 100, 1)

            rows.append({
                '단지명':          cx.get('complexName', ''),
                '건축년월':        cx.get('completionYearMonth', ''),
                '총세대수':        cx.get('totalHouseholdCount', ''),
                '매매_최저(만원)': min_d or '',
                '매매_최고(만원)': max_d or '',
                '매매_평균(만원)': avg_d or '',
                '매매_매물수':     d_cnt,
                '전세_최저(만원)': min_l or '',
                '전세_최고(만원)': max_l or '',
                '전세_평균(만원)': avg_l or '',
                '전세_매물수':     l_cnt,
                '월세_매물수':     r_cnt,
                '갭_매매최저-전세최고(만원)': gap if gap is not None else '',
                '갭비율_전세/매매%': gap_pct if gap_pct is not None else '',
                '단지코드':        cid,
                '위도':            cx.get('latitude', ''),
                '경도':            cx.get('longitude', ''),
            })

        summary_df  = pd.DataFrame(rows)
        articles_df = pd.DataFrame(articles) if articles else pd.DataFrame()
        return summary_df, articles_df, loc_data
