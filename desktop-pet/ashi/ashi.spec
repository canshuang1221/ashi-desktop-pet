# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_all

# 只打包成品立绘，**排除 assets/_source**（生图/抠图用的原始大图）。
# 之前整目录打包，每版都白送约 25MB 的原始素材（exe 71.5MB → 现在 46MB）。
def _asset_datas():
    out = []
    here = os.path.dirname(os.path.abspath(SPEC)) if 'SPEC' in dir() else os.getcwd()
    base = os.path.join(here, 'assets')
    for name in sorted(os.listdir(base)):
        if name.startswith('.') or name == '_source':
            continue
        src = os.path.join(base, name)
        if os.path.isfile(src):
            out.append((src, 'assets'))
    return out


datas = _asset_datas()
binaries = []
hiddenimports = []
tmp_ret = collect_all('certifi')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PyQt5', 'tkinter', 'matplotlib'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='ashi',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
