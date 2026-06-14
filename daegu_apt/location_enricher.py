"""
위치 정보 보강 모듈

카카오 Local API로 단지 좌표 기반 지하철역·초등학교 조회.
kakao_key 미제공 시 하드코딩 대구 지하철 좌표로 도보시간 추정.
"""
import json
import math
import os
import time

import logging
from concurrent.futures import ThreadPoolExecutor

try:
    import requests as _requests
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False

_log = logging.getLogger(__name__)

# 카카오 조회 결과 캐시 (지하철·학교·마트 위치는 사실상 불변 → 재수집 시 재사용)
import sys as _sys
_CACHE_FILE = os.path.join(
    os.path.dirname(_sys.executable) if getattr(_sys, 'frozen', False)
    else os.path.dirname(os.path.abspath(__file__)),
    'location_cache.json'
)
_KAKAO_WORKERS = 5  # 병렬 호출 스레드 수

WALK_SPEED_M_PER_MIN = 67  # 도보 4km/h

KAKAO_CATEGORY_URL    = 'https://dapi.kakao.com/v2/local/search/category.json'
KAKAO_KEYWORD_URL     = 'https://dapi.kakao.com/v2/local/search/keyword.json'
KAKAO_COORD2REGION_URL = 'https://dapi.kakao.com/v2/local/geo/coord2regioncode.json'

# ── 대구 지하철 역 좌표 (1·2·3호선, 67개역) ──────────────────────
DAEGU_SUBWAY = [
    # 1호선
    ('설화명곡', 35.9064, 128.5017), ('화원',      35.8823, 128.5159),
    ('대곡',     35.8706, 128.5271), ('진천',      35.8559, 128.5389),
    ('월배',     35.8478, 128.5498), ('송현',      35.8451, 128.5609),
    ('상인',     35.8378, 128.5690), ('서부정류장', 35.8489, 128.5800),
    ('내당',     35.8618, 128.5834), ('반월당',    35.8672, 128.5968),
    ('중앙로',   35.8691, 128.5926), ('대구역',    35.8780, 128.5889),
    ('칠성시장', 35.8838, 128.5898), ('신천',      35.8754, 128.6358),
    ('동대구역', 35.8794, 128.6256), ('각산',      35.8845, 128.6356),
    ('동구청',   35.8856, 128.6402), ('아양교',    35.8913, 128.6499),
    ('동촌',     35.8988, 128.6586), ('해안',      35.9012, 128.6701),
    ('방촌',     35.9032, 128.6817), ('용계',      35.9037, 128.6940),
    ('율하',     35.9047, 128.7042), ('신기',      35.9046, 128.7139),
    ('반야월',   35.9047, 128.7241), ('대림',      35.9049, 128.7343),
    ('각북',     35.9049, 128.7456), ('임당',      35.9016, 128.7571),
    ('안심',     35.9021, 128.7668),
    # 2호선
    ('문양',     35.9003, 128.4573), ('운수',      35.8965, 128.4670),
    ('강창',     35.8946, 128.4686), ('계명대',    35.8775, 128.4836),
    ('성서공단', 35.8688, 128.4946), ('이곡',      35.8644, 128.5104),
    ('용산',     35.8649, 128.5206), ('죽전',      35.8651, 128.5305),
    ('감삼',     35.8654, 128.5444), ('두류',      35.8670, 128.5593),
    ('경대병원', 35.8696, 128.6044), ('대구은행',  35.8606, 128.6118),
    ('범어',     35.8576, 128.6226), ('수성구청',  35.8544, 128.6302),
    ('만촌',     35.8511, 128.6464), ('담티',      35.8520, 128.6588),
    ('연호',     35.8424, 128.6737), ('영남대',    35.8378, 128.7012),
    # 3호선 (모노레일)
    ('칠곡경대병원', 35.9317, 128.5684), ('구암',  35.9263, 128.5760),
    ('학정',     35.9212, 128.5829), ('팔달',      35.9073, 128.5843),
    ('공단',     35.8927, 128.5814), ('매천',      35.8851, 128.5788),
    ('매천시장', 35.8814, 128.5763), ('팔달시장',  35.8779, 128.5768),
    ('원대',     35.8724, 128.5752), ('북구청',    35.8712, 128.5762),
    ('엑스코',   35.8655, 128.5939), ('대구공항',  35.8862, 128.6622),
    ('신매',     35.8645, 128.6568), ('황금',      35.8627, 128.6477),
    ('수성시장', 35.8547, 128.6345), ('수성못',    35.8473, 128.6265),
    ('지산',     35.8413, 128.6295), ('범물',      35.8386, 128.6467),
]


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    R = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a  = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _walk_min(meters: float) -> int:
    return max(1, round(meters / WALK_SPEED_M_PER_MIN))


