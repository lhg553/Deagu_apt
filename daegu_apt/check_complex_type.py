import sys; sys.stdout.reconfigure(encoding='utf-8')
import json, time, random
import pandas as pd
from playwright.sync_api import sync_playwright

df = pd.read_excel('complex_molit_map_review.xlsx', sheet_name='미매칭')
samples = df['단지코드'].astype(str).tolist()[:30]

results = {}

def on_resp(resp):
    for cid in samples:
        if f'complexes/overview/{cid}' in resp.url and resp.status == 200:
            try:
                d = resp.json()
                results[cid] = {
                    'name': d.get('complexName', ''),
                    'typeName': d.get('complexTypeName', ''),
                    'typeCode': d.get('complexType', ''),
                }
            except:
                pass

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        locale='ko-KR', viewport={'width': 1280, 'height': 800}
    )
    page = ctx.new_page()
    page.on('response', on_resp)
    for i, cid in enumerate(samples[:20]):
        try:
            page.goto(f'https://new.land.naver.com/complexes/{cid}', wait_until='networkidle', timeout=20000)
        except Exception:
            pass
        time.sleep(random.uniform(0.3, 0.5))
        if (i + 1) % 5 == 0:
            print(f'  [{i+1}/20] 조회 중...')
    browser.close()

print(f'\n결과 {len(results)}개:')
type_count = {}
for cid, info in results.items():
    t = info['typeName']
    type_count[t] = type_count.get(t, 0) + 1
    print(f'{cid}: {info["name"]} | {info["typeName"]}({info["typeCode"]})')

print('\n유형별 집계:')
for t, cnt in sorted(type_count.items(), key=lambda x: -x[1]):
    print(f'  {t}: {cnt}개')
