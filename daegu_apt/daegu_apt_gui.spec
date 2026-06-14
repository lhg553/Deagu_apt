# -*- mode: python ; coding: utf-8 -*-
import shutil, os
from PyInstaller.utils.hooks import collect_all

datas = [
    ('daegu_boundaries.json', '.'),
    ('daegu_cortars.json', '.'),
    ('complex_molit_map.json', '.'),
]
binaries = []
hiddenimports = ['openpyxl', 'requests', 'dotenv', 'naver_scraper', 'molit_scraper', 'location_enricher', 'combine', 'main']
tmp_ret = collect_all('playwright')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('numpy')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pandas')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('shapely')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('charset_normalizer')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['gui.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='daegu_apt_gui',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='daegu_apt_gui',
)

# EXE 옆에 사용자 문서 + 매핑 파일 복사 (빌드할 때마다 자동 포함)
_dist_root = os.path.join(DISTPATH, 'daegu_apt_gui')
for _fname in ['사용설명서.txt', '엑셀_데이터_명세.md', 'complex_molit_map.json']:
    _src = os.path.join(SPECPATH, _fname)
    if os.path.exists(_src):
        shutil.copy2(_src, os.path.join(_dist_root, _fname))