def _nearest_subway_hardcoded(lat: float, lon: float):
    """Returns (name+'역', dist_m, walk_min)"""
    best_name, best_dist = '', float('inf')
    for name, slat, slon in DAEGU_SUBWAY:
        d = _haversine_m(lat, lon, slat, slon)
        if d < best_dist:
            best_dist, best_name = d, name
    return best_name + '역', round(best_dist), _walk_min(best_dist)


# ── 카카오 Local API ───────────────────────────────────────────────

def _kakao_category(lat: float, lon: float, kakao_key: str,
                    category_code: str, radius: int = 2000, size: int = 5) -> list:
    try:
        r = _requests.get(
            KAKAO_CATEGORY_URL,
            headers={'Authorization': f'KakaoAK {kakao_key}'},
            params={
                'category_group_code': category_code,
                'x': lon,
                'y': lat,
                'radius': radius,
                'sort': 'distance',
                'size': size,
            },
            timeout=10,
        )
        if r.status_code == 200:
            return r.json().get('documents', [])
        _log.warning('Kakao %s HTTP %d', category_code, r.status_code)
    except Exception as e:
        _log.warning('Kakao %s error: %s', category_code, e)
    return []


def _kakao_subway(lat: float, lon: float, kakao_key: str):
    """가장 가까운 지하철역. Returns (name, walk_min) or None."""
    docs = _kakao_category(lat, lon, kakao_key, 'SW8', radius=3000)
    if docs:
        d = docs[0]
        dist = int(d.get('distance', 0))
        return d.get('place_name', ''), _walk_min(dist)
    return None


def _kakao_schools(lat: float, lon: float, kakao_key: str) -> dict:
    """SC4(학교) 한 번 호출로 가장 가까운 초·중·고를 각각 반환.
    Returns {'elem'/'mid'/'high': (name, dist_m)} (없는 종류는 키 없음).
    size=15로 받아 인근 학교를 충분히 포함 (가까운 중·고에 초등이 밀려 누락되던 문제 해결)."""
    docs = _kakao_category(lat, lon, kakao_key, 'SC4', radius=2000, size=15)
    out: dict = {}
    for d in docs:  # 거리순 정렬됨 → 종류별 첫 항목이 가장 가까움
        cat = d.get('category_name', '').split('>')[-1].strip()
        name, dist = d.get('place_name', ''), int(d.get('distance', 0))
        if '초등학교' in cat and 'elem' not in out:
            out['elem'] = (name, dist)
        elif '중학교' in cat and 'mid' not in out:
            out['mid'] = (name, dist)
        elif '고등학교' in cat and 'high' not in out:
            out['high'] = (name, dist)
    return out


def _kakao_mart(lat: float, lon: float, kakao_key: str) -> str:
    """반경 5km 내 대형마트 최대 5개. Returns '이마트(2200m/33분), 홈플러스(3100m/46분)' 형태."""
    docs = _kakao_category(lat, lon, kakao_key, 'MT1', radius=5000)
    parts = []
    for d in docs[:5]:
        name = d.get('place_name', '')
        dist = int(d.get('distance', 0))
        parts.append(f'{name}({dist}m/{_walk_min(dist)}분)')
    return ', '.join(parts)


def _kakao_keyword(lat: float, lon: float, kakao_key: str,
                   query: str, radius: int = 1000, size: int = 10) -> list:
    try:
        r = _requests.get(
            KAKAO_KEYWORD_URL,
            headers={'Authorization': f'KakaoAK {kakao_key}'},
            params={'query': query, 'x': lon, 'y': lat,
                    'radius': radius, 'sort': 'distance', 'size': size},
            timeout=10,
        )
        if r.status_code == 200:
            return r.json().get('documents', [])
        _log.warning('Kakao keyword=%s HTTP %d', query, r.status_code)
    except Exception as e:
        _log.warning('Kakao keyword=%s error: %s', query, e)
    return []


def _kakao_parks(lat: float, lon: float, kakao_key: str) -> str:
    """반경 1km 내 공원 최대 3개. Returns '어린이공원(350m/5분), 근린공원(800m/12분)' 형태."""
    docs = _kakao_keyword(lat, lon, kakao_key, '공원', radius=1000, size=15)
    parks = [
        d for d in docs
        if '공원' in d.get('place_name', '') and '골프' not in d.get('place_name', '')
    ]
    parts = []
    for d in parks[:3]:
        name = d.get('place_name', '')
        dist = int(d.get('distance', 0))
        parts.append(f'{name}({dist}m/{_walk_min(dist)}분)')
    return ', '.join(parts)


