"""
Naver 단지코드 ↔ MOLIT aptSeq 매핑 구축
Phase 1: complex_molit_map.json 이미 매핑된 단지 → MOLIT 데이터에서 aptSeq 조회 (빠름)
Phase 2: 미매칭 단지 → Naver realPrice로 MOLIT 거래 매칭 → aptSeq (Playwright)
출력: complex_aptseq_map.json  {단지코드: aptSeq}
"""
import sys; sys.stdout.reconfigure(encoding='utf-8')
import os, re, json, time, random
import pandas as pd
from dotenv import load_dotenv

load_dotenv()
BASE     = os.path.dirname(os.path.abspath(__file__))
MAP_FILE = os.path.join(BASE, 'complex_molit_map.json')
OUT_FILE = os.path.join(BASE, 'complex_aptseq_map.json')
REVIEW   = os.path.join(BASE, 'complex_molit_map_review.xlsx')
API_KEY  = os.getenv('MOLIT_API_KEY', '')


def normalize(s: str) -> str:
    return re.sub(r'[\s　]', '', str(s)).lower()


# ── 기존 매핑 로드 ────────────────────────────────────────────────
print('기존 aptSeq 매핑 로드...')
aptseq_map: dict = {}
if os.path.exists(OUT_FILE):
    with open(OUT_FILE, encoding='utf-8') as f:
        aptseq_map = json.load(f)
    print(f'  기존: {len(aptseq_map)}개')

with open(MAP_FILE, encoding='utf-8') as f:
    name_map: dict = json.load(f)   # {단지코드: MOLIT아파트명}

df_review = pd.read_excel(REVIEW, sheet_name='전체매핑')
# 단지코드 → {구, 동, 건축년도} 룩업
meta = {str(r['단지코드']): r for _, r in df_review.iterrows()}

# ── Phase 1: MOLIT 데이터 수집 → aptSeq 룩업 ─────────────────────
print('\n=== Phase 1: MOLIT 실거래 수집 (12개월) ===')
from molit_scraper import MolitScraper
scraper = MolitScraper(API_KEY)
molit_df = scraper.collect(district='all', months=12)

if molit_df.empty:
    print('  MOLIT 데이터 없음 — API 키 확인 필요')
else:
    print(f'  수집: {len(molit_df)}건')
    # aptSeq가 있는 행만 사용
    molit_seq = molit_df[molit_df['aptSeq'].ne('')].copy()
    molit_seq['_norm'] = molit_seq['아파트명'].apply(normalize)

    # {(구, norm_name): aptSeq} 룩업 (가장 많이 나온 aptSeq를 대표값으로)
    seq_lookup: dict = {}
    for (gu, norm), grp in molit_seq.groupby(['구', '_norm']):
        top = grp['aptSeq'].value_counts().idxmax()
        seq_lookup[(gu, norm)] = top

    # 이름 매핑된 단지들에 aptSeq 부여
    p1_found = 0
    for cid, molit_nm in name_map.items():
        if cid in aptseq_map:
            continue
        m = meta.get(cid, {})
        gu = str(m.get('구', ''))
        key = (gu, normalize(molit_nm))
        if key in seq_lookup:
            aptseq_map[cid] = seq_lookup[key]
            p1_found += 1

    print(f'  Phase 1 신규 매핑: {p1_found}개')
    print(f'  누적 aptSeq 매핑: {len(aptseq_map)}개')

# 중간 저장
with open(OUT_FILE, 'w', encoding='utf-8') as f:
    json.dump(aptseq_map, f, ensure_ascii=False, indent=2)
print(f'  중간 저장: {OUT_FILE}')

# ── Phase 2: 미매칭 단지 → Naver realPrice 매칭 ──────────────────
print('\n=== Phase 2: 미매칭 단지 Naver realPrice 매칭 ===')
df_un = pd.read_excel(REVIEW, sheet_name='미매칭')
# 이미 aptSeq 확보된 것 제외
targets = df_un[~df_un['단지코드'].astype(str).isin(aptseq_map)].copy()
print(f'  대상: {len(targets)}개 미매칭 단지')

if targets.empty or molit_df.empty:
    print('  대상 없음 — 종료')
else:
    from playwright.sync_api import sync_playwright

    UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'

    # MOLIT 데이터 인덱스: (구, 거래년도, 거래월, 거래일, 금액) → aptSeq
    molit_seq2 = molit_df[molit_df['aptSeq'].ne('')].copy()
    molit_seq2['_price'] = molit_seq2['거래금액(만원)'].astype(str).str.replace(',', '')
    tx_index: dict = {}
    for _, row in molit_seq2.iterrows():
        key = (str(row['구']),
               str(row['거래년도']), str(int(row['거래월'])),
               str(int(row['거래일'])), row['_price'])
        tx_index.setdefault(key, []).append(row['aptSeq'])

    naver_info: dict = {}
    cids = targets['단지코드'].astype(str).tolist()

    def on_resp(resp):
        for cid in cids:
            if f'complexes/overview/{cid}' in resp.url and resp.status == 200:
                try:
                    d = resp.json()
                    rp = d.get('realPrice')
                    if rp:
                        naver_info[cid] = rp
                except Exception:
                    pass

    print(f'  Naver 개요 조회 중 ({len(cids)}개)...')
    batch = 50  # 한 번에 50개씩 (메모리·속도 균형)
    p2_found = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA, locale='ko-KR',
                                   viewport={'width': 1280, 'height': 800})
        page = ctx.new_page()
        page.on('response', on_resp)

        for i, cid in enumerate(cids):
            try:
                page.goto(f'https://new.land.naver.com/complexes/{cid}',
                          wait_until='networkidle', timeout=20000)
            except Exception:
                pass
            time.sleep(random.uniform(0.3, 0.5))
            if (i + 1) % 10 == 0 or i == len(cids) - 1:
                print(f'    [{i+1}/{len(cids)}] realPrice 확보: {len(naver_info)}개')

        browser.close()

    # realPrice → MOLIT 매칭
    for _, row in targets.iterrows():
        cid = str(row['단지코드'])
        rp  = naver_info.get(cid)
        if not rp:
            continue
        gu       = str(row['구'])
        tx_year  = str(rp.get('tradeYear', ''))
        tx_month = str(int(rp.get('tradeMonth', 0)))
        tx_day   = str(int(str(rp.get('tradeDate', '0')).lstrip('0') or '0'))
        tx_price = str(rp.get('dealPrice', ''))
        key = (gu, tx_year, tx_month, tx_day, tx_price)
        matches = tx_index.get(key, [])
        if len(matches) == 1:
            aptseq_map[cid] = matches[0]
            p2_found += 1
        elif len(matches) > 1:
            # 여러 단지 매칭 시 면적으로 추가 필터
            tx_area = str(rp.get('exclusiveArea', ''))
            for seq in matches:
                sub = molit_seq2[molit_seq2['aptSeq'] == seq]
                if any(sub['전용면적㎡'].astype(str).str.startswith(tx_area[:4])):
                    aptseq_map[cid] = seq
                    p2_found += 1
                    break

    print(f'  Phase 2 신규 매핑: {p2_found}개')

# ── 최종 저장 ─────────────────────────────────────────────────────
with open(OUT_FILE, 'w', encoding='utf-8') as f:
    json.dump(aptseq_map, f, ensure_ascii=False, indent=2)

total = len(df_review)
print(f'\n=== 완료 ===')
print(f'  aptSeq 매핑: {len(aptseq_map)} / {total}개 ({len(aptseq_map)/total*100:.1f}%)')
print(f'  저장: {OUT_FILE}')
