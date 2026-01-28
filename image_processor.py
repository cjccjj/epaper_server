import requests
from PIL import Image, ImageDraw, ImageFont
import io
import numpy as np
import os

# Configuration for image processing
STRETCH_THRESHOLD = 0.33  # If padding ratio is less than this, stretch image instead of padding

def resize_if_large(img, max_dim=1024):
    """Resize image if any dimension exceeds max_dim, maintaining aspect ratio."""
    w, h = img.size
    if w > max_dim or h > max_dim:
        if w > h:
            new_w = max_dim
            new_h = int(h * (max_dim / w))
        else:
            new_h = max_dim
            new_w = int(w * (max_dim / h))
        img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    return img

def download_image(url):
    headers = {"User-Agent": "linux:epaper-server:v1.0.0 (by /u/cj)"}
    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()
    return Image.open(io.BytesIO(response.content))

def fit_resize(img, target_size=(400, 300), stretch_threshold=STRETCH_THRESHOLD):
    """
    Resize image to fit within target_size. 
    If the required padding is less than stretch_threshold, stretch the image instead.
    Otherwise, raise a ValueError (user cheat: only use images that don't need padding).
    """
    tw, th = target_size
    iw, ih = img.size
    
    # Calculate scale factor for fitting
    scale = min(tw / iw, th / ih)
    nw, nh = int(iw * scale), int(ih * scale)
    
    # Calculate how much of the target area would be 'fill' (padding)
    target_area = tw * th
    fitted_area = nw * nh
    fill_ratio = (target_area - fitted_area) / target_area
    
    if fill_ratio <= stretch_threshold:
        # If the gap is small, just stretch it to full target size
        return img.resize(target_size, Image.Resampling.LANCZOS)
    else:
        # User cheat: do not pad. If padding is needed, we drop this image.
        raise ValueError(f"Image requires {fill_ratio:.1%} padding, which exceeds {stretch_threshold:.1%} threshold. Dropping.")

def apply_ac(data, clip_pct=22, cost_pct=6):
    """Weighted Approaching Auto-Contrast logic ported from JS."""
    h, w = data.shape
    hist, _ = np.histogram(data, bins=256, range=(0, 256))
    
    total = w * h
    avg = np.mean(data)
    
    # Calculate potential damage
    total_potential_damage = 0
    for i in range(256):
        total_potential_damage += hist[i] * abs(i - avg)
        
    target_area = total * (clip_pct / 100.0)
    target_cost = total_potential_damage * (cost_pct / 100.0)
    min_target = total * 0.005 # 0.5% safety clip
    
    rem_black = total
    rem_white = total
    left = 0
    right = 255
    clipped_black = 0
    clipped_white = 0
    clipped_total = 0
    total_cost = 0
    
    while left < right and total_cost < target_cost and clipped_total < target_area:
        if rem_white >= rem_black:
            count = hist[right]
            cost = count * (255 - right)
            total_cost += cost
            clipped_total += count
            rem_white -= count
            clipped_white += count
            right -= 1
        else:
            count = hist[left]
            cost = count * left
            total_cost += cost
            clipped_total += count
            rem_black -= count
            clipped_black += count
            left += 1
            
    # Safety clips
    while left < right and clipped_black < min_target:
        clipped_black += hist[left]
        left += 1
    while left < right and clipped_white < min_target:
        clipped_white += hist[right]
        right -= 1
        
    scale = 255.0 / (right - left if right > left else 1)
    
    # Apply contrast
    data = data.astype(np.float32)
    data = np.clip((data - left) * scale, 0, 255)
    return data.astype(np.uint8)