def _kakao_region(lat: float, lon: float, kakao_key: str):
    """좌표 → (구, 동). 법정동 기준. Returns (gu_str, dong_str) or ('', '')."""
    try:
        r = _requests.get(
            KAKAO_COORD2REGION_URL,
            headers={'Authorization': f'KakaoAK {kakao_key}'},
            params={'x': lon, 'y': lat},
            timeout=10,
        )
        if r.status_code == 200:
            for d in r.json().get('documents', []):
                if d.get('region_type') == 'B':  # 법정동
                    return (d.get('region_2depth_name', ''),
                            d.get('region_3depth_name', ''))
        _log.warning('Kakao coord2region HTTP %d', r.status_code)
    except Exception as e:
        _log.warning('Kakao coord2region error: %s', e)
    return '', ''


def _kakao_childcare(lat: float, lon: float, kakao_key: str) -> str:
    """반경 1km 내 어린이집·유치원 최대 5개. Returns '별빛어린이집(200m/3분), ...' 형태."""
    docs = _kakao_category(lat, lon, kakao_key, 'PS3', radius=1000)
    parts = []
    for d in docs[:5]:
        name = d.get('place_name', '')
        dist = int(d.get('distance', 0))
        parts.append(f'{name}({dist}m/{_walk_min(dist)}분)')
    return ', '.join(parts)


_EMPTY_LOC = {
    'subway_name': '', 'subway_walk': '',
    'school_name': '', 'school_dist': '',      # 초등
    'mid_name': '', 'mid_dist': '',            # 중학교
    'high_name': '', 'high_dist': '',          # 고등학교
    'mart': '', 'park': '', 'childcare': '', 'gu': '', 'dong': '',
}


