# -*- coding: utf-8 -*-
"""
페이지 navigation 시 자연 발생하는 api/cortars 응답을 캡처해서
cortarNo 구조 확인 + 수성구 전체 동 cortarNo 수집.
직접 API 호출 X — 모두 on_resp 인터셉트.
"""
import json
import time
from playwright.sync_api import sync_playwright

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
      'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')

# 수성구 격자 중심점 (0.015°×0.018° 스텝 — CLAUDE.md 기준)
from itertools import product
SUSEONG_BBOX = (35.784, 35.885, 128.585, 128.733)
S_LAT, S_LON = 0.015, 0.018


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


def main():
    centers = bbox_to_grid(*SUSEONG_BBOX, S_LAT, S_LON)
    print(f'격자 포인트: {len(centers)}개')

    cortars = {}        # cortarNo → {name, centerLat, centerLon, divisionName}
    first_full = None   # 첫 번째 api/cortars 응답 전체 (구조 확인용)

    def on_resp(resp):
        nonlocal first_full
        url = resp.url
        if '/api/cortars' not in url or resp.status != 200:
            return
        try:
            d = resp.json()
        except Exception:
            return

        # 전체 응답 첫 번째만 저장
        if first_full is None:
            first_full = d

        # cortarNo 추출 (구조 불명이므로 가능한 키 모두 시도)
        cno = (d.get('cortarNo') or d.get('sectorNo') or
               d.get('regionNo') or d.get('areaNo'))
        cname = (d.get('cortarName') or d.get('sectorName') or
                 d.get('regionName') or '')
        div = d.get('divisionName') or d.get('cityName') or ''
        clat = d.get('centerLat') or d.get('lat') or ''
        clon = d.get('centerLon') or d.get('lon') or ''

        if cno and cno not in cortars:
            cortars[cno] = {
                'name': cname, 'division': div,
                'centerLat': clat, 'centerLon': clon,
            }
            print(f'  NEW: {cno} {cname} ({div})')

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=UA, locale='ko-KR', viewport={'width': 1280, 'height': 800}
        )
        page = ctx.new_page()
        page.on('response', on_resp)

        print('[1] 워밍업...')
        try:
            page.goto(
                'https://new.land.naver.com/?ms=35.858,128.627,15&a=APT&b=A1&e=RETAIL',
                wait_until='networkidle', timeout=30000
            )
        except Exception:
            pass
        time.sleep(2)

        print(f'[2] 수성구 격자 {len(centers)}개 순회 (cortarNo 수집)...')
        for i, (lat, lon) in enumerate(centers):
            try:
                page.goto(
                    f'https://new.land.naver.com/?ms={lat},{lon},15&a=APT&b=A1&e=RETAIL',
                    wait_until='networkidle', timeout=20000
                )
            except Exception:
                pass
            time.sleep(1.2)
            if (i + 1) % 10 == 0:
                print(f'    [{i+1}/{len(centers)}] 수집된 cortarNo: {len(cortars)}개')

        browser.close()

    print('\n' + '=' * 60)
    print('첫 번째 api/cortars 전체 응답 구조:')
    print('=' * 60)
    if first_full:
        print(json.dumps(first_full, ensure_ascii=False, indent=2)[:3000])
    else:
        print('(캡처 없음)')

    print(f'\n수집된 수성구 cortarNo: {len(cortars)}개')
    for cno, info in sorted(cortars.items()):
        if '수성' in info.get('division', '') or '수성' in info.get('name', ''):
            print(f'  {cno}: {info["name"]} ({info["division"]}) '
                  f'center=({info["centerLat"]},{info["centerLon"]})')

    print(f'\n전체 수집된 cortarNo: {len(cortars)}개 (수성구 + 인근 구 경계)')
    for cno, info in sorted(cortars.items()):
        print(f'  {cno}: {info["name"]} ({info["division"]})')


if __name__ == '__main__':
    main()