def apply_burkes(data):
    """Burkes Dithering logic ported from JS."""
    h, w = data.shape
    out = data.astype(np.float32)
    
    for y in range(h):
        for x in range(w):
            old_val = out[y, x]
            new_val = 0 if old_val < 128 else 255
            err = (old_val - new_val) / 32.0
            out[y, x] = new_val
            
            def add_err(nx, ny, factor):
                if 0 <= nx < w and 0 <= ny < h:
                    out[ny, nx] = np.clip(out[ny, nx] + err * factor, 0, 255)
            
            add_err(x + 1, y,     8)
            add_err(x + 2, y,     4)
            add_err(x - 2, y + 1, 2)
            add_err(x - 1, y + 1, 4)
            add_err(x,     y + 1, 8)
            add_err(x + 1, y + 1, 4)
            add_err(x + 2, y + 1, 2)
                
    return out.astype(np.uint8)

from PIL import ImageDraw, ImageFont

def overlay_title(img, title):
    """Overlay title on the bottom of the image with outlined text for legibility."""
    if not title:
        return img
    
    draw = ImageDraw.Draw(img)
    w, h = img.size
    
    # Improved font loading with fallbacks
    font_paths = ["/app/data/ntailu.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    font = None
    
    for path in font_paths:
        try:
            # em-size 33 usually yields ~24-26px actual height
            font = ImageFont.truetype(path, 33)
            break 
        except Exception:
            continue
            
    if font is None:
        font = ImageFont.load_default()
        ascent, descent = 10, 2 # Rough estimates for default
    else:
        ascent, descent = font.getmetrics()

    line_height = ascent + descent
    # Use a consistent area height regardless of specific character glyphs
    area_h = max(34, line_height + 10)
    
    # Measure text width
    def get_text_width(text):
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0]

    # Truncate if too long
    if get_text_width(title) > w - 20:
        while get_text_width(title + "...") > w - 20 and len(title) > 0:
            title = title[:-1]
        title += "..."

    text_w = get_text_width(title)
    
    # Calculations for positioning
    x = (w - text_w) // 2
    # Use ascent to anchor the baseline consistently
    y = h - area_h + (area_h - line_height) // 2 
    
    # Draw black outline (8-way)
    # Note: If img mode is '1', fill=0 is black, fill=255 is white.
    for dx, dy in [(-1,-1), (-1,0), (-1,1), (0,-1), (0,1), (1,-1), (1,0), (1,1)]:
        draw.text((x + dx, y + dy), title, font=font, fill=0)
    
    # Draw white text center
    draw.text((x, y), title, font=font, fill=255)
    
    return img

def process_and_dither(img, target_size=(400, 300), clip_pct=22, cost_pct=6, resize_mode='fit', stretch_threshold=STRETCH_THRESHOLD, title=None):
    # 1. Resize
    img = fit_resize(img, target_size, stretch_threshold=stretch_threshold)
    
    # 2. Convert to grayscale
    img = img.convert("L")
    data = np.array(img).astype(np.float32)
    
    # Apply Gamma 2.2 Correction
    data = 255.0 * np.power(data / 255.0, 1.0 / 2.2)
    data = data.astype(np.uint8)
    
    # 3. Apply Weighted Approaching Auto-Contrast
    data = apply_ac(data, clip_pct, cost_pct)
    
    # 4. Apply Burkes Dithering
    data = apply_burkes(data)
    
    # 5. Convert back to Pillow image (1-bit mode)
    dithered_img = Image.fromarray(data).convert("1")
    
    # 6. Overlay title if provided
    if title:
        dithered_img = overlay_title(dithered_img, title)
        
    return dithered_img


def save_as_bmp(img, path):
    # Ensure directory exists if path contains one
    dir_name = os.path.dirname(path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
    # BMP format for epaper usually needs to be 1-bit or 8-bit
    img.save(path, format="BMP")

def process_image_url(url, output_path, target_size=(400, 300), resize_mode='fit', stretch_threshold=STRETCH_THRESHOLD, title=None):
    """Complete helper to download, process, and save an image."""
    img = download_image(url)
    dithered = process_and_dither(img, target_size, resize_mode=resize_mode, stretch_threshold=stretch_threshold, title=title)
    save_as_bmp(dithered, output_path)
    return output_path
