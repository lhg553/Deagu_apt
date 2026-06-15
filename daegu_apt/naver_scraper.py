"""
Naver Land 호가 수집기
- 매매/전세/월세 동시 수집 (단지별 전 거래유형 통합)
- 개별 매물 가격 수집 (단지당 10건 이하만 상세 조회, rate limit 방지)
- 위치 정보(지하철·학교)는 location_enricher에서 카카오 API로 별도 수집
- 수집 결과: (summary_df, articles_df, {})
"""
import re
import math
import random
import time
import threading
from urllib.parse import urlsplit, parse_qsl, urlencode, urlunsplit

import pandas as pd
from playwright.sync_api import sync_playwright

stop_event = threading.Event()


def _rebuild_url(template_url: str, path: str = None,
                 overrides: dict = None, drop: tuple = ()) -> str:
    """캡처된 API URL 템플릿의 쿼리 파라미터를 치환해 새 URL 생성."""
    parts = urlsplit(template_url)
    q = dict(parse_qsl(parts.query, keep_blank_values=True))
    for k in drop:
        q.pop(k, None)
    if overrides:
        q.update({k: str(v) for k, v in overrides.items()})
    return urlunsplit((parts.scheme, parts.netloc, path or parts.path,
                       urlencode(q), ''))

# 구별 바운딩박스 (lat_min, lat_max, lon_min, lon_max)
# 2025 SGIS 통계청 경계 기반 + 0.005° 버퍼 (경계 단지 누락 방지)
DISTRICT_BBOX = {
    '중구':   (35.850, 35.885, 128.568, 128.620),
    '동구':   (35.845, 36.022, 128.597, 128.769),
    '서구':   (35.848, 35.903, 128.510, 128.588),
    '남구':   (35.801, 35.866, 128.549, 128.615),
    '북구':   (35.868, 35.994, 128.499, 128.639),
    '수성구': (35.784, 35.885, 128.585, 128.733),
    '달서구': (35.767, 35.876, 128.463, 128.594),
    '달성군': (35.601, 35.949, 128.345, 128.701),
    '군위군': (36.001, 36.333, 128.404, 128.906),
}

_STEP_LAT = 0.025   # all 모드 기본 스텝 (≈ 2.8km)
_STEP_LON = 0.030   # all 모드 기본 스텝 (≈ 2.7km)

# 단일 구 수집 시 구별 전용 스텝 (셀당 단지 수 과다로 인한 누락 방지)
# 중구/서구/남구는 면적이 작고 밀도 높으므로 작은 스텝 사용
_DISTRICT_STEP = {
    '중구':   (0.010, 0.012),
    '서구':   (0.012, 0.015),
    '남구':   (0.012, 0.015),
    '수성구': (0.015, 0.018),
    '달서구': (0.015, 0.018),
    '북구':   (0.015, 0.018),
    '동구':   (0.020, 0.025),
    '달성군': (0.025, 0.030),
    '군위군': (0.025, 0.030),
}


def _bbox_to_grid(lat_min, lat_max, lon_min, lon_max,
                  step_lat=None, step_lon=None) -> list:
    s_lat = step_lat or _STEP_LAT
    s_lon = step_lon or _STEP_LON
    pts = []
    lat = lat_min
    while lat <= lat_max + 0.001:
        lon = lon_min
        while lon <= lon_max + 0.001:
            pts.append((round(lat, 3), round(lon, 3)))
            lon = round(lon + s_lon, 6)
        lat = round(lat + s_lat, 6)
    return pts


_DAEGU_RANGE = (35.70, 36.05, 128.35, 128.85)  # 대구 전체 허용 bbox (fallback)

# 폴리곤 캐시 (최초 1회 로드)
_POLYGONS: dict | None = None


