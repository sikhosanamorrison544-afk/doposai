#!/bin/bash
# Build a standalone executable using PyInstaller

cd "$(dirname "$0")"

echo "=========================================="
echo "Building Standalone POS Application"
echo "=========================================="
echo ""

# Check if PyInstaller is installed
if ! python3 -c "import PyInstaller" 2>/dev/null; then
    echo "Installing PyInstaller..."
    pip install pyinstaller
fi

# Create PyInstaller spec file
cat > pos_launcher.spec << 'EOF'
# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['launch_pos.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('app', 'app'),
        ('templates', 'templates'),
        ('static', 'static'),
        ('pos.db', '.'),
    ],
    hiddenimports=[
        'uvicorn.lifespan.on',
        'uvicorn.lifespan.off',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.protocols.websockets.websockets_impl',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.http.h11_impl',
        'uvicorn.protocols.http.httptools_impl',
        'uvicorn.loops.auto',
        'uvicorn.loops.asyncio',
        'uvicorn.logging',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='POS-System',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='pos_icon.ico' if os.path.exists('pos_icon.ico') else None,
)
EOF

echo "Building executable..."
pyinstaller --clean pos_launcher.spec

if [ -f "dist/POS-System" ]; then
    echo ""
    echo "=========================================="
    echo "Build successful!"
    echo "=========================================="
    echo ""
    echo "Executable created at: dist/POS-System"
    echo ""
    echo "You can run it with:"
    echo "  ./dist/POS-System"
    echo ""
    echo "Or create a desktop entry that points to:"
    echo "  $(pwd)/dist/POS-System"
else
    echo ""
    echo "Build may have failed. Check the output above for errors."
fi

