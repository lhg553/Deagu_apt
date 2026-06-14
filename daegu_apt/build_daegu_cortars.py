# -*- coding: utf-8 -*-
"""
대구 8개 구 전체 동(cortarNo) 자동 수집 → daegu_cortars.json 저장.

동작:
  - 구별 bbox 격자를 순회하면서 페이지 navigation으로 발생하는
    api/cortars 응답을 인터셉트 → 각 격자 포인트에 해당하는 cortarNo 수집
  - 같은 cortarNo에 속하는 격자 포인트들을 zoom-15 뷰포트 크기로 클러스터링
    → 법정동 하나가 여러 행정동에 걸쳐 넓은 경우에도 완전 커버
  - 출력: daegu_cortars.json
    {
      "수성구": [
        {"cortarNo":"2726010100","name":"범어동","centerLat":35.856,"centerLon":128.622},
        ...  # 동일 cortarNo가 여러 항목일 수 있음 (넓은 동 → 여러 커버리지 포인트)
      ],
      ...
    }

배경:
  법정동(cortarNo 단위)과 행정동은 1:N 관계임.
  예) 봉덕동(법정동) = 봉덕1동(0.49㎢) + 봉덕2동(3.06㎢) + 봉덕3동(2.69㎢)
  Naver api/cortars가 반환하는 centroid는 법정동의 임의 대표점이어서
  zoom-15 뷰포트 하나로는 넓은 동 전체를 커버하지 못함.
  → 격자 포인트 자체를 cortarNo별로 수집 후 클러스터링으로 다중 커버리지 포인트 생성.
"""
import json
import os
import sys
import time
from playwright.sync_api import sync_playwright

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
      'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')

DISTRICT_BBOX = {
    '중구':   (35.850, 35.885, 128.568, 128.620),
    '동구':   (35.845, 36.022, 128.597, 128.769),
    '서구':   (35.848, 35.903, 128.510, 128.590),
    '남구':   (35.801, 35.870, 128.549, 128.630),
    '북구':   (35.868, 35.994, 128.499, 128.639),
    '수성구': (35.784, 35.885, 128.585, 128.733),
    '달서구': (35.767, 35.876, 128.463, 128.594),
    '달성군': (35.601, 35.949, 128.345, 128.701),
}

# cortarNo discovery 용 스텝
DISC_STEP = {
    '중구':   (0.008, 0.010),
    '동구':   (0.018, 0.022),
    '서구':   (0.010, 0.013),
    '남구':   (0.008, 0.010),
    '북구':   (0.013, 0.016),
    '수성구': (0.013, 0.016),
    '달서구': (0.013, 0.016),
    '달성군': (0.022, 0.027),
}

# 구별 대표 cortarNo 접두사 (intra-구 필터용)
DIVISION_NO = {
    '중구':   '2711',
    '동구':   '2714',
    '서구':   '2717',
    '남구':   '2720',
    '북구':   '2723',
    '수성구': '2726',
    '달서구': '2729',
    '달성군': '2771',
}

# zoom-15 뷰포트 절반 크기 (클러스터 셀 크기)
# 이 크기로 격자 포인트를 묶으면 셀 평균 좌표에서 zoom-15로 열었을 때 셀 전체가 커버됨
CLUSTER_DLAT = 0.007  # ~780m
CLUSTER_DLON = 0.010  # ~900m


def bbox_to_grid(lat_min, lat_max, lon_min, lon_max, s_lat, s_lon):
    pts = []
    lat = lat_min
    while lat <= lat_max + 0.001:
        lon = lon_min
        while lon <= lon_max + 0.001:
            pts.append((round(lat, 3), round(lon, 3)))
            lon = round(lon + s_lon, 6)
        lat = round(lat + s_lat, 6)
    return pts


def cluster_points(points):
    """
    격자 포인트들을 CLUSTER_DLAT × CLUSTER_DLON 셀로 클러스터링.
    각 셀의 평균 좌표를 반환 — zoom-15 뷰포트에서 셀 내 모든 포인트를 커버.
    """
    if not points:
        return []
    lat_min = min(p[0] for p in points)
    lon_min = min(p[1] for p in points)
    cells: dict = {}
    for lat, lon in points:
        ci = int((lat - lat_min) / CLUSTER_DLAT)
        cj = int((lon - lon_min) / CLUSTER_DLON)
        cells.setdefault((ci, cj), []).append((lat, lon))
    return [
        (round(sum(p[0] for p in pts) / len(pts), 6),
         round(sum(p[1] for p in pts) / len(pts), 6))
        for pts in cells.values()
    ]