def _load_polygons() -> dict:
    """daegu_boundaries.json → {구이름: shapely Polygon} 캐시 반환."""
    global _POLYGONS
    if _POLYGONS is not None:
        return _POLYGONS
    import os, json
    from shapely.geometry import shape
    base = getattr(__import__('sys'), '_MEIPASS',
                   os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(base, 'daegu_boundaries.json')
    if not os.path.isfile(path):
        _POLYGONS = {}
        return _POLYGONS
    with open(path, encoding='utf-8') as f:
        raw = json.load(f)
    _POLYGONS = {name: shape(geom) for name, geom in raw.items()}
    return _POLYGONS


def _build_centers(district: str) -> list:
    if district == 'all':
        # 대구 전체를 단일 그리드로 커버 (구 경계 중복 없음)
        return _bbox_to_grid(35.745, 35.975, 128.415, 128.775)
    bbox = DISTRICT_BBOX.get(district)
    if not bbox:
        return []
    s_lat, s_lon = _DISTRICT_STEP.get(district, (_STEP_LAT, _STEP_LON))
    grid = _bbox_to_grid(*bbox, step_lat=s_lat, step_lon=s_lon)
    print(f'  [격자] {district}: {len(grid)}개 셀 (스텝 {s_lat}°×{s_lon}°)')
    return grid


def _in_bbox(cx: dict, lat_min: float, lat_max: float,
             lon_min: float, lon_max: float) -> bool:
    """bbox 범위 필터 (shapely 없을 때 fallback)."""
    try:
        lat = float(cx.get('latitude') or 0)
        lon = float(cx.get('longitude') or 0)
        if lat == 0 and lon == 0:
            return False
        return lat_min <= lat <= lat_max and lon_min <= lon <= lon_max
    except (TypeError, ValueError):
        return False


def _in_polygon(cx: dict, district: str) -> bool:
    """단지 좌표가 실제 행정구역 폴리곤 안에 있으면 True.
    경계 근처 단지의 좌표 미세 오차를 허용하기 위해 약 55m(0.0005°) 버퍼 적용.
    """
    try:
        lat = float(cx.get('latitude') or 0)
        lon = float(cx.get('longitude') or 0)
        if lat == 0 and lon == 0:
            return False
        from shapely.geometry import Point
        pt = Point(lon, lat)  # shapely는 (x=lon, y=lat) 순서
        polys = _load_polygons()
        if not polys:
            return True  # 폴리곤 파일 없으면 통과
        _BUF = 0.0005  # ≈ 55m — 경계 근처 좌표 오차 허용
        if district == 'all':
            return any(p.buffer(_BUF).contains(pt) for p in polys.values())
        poly = polys.get(district)
        return poly.buffer(_BUF).contains(pt) if poly else True
    except Exception:
        return True

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
      'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')

# networkidle 가속용: 데이터 수집과 무관한 무거운 리소스 차단
# (지도 타일 이미지가 계속 스트리밍되면 networkidle이 늦게 풀림)
_BLOCK_TYPES = {'image', 'media', 'font'}


def _install_blocker(ctx):
    """이미지·미디어·폰트 요청을 차단해 페이지의 네트워크 정착을 빠르게.
    필요한 document/script/xhr/fetch는 통과시켜 markers·articles API는 그대로 발화."""
    def _route(route):
        try:
            if route.request.resource_type in _BLOCK_TYPES:
                route.abort()
            else:
                route.continue_()
        except Exception:
            try:
                route.continue_()
            except Exception:
                pass
    ctx.route('**/*', _route)

MARKERS_URL  = 'https://new.land.naver.com/api/complexes/single-markers/2.0'

# cortarNo 캐시
_CORTARS: dict | None = None


