"""
미매칭 수성구 최근 단지 Naver 실거래 + MOLIT 비교
"""
import sys; sys.stdout.reconfigure(encoding='utf-8')
import os, time, requests
import xml.etree.ElementTree as ET
import pandas as pd
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv

load_dotenv()
BASE = os.path.dirname(os.path.abspath(__file__))
API_KEY = os.getenv('MOLIT_API_KEY', '')
API_URL = 'https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev'
DAEGU_LAWD = {'수성구': '27260', '달서구': '27290', '북구': '27230', '동구': '27140'}

df_un = pd.read_excel(os.path.join(BASE, 'complex_molit_map_review.xlsx'), sheet_name='미매칭')
# 수성구 최근 건축 10개
targets = (df_un[df_un['구'] == '수성구']
           .sort_values('건축년도', ascending=False)
           .head(10)[['단지코드', 'Naver단지명', '구', '동', '건축년도']]
           .to_dict('records'))

# ── Naver overview 조회 ─────────────────────────────────────────────
naver_info = {}

def on_resp(resp):
    for t in targets:
        cid = str(t['단지코드'])
        if f'complexes/overview/{cid}' in resp.url and resp.status == 200:
            try:
                d = resp.json()
                naver_info[cid] = {
                    'typeName': d.get('complexTypeName', ''),
                    'realPrice': d.get('realPrice'),
                    'minPrice': d.get('minPriceByLetter', ''),
                    'maxPrice': d.get('maxPriceByLetter', ''),
                }
            except: pass

print('Naver overview 조회 중...')
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(user_agent='Mozilla/5.0', locale='ko-KR', viewport={'width':1280,'height':800})
    page = ctx.new_page()
    page.on('response', on_resp)
    for t in targets:
        cid = str(t['단지코드'])
        try:
            page.goto(f'https://new.land.naver.com/complexes/{cid}', wait_until='networkidle', timeout=20000)
        except: pass
        time.sleep(0.4)
    browser.close()

# ── MOLIT 동일 구+동 최근 6개월 단지명 목록 ────────────────────────
def prev_months(n):
    d = datetime.today().replace(day=1)
    r = []
    for _ in range(n):
        r.append(d.strftime('%Y%m'))
        d -= timedelta(days=1)
        d = d.replace(day=1)
    return r

molit_cache = {}
def get_molit_dong(lawd, dong, n_months=6):
    key = (lawd, dong)
    if key in molit_cache:
        return molit_cache[key]
    rows = []
    for ymd in prev_months(n_months):
        url = f'{API_URL}?serviceKey={API_KEY}&LAWD_CD={lawd}&DEAL_YMD={ymd}&numOfRows=1000&pageNo=1'
        try:
            r = requests.get(url, timeout=15)
            if r.status_code != 200: continue
            root = ET.fromstring(r.content)
            for item in root.findall('.//item'):
                def g(tag, _i=item):
                    el = _i.find(tag); return el.text.strip() if el is not None and el.text else ''
                if g('umdNm') == dong:
                    rows.append({'아파트명': g('aptNm'), '년': g('dealYear'), '월': g('dealMonth'),
                                 '금액': g('dealAmount').replace(',',''), '면적': g('excluUseAr')})
        except: pass
    molit_cache[key] = rows
    return rows

# ── 결과 출력 ────────────────────────────────────────────────────────
print()
print('=' * 70)
for t in targets:
    cid  = str(t['단지코드'])
    name = t['Naver단지명']
    gu   = t['구']
    dong = t['동']
    yr   = t['건축년도']
    lawd = DAEGU_LAWD.get(gu, '')
    info = naver_info.get(cid, {})
    rp   = info.get('realPrice')

    print(f'\n[{name}] {cid} / {gu} {dong} / {yr}년')
    print(f'  Naver 유형: {info.get("typeName","-")} | 호가: {info.get("minPrice","-")}~{info.get("maxPrice","-")}')
    if rp:
        print(f'  Naver 최근실거래: {rp.get("tradeYear")}.{rp.get("tradeMonth"):02d}.{rp.get("tradeDate")} '
              f'{rp.get("formattedPrice")} {rp.get("exclusiveArea")}㎡ {rp.get("floor")}층')
        # MOLIT 매칭 시도
        if lawd:
            tx_ymd = f'{rp["tradeYear"]}{int(rp["tradeMonth"]):02d}'
            molit_rows = get_molit_dong(lawd, dong, n_months=6)
            tx_price = str(rp.get('dealPrice', ''))
            matched = [r for r in molit_rows if r['년'] == str(rp['tradeYear'])
                       and r['월'].lstrip('0') == str(rp['tradeMonth']).lstrip('0')
                       and r['금액'] == tx_price]
            if matched:
                print(f'  MOLIT 매칭: "{matched[0]["아파트명"]}" (이름 차이 확인!)')
            else:
                print(f'  MOLIT 동일 거래 없음')
                dong_names = list({r["아파트명"] for r in molit_rows})
                print(f'  {dong} MOLIT 단지들: {dong_names[:8]}')
    else:
        print(f'  Naver 최근실거래: 없음')
        if lawd:
            molit_rows = get_molit_dong(lawd, dong, n_months=6)
            dong_names = list({r["아파트명"] for r in molit_rows})
            print(f'  {dong} MOLIT 거래 단지들(6개월): {dong_names[:8]}')
