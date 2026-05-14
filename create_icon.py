#!/usr/bin/env python3
"""
Create a simple icon for the POS system
"""
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:
    HAS_PIL = False
    print("Pillow not installed. Creating a simple SVG icon instead.")

BASE_DIR = Path(__file__).parent

if HAS_PIL:
    # Create PNG icon
    size = 512
    img = Image.new('RGB', (size, size), color='#1e293b')
    draw = ImageDraw.Draw(img)
    
    # Draw a simple POS/cash register icon
    # Outer box
    draw.rectangle([80, 80, 432, 432], fill='#0f172a', outline='#64748b', width=4)
    
    # Screen/display area
    draw.rectangle([120, 120, 392, 280], fill='#1e293b', outline='#475569', width=3)
    
    # Text "POS"
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 120)
    except:
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", 120)
        except:
            font = ImageFont.load_default()
    
    draw.text((256, 200), "POS", fill='#3b82f6', font=font, anchor='mm')
    
    # Draw buttons
    for i, y in enumerate([320, 380]):
        draw.ellipse([180 + i*80, y, 220 + i*80, y+40], fill='#475569', outline='#64748b', width=2)
    
    # Save icon
    icon_path = BASE_DIR / "pos_icon.png"
    img.save(icon_path)
    print(f"Icon created: {icon_path}")
    
    # Also create smaller sizes for desktop entry
    for size in [32, 48, 64, 128, 256]:
        small_img = img.resize((size, size), Image.Resampling.LANCZOS)
        small_path = BASE_DIR / f"pos_icon_{size}.png"
        small_img.save(small_path)
else:
    # Create SVG icon as fallback
    svg_content = '''<?xml version="1.0" encoding="UTF-8"?>
<svg width="512" height="512" xmlns="http://www.w3.org/2000/svg">
  <rect width="512" height="512" fill="#1e293b"/>
  <rect x="80" y="80" width="352" height="352" fill="#0f172a" stroke="#64748b" stroke-width="4"/>
  <rect x="120" y="120" width="272" height="160" fill="#1e293b" stroke="#475569" stroke-width="3"/>
  <text x="256" y="230" font-family="Arial, sans-serif" font-size="120" font-weight="bold" fill="#3b82f6" text-anchor="middle">POS</text>
  <circle cx="210" cy="340" r="20" fill="#475569" stroke="#64748b" stroke-width="2"/>
  <circle cx="290" cy="400" r="20" fill="#475569" stroke="#64748b" stroke-width="2"/>
</svg>'''
    
    icon_path = BASE_DIR / "pos_icon.svg"
    with open(icon_path, 'w') as f:
        f.write(svg_content)
    print(f"SVG icon created: {icon_path}")

