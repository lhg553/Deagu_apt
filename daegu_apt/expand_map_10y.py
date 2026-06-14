# -*- coding: utf-8 -*-
"""
10년 MOLIT 데이터로 미매칭 단지 추가 매핑 시도
complex_molit_map.json, complex_aptseq_map.json 갱신
"""
import sys; sys.stdout.reconfigure(encoding='utf-8')
import os, re, json, difflib
import pandas as pd
from dotenv import load_dotenv

load_dotenv()
BASE     = os.path.dirname(os.path.abspath(__file__))
MAP_FILE = os.path.join(BASE, 'complex_molit_map.json')
SEQ_FILE = os.path.join(BASE, 'complex_aptseq_map.json')
REVIEW   = os.path.join(BASE, 'complex_molit_map_review.xlsx')
API_KEY  = os.getenv('MOLIT_API_KEY', '')


def normalize(s):
    return re.sub(r'[\s　]', '', str(s)).lower()

def strip_suffix(s):
    return re.sub(r'\s*\([^)]*\)', '', str(s)).strip()

def extract_ordinal(s):
    found = set()
    found.update(re.findall(r'\d+차', s))
    found.update(re.findall(r'[A-Z]동', s))
    found.update(re.findall(r'\d+지구', s))
    found.update(re.findall(r'\d+블록', s))
    found.update(re.findall(r'\d+단지', s))
    return found

def ordinal_ok(a, b):
    oa, ob = extract_ordinal(a), extract_ordinal(b)
    if not oa or not ob:
        return True
    return bool(oa & ob)

def safe_year(val):
    try:
        s = str(val)
        if s in ('', 'nan', 'None'):
            return ''
        return str(int(float(s)))[:4]
    except Exception:
        return ''


# ── 기존 매핑 로드 ─────────────────────────────────────────────────────
with open(MAP_FILE, encoding='utf-8') as f:
    name_map = json.load(f)
with open(SEQ_FILE, encoding='utf-8') as f:
    aptseq_map = json.load(f)

df_all     = pd.read_excel(REVIEW, sheet_name='전체매핑')
df_unmatch = pd.read_excel(REVIEW, sheet_name='미매칭')

# 이미 name_map에 있는 것 제외 (build_aptseq_map Phase 2 추가분 포함)
targets = df_unmatch[~df_unmatch['단지코드'].astype(str).isin(name_map)].copy()
print(f'기존: name_map {len(name_map)}개 / aptSeq {len(aptseq_map)}개')
print(f'미매칭 시트: {len(df_unmatch)}개 → 실 대상: {len(targets)}개 (이미 추가 {len(df_unmatch)-len(targets)}개 제외)')

# ── 10년 MOLIT 수집 ────────────────────────────────────────────────────
print(f'\n=== MOLIT 10년 수집 (8구 × 120개월 = 960 API 호출) ===')
from molit_scraper import MolitScraper
scraper = MolitScraper(API_KEY)
molit_df = scraper.collect(district='all', months=120)

if molit_df.empty:
    print('MOLIT 데이터 없음 — API 키 확인')
    sys.exit(1)
print(f'\n수집 완료: {len(molit_df):,}건')

# aptSeq 있는 행만 사용
molit_seq = molit_df[molit_df['aptSeq'].ne('')].copy()
molit_seq['_norm'] = molit_seq['아파트명'].apply(normalize)
print(f'aptSeq 보유 행: {len(molit_seq):,}건')

# ── 룩업 테이블 구성 ────────────────────────────────────────────────────
# (구, 법정동) → {norm_name: aptSeq}
dong_pool: dict = {}
for (gu, dong, norm), grp in molit_seq.groupby(['구', '법정동', '_norm']):
    dong_pool.setdefault((gu, dong), {})[norm] = grp['aptSeq'].value_counts().idxmax()