def collect_cortarnos_for_district(page, district: str) -> dict:
    """
    구 격자를 순회해서 cortarNo 수집.
    반환: {cortarNo: {'name': str, 'points': [(lat, lon), ...]}}
    points = 해당 cortarNo 반환한 격자 포인트들 (클러스터링 입력용)
    """
    bbox = DISTRICT_BBOX[district]
    step = DISC_STEP[district]
    centers = bbox_to_grid(*bbox, *step)
    div_prefix = DIVISION_NO[district]
    collected: dict[str, dict] = {}

    # 현재 격자 포인트에서 인터셉트된 cortarNo를 기록하는 공유 변수
    last_hit: list = [None, '']  # [cortarNo, name]

    def on_resp(resp):
        if '/api/cortars' not in resp.url or resp.status != 200:
            return
        try:
            d = resp.json()
        except Exception:
            return
        cno = d.get('cortarNo') or d.get('sectorNo')
        cname = d.get('cortarName') or d.get('sectorName') or ''
        if cno and cno.startswith(div_prefix):
            last_hit[0] = cno
            last_hit[1] = cname

    page.on('response', on_resp)

    print(f'  [{district}] 격자 {len(centers)}개 순회...')
    n_pts = 0
    for i, (lat, lon) in enumerate(centers):
        last_hit[0] = None
        last_hit[1] = ''
        try:
            page.goto(
                f'https://new.land.naver.com/?ms={lat},{lon},15&a=APT&b=A1&e=RETAIL',
                wait_until='networkidle', timeout=20000
            )
        except Exception:
            pass
        time.sleep(1.0)
        if last_hit[0]:
            cno = last_hit[0]
            if cno not in collected:
                collected[cno] = {'name': last_hit[1], 'points': []}
            elif not collected[cno]['name'] and last_hit[1]:
                collected[cno]['name'] = last_hit[1]
            collected[cno]['points'].append((lat, lon))
            n_pts += 1
        if (i + 1) % 15 == 0:
            print(f'    [{i+1}/{len(centers)}] {district} cortarNo: {len(collected)}개 ({n_pts}개 포인트)')

    page.remove_listener('response', on_resp)
    return collected


def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    out_path = os.path.join(base_dir, 'daegu_cortars.json')

    # 기존 파일 로드 (이어 작업)
    if os.path.isfile(out_path):
        with open(out_path, encoding='utf-8') as f:
            result = json.load(f)
        total_entries = sum(len(v) for v in result.values())
        print(f'기존 daegu_cortars.json 로드: {total_entries}개 항목')
    else:
        result = {}

    force = '--force' in sys.argv
    named = [a for a in sys.argv[1:] if not a.startswith('-')]

    districts = list(DISTRICT_BBOX.keys())
    if named:
        districts = [d for d in named if d in DISTRICT_BBOX]
        if not districts:
            print(f'알 수 없는 구: {named}')
            return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=UA, locale='ko-KR', viewport={'width': 1280, 'height': 800}
        )
        page = ctx.new_page()

        print('[워밍업] 메인 페이지 방문...')
        try:
            page.goto(
                'https://new.land.naver.com/?ms=35.858,128.627,15&a=APT&b=A1&e=RETAIL',
                wait_until='networkidle', timeout=30000
            )
        except Exception:
            pass
        time.sleep(2)

        for district in districts:
            if district in result and len(result[district]) > 0:
                print(f'[{district}] 이미 수집됨 ({len(result[district])}개 항목) — 스킵'
                      f'  (재수집: python build_daegu_cortars.py --force {district})')
                if not force:
                    continue

            print(f'\n[{district}] cortarNo 수집 시작...')
            collected = collect_cortarnos_for_district(page, district)

            # 클러스터링: cortarNo별 격자 포인트 → 다중 커버리지 포인트
            entries = []
            for cno, info in sorted(collected.items()):
                coverage = cluster_points(info['points'])
                for clat, clon in coverage:
                    entries.append({
                        'cortarNo': cno,
                        'name': info['name'],
                        'centerLat': clat,
                        'centerLon': clon,
                    })

            result[district] = entries
            n_cno = len(set(e['cortarNo'] for e in entries))
            print(f'  → {district}: {n_cno}개 동, {len(entries)}개 커버리지 포인트')
            for cno, info in sorted(collected.items()):
                pts = cluster_points(info['points'])
                print(f'     {cno} {info["name"]:12s}  격자{len(info["points"])}개 → {len(pts)}개 포인트')

            with open(out_path, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            print(f'  daegu_cortars.json 저장 완료')
            time.sleep(1)

        browser.close()

    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    total_entries = sum(len(v) for v in result.values())
    total_cno = sum(len(set(e['cortarNo'] for e in v)) for v in result.values())
    print(f'\n완료: {total_cno}개 동, {total_entries}개 커버리지 포인트 → {out_path}')
    for gu, items in result.items():
        n = len(set(e['cortarNo'] for e in items))
        print(f'  {gu}: {n}개 동, {len(items)}개 포인트')


if __name__ == '__main__':
    main()