def _load_cortars(district: str) -> list:
    """daegu_cortars.json → [(cortarNo, lat, lon, name)] 목록 반환.
    파일 없으면 빈 리스트 (grid 방식 fallback).
    """
    global _CORTARS
    if _CORTARS is None:
        import os, json
        base = getattr(__import__('sys'), '_MEIPASS',
                       os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(base, 'daegu_cortars.json')
        if not os.path.isfile(path):
            _CORTARS = {}
        else:
            with open(path, encoding='utf-8') as f:
                _CORTARS = json.load(f)

    if district == 'all':
        items = [x for v in _CORTARS.values() for x in v]
    else:
        items = _CORTARS.get(district, [])

    return [(x['cortarNo'], float(x['centerLat']), float(x['centerLon']), x['name'])
            for x in items if x.get('centerLat') and x.get('centerLon')]
ARTICLES_URL = 'https://new.land.naver.com/api/articles/complex/{}'
COMPLEX_URL  = 'https://new.land.naver.com/api/complexes/{}?sameAddressGroup=false'

TRADE_LABEL  = {'A1': '매매', 'B1': '전세', 'B2': '월세'}


def _safe_int(v):
    try:
        return int(str(v).replace(',', '').strip())
    except Exception:
        return None


def _exclu_rate(area1_str, area2_str) -> str:
    try:
        a1 = float(str(area1_str).replace(',', '').strip())
        a2 = float(str(area2_str).replace(',', '').strip())
        if a1 > 0 and a2 > 0:
            return str(round(a2 / a1 * 100, 1))
    except Exception:
        pass
    return ''


def _to_pyeong(area_m2) -> str:
    try:
        v = float(str(area_m2).replace(',', '').strip())
        return str(round(v / 3.3)) if v > 0 else ''
    except Exception:
        return ''


def _normalize_areas(area1_str, area2_str):
    """
    공급(area1)·전용(area2) 값을 받아 둘 다 ㎡ 단위 float으로 반환.
    일부 단지는 area2가 이미 평 단위로 내려오는 경우가 있어
    area1/area2 비율로 감지: 비율 ≈ 3.3이면 area2가 평 단위.
    (정상 전용률 60~90% → 비율 1.1~1.7 / 평 혼입 시 비율 2.5~4.5)
    Returns: (공급㎡_or_None, 전용㎡_or_None)
    """
    def _f(s):
        try:
            return float(str(s).replace(',', '').strip()) if s else 0.0
        except Exception:
            return 0.0

    a1 = _f(area1_str)
    a2 = _f(area2_str)

    if a1 > 0 and a2 > 0:
        ratio = a1 / a2
        if 2.5 <= ratio <= 4.5:
            # area2가 이미 평 단위 → ㎡로 환산
            a2 = round(a2 * 3.3, 2)
        elif 0.22 <= ratio <= 0.4:
            # area1이 이미 평 단위 → ㎡로 환산
            a1 = round(a1 * 3.3, 2)

    return (a1 if a1 > 0 else None,
            a2 if a2 > 0 else None)


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



def _fetch_articles(seen: dict) -> list:
    """
    매매 매물이 있는 모든 단지의 매물 상세를 수집.

    각 단지 페이지를 방문해 articles API 응답을 on_resp로 캡처.
    이미지·타일을 차단해 networkidle이 빠르게 풀리도록 해 단지당 대기 시간을 단축.
    1페이지(약 20건)는 페이지 방문으로 캡처하고, 추가 페이지는
    세션이 따뜻한 상태에서 직접 API 호출(ctx.request.get)로 가져온다.
    (단지 미방문 상태의 직접 호출은 Naver가 429/401로 차단하므로 사용하지 않음)

    전세 매물도 있는 단지는 tradeType=B1 페이지를 추가 방문해 전세 매물도 수집.
    """
    targets = [
        (cid, cx) for cid, cx in seen.items()
        if (cx.get('dealCount', 0) or 0) > 0
    ]
    lease_targets = {
        cid for cid, cx in targets
        if (cx.get('leaseCount', 0) or 0) > 0
    }
    if not targets:
        print('    조회 대상 없음')
        return []

    print(f'    대상: {len(targets)}개 단지 (전세 추가수집: {len(lease_targets)}개)')

    current = {'cid': None}
    buf: dict = {}
    url_cache: dict = {}   # cid → 캡처된 article API URL (페이지네이션 템플릿)
    api_headers = {}       # SPA가 보낸 article API 요청 헤더 (authorization 등) 재사용
    pg_rl = {'disabled': False, 'fail_streak': 0}  # 페이지네이션 rate limit 상태
    PAGE_SIZE = 20

    def on_req(req):
        # SPA가 보내는 article API 요청의 헤더(authorization 포함)를 캡처해 직접 호출에 재사용
        if 'articles/complex/' in req.url and not api_headers:
            try:
                h = req.headers
                for k in ('authorization', 'referer', 'accept', 'accept-language',
                          'sec-fetch-site', 'sec-fetch-mode', 'sec-fetch-dest'):
                    if h.get(k):
                        api_headers[k] = h[k]
            except Exception:
                pass

    def on_resp(resp):
        cid = current['cid']
        if not cid:
            return
        url = resp.url
        if f'articles/complex/{cid}' not in url and f'articleList?hscpNo={cid}' not in url:
            return
        if resp.status != 200:
            return
        if cid not in url_cache and f'articles/complex/{cid}' in url:
            url_cache[cid] = url
        try:
            data = resp.json()
            items = data if isinstance(data, list) else data.get('articleList', [])
            buf.setdefault(cid, []).extend(items)
        except Exception:
            pass

    def _article_url(cid, trade, page_num):
        base = url_cache[cid]
        return _rebuild_url(base, overrides={
            'tradeType': trade, 'page': page_num,
        })

    _JS_FETCH = """async ([url, headers]) => {
        try {
            const r = await fetch(url, {headers, credentials: 'include'});
            if (!r.ok) return {status: r.status};
            const j = await r.json();
            return {status: 200, data: j};
        } catch (e) { return {status: -1, error: String(e)}; }
    }"""

    def _fetch_pages(page, cid, trade, start_page=2):
        """단지 페이지 안 fetch(page.evaluate)로 거래유형별 매물을 수집.
        SPA와 동일한 네트워크 스택을 사용해 429/401 차단 회피.
        - start_page=2: A1 1페이지는 방문으로 캡처했으니 2페이지부터 (매매 추가분).
        - start_page=1: 방문 없이 전체 수집 (전세 등 — 별도 방문 생략).
        429가 반복되면 비활성화하고 수집된 것만 유지."""
        if cid not in url_cache or pg_rl['disabled']:
            return
        page_num = start_page
        while page_num <= 30:
            url = _article_url(cid, trade, page_num)
            retry_429 = 0
            res = None
            while True:
                try:
                    res = page.evaluate(_JS_FETCH, [url, api_headers or {}])
                except Exception:
                    return
                if not res or res.get('status') != 429:
                    break
                retry_429 += 1
                if retry_429 > 2:
                    pg_rl['fail_streak'] += 1
                    if pg_rl['fail_streak'] >= 5 and not pg_rl['disabled']:
                        pg_rl['disabled'] = True
                        print('    [경고] 페이지네이션 429 반복 — rate limit 의심, '
                              '추가 페이지 수집 중단(1페이지만 유지). 잠시 후 재시도 권장.')
                    return
                wait = 15 * retry_429
                print(f'    [대기] 페이지네이션 429 — {wait}초 후 재시도 ({retry_429}/2)...')
                time.sleep(wait)
            if not res or res.get('status') != 200:
                return
            data = res.get('data')
            items = data if isinstance(data, list) else (data.get('articleList') or [])
            more = data.get('isMoreData') if isinstance(data, dict) else None
            if items:
                buf.setdefault(cid, []).extend(items)
            pg_rl['fail_streak'] = 0
            if not items or more is False or len(items) < PAGE_SIZE:
                return
            page_num += 1
            time.sleep(random.uniform(0.15, 0.3))

    def _visit(page, cid, trade, settle=0.3):
        """단지 페이지 방문 — articles 응답을 on_resp로 캡처.
        이미지·타일 차단으로 networkidle이 빠르게 풀려 대기 시간 단축."""
        url = f'https://new.land.naver.com/complexes/{cid}?a=APT&b={trade}'
        try:
            page.goto(url, wait_until='networkidle', timeout=20000)
        except Exception:
            pass
        time.sleep(settle)

    fetched = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=UA, locale='ko-KR', viewport={'width': 1280, 'height': 800}
        )
        _install_blocker(ctx)
        page = ctx.new_page()
        page.on('request', on_req)
        page.on('response', on_resp)

        for i, (cid, cx) in enumerate(targets):
            if stop_event.is_set():
                print('  [중지] 수집 중단')
                break
            current['cid'] = cid
            n0 = len(buf.get(cid, []))
            _visit(page, cid, 'A1')  # 매매 1페이지 캡처 + 세션 워밍 + URL/헤더 캡처
            # 매매 1페이지가 꽉 찼을 때만(=2페이지 존재 가능) 추가 페이지 수집
            if len(buf.get(cid, [])) - n0 >= PAGE_SIZE:
                _fetch_pages(page, cid, 'A1', start_page=2)
            if cid in buf:
                fetched += 1

            # 전세: 별도 페이지 방문 없이 따뜻한 세션에서 evaluate fetch로 전체 수집
            if cid in lease_targets:
                _fetch_pages(page, cid, 'B1', start_page=1)

            time.sleep(random.uniform(0.2, 0.4))  # 단지 간 페이싱 (rate limit 완화)

            if (i + 1) % 10 == 0 or i == len(targets) - 1:
                print(f'    [{i+1}/{len(targets)}] 캡처 성공: {fetched}개')

        browser.close()

    articles = []
    for cid, items in buf.items():
        cx = seen.get(cid, {})
        for art in items:
            prc = _parse_price(art.get('dealOrWarrantPrc', ''))
            if prc:
                a1_m2, a2_m2 = _normalize_areas(art.get('area1', ''), art.get('area2', ''))
                articles.append({
                    '단지명':    cx.get('complexName', ''),
                    '단지코드':  cid,
                    '거래유형':  art.get('tradeTypeName', '매매'),
                    '가격(만원)': prc,
                    '공급평형':   _to_pyeong(a1_m2 or a2_m2),
                    '전용평형':   _to_pyeong(a2_m2),
                    '전용률(%)':  _exclu_rate(a1_m2, a2_m2),
                    '공급면적㎡': round(a1_m2, 2) if a1_m2 else '',
                    '전용면적㎡': round(a2_m2, 2) if a2_m2 else '',
                    '층':        art.get('floorInfo', ''),
                    '방향':      art.get('direction', ''),
                    '등록일':    art.get('articleConfirmYmd', ''),
                    '매물번호':  art.get('articleNo', ''),
                    '동일매물수':        art.get('sameAddrCnt') or 1,
                    '동일_최저가(만원)': _parse_price(art.get('sameAddrMinPrc', '')) or '',
                    '동일_최고가(만원)': _parse_price(art.get('sameAddrMaxPrc', '')) or '',
                    '중개사명(참고)':       art.get('realtorName', ''),
                    '중개사_코멘트(참고)':  art.get('articleFeatureDesc', ''),
                    '태그(참고)':          ', '.join(art.get('tagList') or []),
                })

    return articles