# (구, 건축년도) → {norm_name: aptSeq}
year_pool: dict = {}
yr_rows = molit_seq[molit_seq['건축년도'].astype(str).str.match(r'^\d{4}$')]
for (gu, yr, norm), grp in yr_rows.groupby(['구', '건축년도', '_norm']):
    year_pool.setdefault((gu, str(yr)), {})[norm] = grp['aptSeq'].value_counts().idxmax()

# (구, norm_name) → aptSeq  (Phase 1 보완용)
name_lookup: dict = {}
for (gu, norm), grp in molit_seq.groupby(['구', '_norm']):
    name_lookup[(gu, norm)] = grp['aptSeq'].value_counts().idxmax()

# aptSeq → 대표 아파트명
seq_to_name: dict = {}
for seq, grp in molit_seq.groupby('aptSeq'):
    seq_to_name[seq] = grp['아파트명'].value_counts().idxmax()

print(f'dong_pool 키: {len(dong_pool)}개 / year_pool 키: {len(year_pool)}개')

# ── Phase 1 보완: name_map 있지만 aptSeq 없는 것 → 10년 데이터로 재시도 ──
meta = {str(r['단지코드']): r for _, r in df_all.iterrows()}
p1_extra = 0
for cid, molit_nm in name_map.items():
    if cid in aptseq_map:
        continue
    m = meta.get(cid, {})
    gu = str(m.get('구', ''))
    if (gu, normalize(molit_nm)) in name_lookup:
        aptseq_map[cid] = name_lookup[(gu, normalize(molit_nm))]
        p1_extra += 1
if p1_extra:
    print(f'Phase 1 보완: aptSeq {p1_extra}개 신규')

# ── 미매칭 단지 fuzzy 재매핑 ─────────────────────────────────────────────
print(f'\n=== 미매칭 {len(targets)}개 fuzzy 재매핑 (10년 풀) ===')
name_added = seq_added = 0

for _, row in targets.iterrows():
    cid     = str(row['단지코드'])
    nv_name = str(row['Naver단지명']).replace(' ', '')
    nv_s    = strip_suffix(nv_name)
    gu      = str(row['구'])
    dong    = str(row.get('동', '')) if pd.notna(row.get('동')) else ''
    yr      = safe_year(row.get('건축년도'))

    matched_seq = None

    # 3단계: 구+동 fuzzy 0.78
    d_pool = dong_pool.get((gu, dong), {})
    if d_pool:
        ms = difflib.get_close_matches(nv_s or nv_name, list(d_pool.keys()), n=3, cutoff=0.78)
        for cand in ms:
            if ordinal_ok(nv_name, cand):
                matched_seq = d_pool[cand]
                break

    # 4단계: 구+건축년도 fuzzy 0.65
    if matched_seq is None and yr:
        y_pool = year_pool.get((gu, yr), {})
        if y_pool:
            ms = difflib.get_close_matches(nv_s or nv_name, list(y_pool.keys()), n=3, cutoff=0.65)
            for cand in ms:
                if ordinal_ok(nv_name, cand):
                    matched_seq = y_pool[cand]
                    break

    if matched_seq:
        aptseq_map[cid] = matched_seq
        seq_added += 1
        nm = seq_to_name.get(matched_seq, '')
        if nm:
            name_map[cid] = nm
            name_added += 1

print(f'  name 신규: {name_added}개')
print(f'  aptSeq 신규: {seq_added}개')

# ── 저장 ──────────────────────────────────────────────────────────────────
with open(MAP_FILE, 'w', encoding='utf-8') as f:
    json.dump(name_map, f, ensure_ascii=False, indent=2)
with open(SEQ_FILE, 'w', encoding='utf-8') as f:
    json.dump(aptseq_map, f, ensure_ascii=False, indent=2)

total = len(df_all)
print(f'\n=== 완료 ===')
print(f'  name_map : {len(name_map):,} / {total:,}개')
print(f'  aptSeq   : {len(aptseq_map):,} / {total:,}개 ({len(aptseq_map)/total*100:.1f}%)')