def _load_loc_cache() -> dict:
    try:
        if os.path.isfile(_CACHE_FILE):
            with open(_CACHE_FILE, encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        _log.warning('location cache load error: %s', e)
    return {}


_CACHE_LOCK = __import__('threading').Lock()


def _save_loc_cache(cache: dict):
    # 동시 수집(여러 구 병렬) 시 서로의 캐시를 덮어쓰지 않도록 기존 내용과 병합 후 저장
    try:
        with _CACHE_LOCK:
            merged = _load_loc_cache()
            merged.update(cache)
            with open(_CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(merged, f, ensure_ascii=False)
    except Exception as e:
        _log.warning('location cache save error: %s', e)


def _kakao_lookup_one(lat_f: float, lon_f: float, kakao_key: str,
                      need_region: bool = True) -> dict:
    """단지 1곳의 위치 정보 조회 (카카오 API).
    need_region=False면 구·동 역지오코딩 생략 (네이버 cortarNo에서 이미 확보한 경우)."""
    rec = dict(_EMPTY_LOC)

    sub = _kakao_subway(lat_f, lon_f, kakao_key)
    if sub:
        rec['subway_name'], rec['subway_walk'] = sub[0], sub[1]
    else:
        name, _, walk = _nearest_subway_hardcoded(lat_f, lon_f)
        rec['subway_name'], rec['subway_walk'] = name, walk
    time.sleep(0.05)

    sch = _kakao_schools(lat_f, lon_f, kakao_key)
    if sch.get('elem'):
        rec['school_name'] = sch['elem'][0]
        rec['school_dist'] = f'{sch["elem"][1]}m/{_walk_min(sch["elem"][1])}분'
    if sch.get('mid'):
        rec['mid_name'] = sch['mid'][0]
        rec['mid_dist'] = f'{sch["mid"][1]}m/{_walk_min(sch["mid"][1])}분'
    if sch.get('high'):
        rec['high_name'] = sch['high'][0]
        rec['high_dist'] = f'{sch["high"][1]}m/{_walk_min(sch["high"][1])}분'
    time.sleep(0.05)

    rec['mart'] = _kakao_mart(lat_f, lon_f, kakao_key)
    time.sleep(0.05)

    rec['park'] = _kakao_parks(lat_f, lon_f, kakao_key)
    time.sleep(0.05)

    rec['childcare'] = _kakao_childcare(lat_f, lon_f, kakao_key)

    if need_region:
        time.sleep(0.05)
        rec['gu'], rec['dong'] = _kakao_region(lat_f, lon_f, kakao_key)
    return rec


def enrich_dataframe(df, naver_loc_data: dict = None, kakao_key: str = None) -> object:
    """
    df에 지하철·초등학교 컬럼 추가 후 반환.

    kakao_key 있으면 카카오 Local API 사용 (정확).
    없으면 하드코딩 지하철 좌표로 추정 (초등학교 없음).

    조회 결과는 location_cache.json에 단지코드별로 캐시되어
    재수집 시 API 호출 없이 재사용. 캐시 미스는 스레드 풀로 병렬 조회.
    """
    if df.empty:
        return df

    use_kakao = bool(kakao_key and _HAS_REQUESTS)
    # 네이버 cortarNo에서 구·동을 이미 채운 경우 카카오 역지오코딩 생략
    has_region = '지역(구)' in df.columns

    # 행별 (캐시키, 좌표) 준비 — 키는 단지코드 우선, 없으면 좌표 문자열
    # 수집 단지는 네이버 법정동(cortarNo) 기준 + 폴리곤 필터를 이미 거쳐 모두 대구 소속이므로
    # 별도 대구 좌표 범위 게이트는 두지 않음. 좌표가 없거나 파싱 불가/0,0일 때만 스킵.
    jobs = []  # (row_idx, key, lat_f|None, lon_f|None)
    for i, (_, row) in enumerate(df.iterrows()):
        lat, lon = row.get('위도', ''), row.get('경도', '')
        cid = str(row.get('단지코드', '') or '')
        try:
            lat_f, lon_f = float(lat), float(lon)
            if lat_f == 0 and lon_f == 0:
                lat_f = lon_f = None
        except (TypeError, ValueError):
            lat_f = lon_f = None
        key = cid or (f'{lat_f:.5f},{lon_f:.5f}' if lat_f is not None else '')
        jobs.append((i, key, lat_f, lon_f))

    results: dict[int, dict] = {}

    if use_kakao:
        cache = _load_loc_cache()
        misses = []
        for i, key, lat_f, lon_f in jobs:
            if lat_f is None:
                results[i] = dict(_EMPTY_LOC)
            elif key and key in cache and 'mid_name' in cache[key]:
                results[i] = {**_EMPTY_LOC, **cache[key]}
            else:
                misses.append((i, key, lat_f, lon_f))

        print(f'  위치 정보 보강 중 (카카오 API, {len(df)}개 단지 — '
              f'캐시 {len(df)-len(misses)}개, 신규 조회 {len(misses)}개)...')

        if misses:
            done_cnt = {'n': 0}

            def _work(job):
                i, key, lat_f, lon_f = job
                try:
                    rec = _kakao_lookup_one(lat_f, lon_f, kakao_key,
                                            need_region=not has_region)
                except Exception:
                    rec = dict(_EMPTY_LOC)
                done_cnt['n'] += 1
                if done_cnt['n'] % 50 == 0:
                    print(f'    [{done_cnt["n"]}/{len(misses)}] 위치 보강 진행 중...')
                return i, key, rec

            with ThreadPoolExecutor(max_workers=_KAKAO_WORKERS) as ex:
                for i, key, rec in ex.map(_work, misses):
                    results[i] = rec
                    if key and (rec['gu'] or rec['subway_name']):
                        cache[key] = rec
            _save_loc_cache(cache)
    else:
        print('  위치 정보 보강 중 (하드코딩 지하철 데이터)...')
        for i, key, lat_f, lon_f in jobs:
            rec = dict(_EMPTY_LOC)
            if lat_f is not None:
                try:
                    name, _, walk = _nearest_subway_hardcoded(lat_f, lon_f)
                    rec['subway_name'], rec['subway_walk'] = name, walk
                except Exception:
                    pass
            results[i] = rec

    ordered = [results[i] for i in range(len(jobs))]
    has_school    = any(r['school_name'] for r in ordered)
    has_mid       = any(r['mid_name'] for r in ordered)
    has_high      = any(r['high_name'] for r in ordered)
    has_park      = any(r['park'] for r in ordered)
    has_childcare = any(r['childcare'] for r in ordered)

    # 모든 거리·도보 값은 직선거리(haversine)를 도보속도(67m/분)로 나눈 추정치
    out = df.copy()
    out['근처지하철']        = [r['subway_name'] for r in ordered]
    out['지하철직선도보(분)']  = [r['subway_walk'] for r in ordered]
    if has_school:
        out['근처초등학교']         = [r['school_name'] for r in ordered]
        out['초등학교직선거리(m/분)'] = [r['school_dist'] for r in ordered]
    if has_mid:
        out['근처중학교']          = [r['mid_name'] for r in ordered]
        out['중학교직선거리(m/분)']  = [r['mid_dist'] for r in ordered]
    if has_high:
        out['근처고등학교']         = [r['high_name'] for r in ordered]
        out['고등학교직선거리(m/분)'] = [r['high_dist'] for r in ordered]
    if use_kakao:
        out['인근대형마트(5km)'] = [r['mart'] for r in ordered]
    if has_park:
        out['인근공원(1km)'] = [r['park'] for r in ordered]
    if has_childcare:
        out['인근어린이집(1km)'] = [r['childcare'] for r in ordered]

    # 지역(구)/지역(동): 네이버 cortarNo에서 이미 있으면 그대로 두고,
    # 없을 때(격자 fallback 등)만 kakao 역지오코딩 결과를 첫 두 컬럼으로 삽입
    if use_kakao and not has_region:
        out.insert(0, '지역(동)', [r['dong'] for r in ordered])
        out.insert(0, '지역(구)', [r['gu'] for r in ordered])

    return out