class NaverLandScraper:
    def collect(self, district: str = 'all', test_limit: int = 0) -> tuple:
        """
        Returns
        -------
        summary_df  : 단지 수준 요약 (매매/전세/월세 최저·최고·평균·매물수)
        articles_df : 개별 매물 상세 (단지명, 거래유형, 가격, 면적, 층, ...)
        loc_data    : dict[cid → {subway_name, subway_walk, school_name, school_dist}]

        test_limit  : 0이면 전체, N이면 매물 많은 순 N개 단지만 수집 (빠른 테스트용)
        """
        # cortarNo 기반 수집 (daegu_cortars.json 있으면) / grid fallback
        cortars = _load_cortars(district)
        if cortars:
            use_cortar = True
            scan_items = cortars  # [(cno, lat, lon, name)]
            print(f'  cortarNo 기반 수집: {len(scan_items)}개 동')
        else:
            use_cortar = False
            centers = _build_centers(district)
            if not centers:
                print(f'  [경고] 알 수 없는 지역: {district}')
                return pd.DataFrame(), pd.DataFrame(), {}
            scan_items = [(None, lat, lon, '') for lat, lon in centers]
            print(f'  격자 {len(centers)}개 순회 (cortarNo 파일 없음 — fallback)')

        seen: dict = {}
        phase  = {'v': '', 'url_logged': False}
        rl     = {'limited': False, 'empty_streak': 0, 'retry_count': 0, 'needs_sleep': False, 'total_sleeps': 0}

        def _merge_items(items):
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

        # ── regions/complexes 응답(동 단위 전체 단지)을 seen에 병합 ──
        # gu/dong은 조회 중인 법정동 cortarNo에서 직접 채움 (Kakao 역지오코딩 불필요)
        def _add_complex(c, gu='', dong=''):
            cid = str(c.get('complexNo') or '')
            if not cid:
                return
            ymd = str(c.get('useApproveYmd') or '')
            rec = {
                'complexName':         c.get('complexName', ''),
                'completionYearMonth': ymd[:6] if len(ymd) >= 6 else ymd,
                'totalHouseholdCount': c.get('totalHouseholdCount', ''),
                'dealCount':           c.get('dealCount', 0) or 0,
                'leaseCount':          c.get('leaseCount', 0) or 0,
                'rentCount':           c.get('rentCount', 0) or 0,
                'latitude':            c.get('latitude', ''),
                'longitude':           c.get('longitude', ''),
                'markerId':            cid,
                '지역(구)':             gu,
                '지역(동)':             dong,
            }
            if cid not in seen:
                seen[cid] = rec
            else:
                for k, v in rec.items():
                    if v and not seen[cid].get(k):
                        seen[cid][k] = v

        def on_resp(resp):
            # 429 → 즉시 rate-limit 플래그
            if resp.status == 429 and 'land.naver.com' in resp.url:
                rl['limited'] = True
                print(f'  [오류] Rate limit (429) 감지: {resp.url[:80]}')
                return

            if 'single-markers' not in resp.url:
                return
            if resp.status != 200:
                return

            if not phase['url_logged']:
                def _area_val(key):
                    for p in resp.url.split('&'):
                        if p.lower().startswith(key + '='):
                            try:
                                return int(p.split('=', 1)[1])
                            except ValueError:
                                pass
                    return None
                a_min = _area_val('areamin')
                a_max = _area_val('areamax')
                if (a_min is not None and a_min > 0) or (a_max is not None and a_max < 500):
                    print(f'  [주의] markers 면적 필터 감지 - areaMin={a_min} areaMax={a_max} -> 일부 평형 누락 가능')
                else:
                    print(f'  [확인] 면적 필터 없음 (areaMin={a_min}, areaMax={a_max}) - 전체 평형 수집 중')
                phase['url_logged'] = True

            for part in resp.url.split('&'):
                if part.startswith('tradeType='):
                    phase['v'] = part.split('=')[1]
                    break
            try:
                items = resp.json()
                if not isinstance(items, list):
                    rl['empty_streak'] += 1
                else:
                    if len(items) == 0:
                        rl['empty_streak'] += 1
                    else:
                        rl['empty_streak'] = 0
                        if rl['retry_count'] > 0:
                            rl['retry_count'] = 0
                    # 연속 빈 응답 10회 = rate limit / 차단 의심
                    if rl['empty_streak'] >= 10 and not rl['needs_sleep']:
                        rl['needs_sleep'] = True
                        print(f'  [경고] 연속 {rl["empty_streak"]}회 빈 마커 응답 — rate limit 의심')
                    _merge_items(items)
            except Exception:
                pass

        if use_cortar:
            # ── regions/complexes: 동(cortarNo) 단위 전체 단지 목록 수집 ──
            # 뷰포트 한계가 없어 매물 없는 단지·화면 밖 단지까지 빠짐없이 수집.
            cno_map: dict = {}  # cortarNo → (lat, lon, 동이름)
            for cno, lat, lon, name in cortars:
                if cno and cno not in cno_map:
                    cno_map[cno] = (lat, lon, name)
            cnos = list(cno_map.items())
            # cortarNo → 구 매핑 (district != 'all'이면 전부 그 구)
            if district == 'all' and _CORTARS:
                gu_of = {x['cortarNo']: gu for gu, items in _CORTARS.items() for x in items}
            else:
                gu_of = {cno: district for cno in cno_map}
            print(f'  regions/complexes 단지 목록 수집: {len(cnos)}개 동')

            REGIONS_JS = """async ([cno, headers]) => {
                const url = `https://new.land.naver.com/api/regions/complexes`
                          + `?cortarNo=${cno}&realEstateType=APT&order=`;
                try {
                    const r = await fetch(url, {headers, credentials:'include'});
                    if (!r.ok) return {status: r.status};
                    const j = await r.json();
                    return {status: 200, list: j.complexList || []};
                } catch (e) { return {status: -1, error: String(e)}; }
            }"""

            api_headers: dict = {}

            def _cap_auth(req):
                if 'new.land.naver.com/api/' in req.url and 'authorization' not in api_headers:
                    try:
                        h = req.headers
                        if h.get('authorization'):
                            for k in ('authorization', 'accept', 'accept-language'):
                                if h.get(k):
                                    api_headers[k] = h[k]
                    except Exception:
                        pass

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                ctx = browser.new_context(
                    user_agent=UA, locale='ko-KR', viewport={'width': 1280, 'height': 800}
                )
                _install_blocker(ctx)
                page = ctx.new_page()
                page.on('request', _cap_auth)

                # 워밍업: auth 헤더 확보 (아무 동 한 곳 방문)
                w_lat, w_lon = cnos[0][1][0], cnos[0][1][1]
                try:
                    page.goto(f'https://new.land.naver.com/complexes?ms={w_lat},{w_lon},15&a=APT&b=A1&e=RETAIL',
                              wait_until='networkidle', timeout=25000)
                except Exception:
                    pass
                time.sleep(0.5)

                for i, (cno, (lat, lon, dong)) in enumerate(cnos):
                    gu = gu_of.get(cno, district if district != 'all' else '')
                    res = None
                    for attempt in range(3):
                        try:
                            res = page.evaluate(REGIONS_JS, [cno, api_headers or {}])
                        except Exception:
                            res = None
                        if res and res.get('status') == 429:
                            print('    [대기] regions 429 — 60초 후 재시도...')
                            time.sleep(60)
                            continue
                        break
                    if res and res.get('status') == 200:
                        for c in res.get('list') or []:
                            _add_complex(c, gu, dong)
                    if (i + 1) % 10 == 0 or i == len(cnos) - 1:
                        print(f'    [{i+1}/{len(cnos)}] 누적 {len(seen)}개 단지')
                    time.sleep(random.uniform(0.1, 0.2))

                browser.close()
        else:
            # ── fallback: cortars 파일 없을 때 기존 bbox 격자 single-markers ──
            n_items = len(scan_items)
            print(f'  격자 {n_items}개 × 2 거래유형 순회 (fallback)...')

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                ctx = browser.new_context(
                    user_agent=UA, locale='ko-KR', viewport={'width': 1280, 'height': 800}
                )
                _install_blocker(ctx)
                page = ctx.new_page()
                page.on('response', on_resp)

                def _rl_check_and_wait(phase_name, i):
                    if rl['limited']:
                        print(f'  [중단] Rate limit — {phase_name} 격자 {i}/{n_items}')
                        return True
                    if rl['needs_sleep']:
                        if rl['total_sleeps'] < 8:
                            wait = 90 + rl['retry_count'] * 60
                            print(f'  [대기] Rate limit — {wait}초 후 재시도 (누적 {rl["total_sleeps"]+1}/8)...')
                            time.sleep(wait)
                            rl['empty_streak'] = 0
                            rl['needs_sleep'] = False
                            rl['retry_count'] += 1
                            rl['total_sleeps'] += 1
                        else:
                            rl['limited'] = True
                            return True
                    return False

                def _nav_url(cno, lat, lon, trade):
                    return f'https://new.land.naver.com/?ms={lat},{lon},15&a=APT&b={trade}&e=RETAIL'

                def _scan_phase(label, trade, settle_sleep):
                    for i, (cno, lat, lon, name) in enumerate(scan_items):
                        if _rl_check_and_wait(label, i):
                            return
                        rl['empty_streak'] = 0
                        try:
                            page.goto(_nav_url(cno, lat, lon, trade),
                                      wait_until='networkidle', timeout=25000)
                        except Exception:
                            pass
                        time.sleep(settle_sleep)
                        if label == '매매' and ((i + 1) % 5 == 0 or i == n_items - 1):
                            print(f'    매매 [{i+1}/{n_items}] 누적 {len(seen)}개 단지')

                _scan_phase('매매', 'A1', 0.4)
                rl['empty_streak'] = 0
                rl['needs_sleep'] = False
                rl['retry_count'] = 0
                if not rl['limited']:
                    _scan_phase('전세', 'B1', 0.4)
                browser.close()

        # ── 좌표 범위 필터 ──────────────────────────────────────────
        # 폴리곤 데이터 있으면 실제 행정구역 경계로, 없으면 bbox fallback
        before = len(seen)
        if _load_polygons():
            seen = {cid: cx for cid, cx in seen.items()
                    if _in_polygon(cx, district)}
        else:
            if district != 'all':
                bbox = DISTRICT_BBOX.get(district)
                if bbox:
                    lat_min, lat_max, lon_min, lon_max = bbox
                    buf = 0.012
                    flt = (lat_min - buf, lat_max + buf, lon_min - buf, lon_max + buf)
                else:
                    flt = _DAEGU_RANGE
            else:
                flt = _DAEGU_RANGE
            seen = {cid: cx for cid, cx in seen.items() if _in_bbox(cx, *flt)}

        removed = before - len(seen)
        if removed:
            tag = district if district != 'all' else '대구 전체'
            print(f'  [필터] {tag} 경계 외 {removed}개 단지 제거')

        # TEST 모드: dealCount 상위 N개로 제한
        if test_limit and len(seen) > test_limit:
            sorted_cids = sorted(seen, key=lambda c: seen[c].get('dealCount', 0) or 0, reverse=True)
            seen = {cid: seen[cid] for cid in sorted_cids[:test_limit]}
            print(f'  [TEST] {test_limit}개 단지로 제한')

        # ── Phase 3: 개별 매물 상세 ────────────────────────────────
        print(f'  개별 매물 상세 조회 중 (매매 매물 있는 전체 단지)...')
        articles = _fetch_articles(seen)

        # ── 단지 요약 DataFrame ─────────────────────────────────────
        art_df = pd.DataFrame(articles) if articles else pd.DataFrame(
            columns=['단지코드', '거래유형', '가격(만원)'])

        # 동일매물(여러 중개사 동일 물건) 중복 제거: 통계 계산용
        # 가격·층·방향이 같으면 같은 물건으로 간주, 대표 1건만 유지
        if not art_df.empty:
            _dedup_keys = ['단지코드', '거래유형', '가격(만원)', '층', '방향']
            art_stats = art_df.drop_duplicates(subset=_dedup_keys, keep='first')
        else:
            art_stats = art_df

        def pyeong_list(cid):
            if art_df.empty or '전용평형' not in art_df.columns:
                return ''
            sub = art_df[art_df['단지코드'] == cid]['전용평형']
            unique = sorted({p for p in sub if p}, key=lambda x: int(x) if x.isdigit() else 0)
            return '/'.join(unique)

        def real_avg(cid, trade):
            sub = art_stats[
                (art_stats['단지코드'] == cid) & (art_stats['거래유형'] == trade)
            ]['가격(만원)']
            return round(sub.mean()) if len(sub) > 0 else None

        def estimated_avg(mn, mx):
            a, b = _safe_int(mn), _safe_int(mx)
            if a is not None and b is not None:
                return round((a + b) / 2)
            return None

        def didimdol_count(cid):
            """5억 이하 + 전용 85㎡ 이하 매매 매물 수 (호가 기준 참고용)."""
            if art_stats.empty or '가격(만원)' not in art_stats.columns:
                return ''
            sub = art_stats[(art_stats['단지코드'] == cid) & (art_stats['거래유형'] == '매매') &
                            (art_stats['가격(만원)'] <= 50000)]
            if '전용면적㎡' in sub.columns:
                sub = sub[pd.to_numeric(sub['전용면적㎡'], errors='coerce').fillna(999) <= 85]
            return len(sub) if len(sub) > 0 else ''

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
                '지역(구)':        cx.get('지역(구)', ''),
                '지역(동)':        cx.get('지역(동)', ''),
                '단지명':          cx.get('complexName', ''),
                '건축년월':        cx.get('completionYearMonth', ''),
                '총세대수':        cx.get('totalHouseholdCount', ''),
                '5억이하매물수(호가)':   didimdol_count(cid),
                '매매_최저(만원)': min_d or '',
                '매매_최고(만원)': max_d or '',
                '매매_평균(만원)': avg_d or '',
                '매매_매물수':     d_cnt,
                '전세_최저(만원)': min_l or '',
                '전세_최고(만원)': max_l or '',
                '전세_평균(만원)': avg_l or '',
                '전세_매물수':     l_cnt,
                '월세_매물수':     r_cnt,
                '단지코드':        cid,
                '위도':            cx.get('latitude', ''),
                '경도':            cx.get('longitude', ''),
            })

        summary_df  = pd.DataFrame(rows)
        # 매물상세: 동일 물건(가격·층·방향 같은 중복 중개사 매물) 제거 후 출력
        articles_df = art_stats.reset_index(drop=True) if not art_stats.empty else pd.DataFrame()
        return summary_df, articles_df, {'rate_limited': rl['limited']}
