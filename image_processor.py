import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import io
import numpy as np
import os

# --- Helper Functions (Core Processing) ---

def download_image_simple(url):
    """Download image from URL and return as PIL Image object."""
    headers = {"User-Agent": "linux:epaper-server:v1.0.0 (by /u/cj)"}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        return Image.open(io.BytesIO(response.content))
    except Exception as e:
        print(f"Error downloading image: {e}")
        return None

def fit_resize(img, target_size=(400, 300)):
    """
    Resize and crop image to fill target_size (Crop-to-fill).
    """
    tw, th = target_size
    iw, ih = img.size
    
    scale = max(tw / iw, th / ih)
    nw, nh = int(iw * scale), int(ih * scale)
    
    ox = (tw - nw) // 2
    oy = (th - nh) // 2
    
    img = img.resize((nw, nh), Image.Resampling.LANCZOS)
    target = Image.new("RGB", (tw, th), (255, 255, 255))
    target.paste(img, (ox, oy))
    return target

def sharpen_image(img, amount=1.0):
    """Apply UnsharpMask sharpening to a PIL image."""
    if amount <= 0:
        return img
    return img.filter(ImageFilter.UnsharpMask(radius=1, percent=int(amount * 100), threshold=3))

def apply_ac(data, clip_pct=22, cost_pct=6):
    """Weighted Approaching Auto-Contrast logic."""
    h, w = data.shape
    hist, _ = np.histogram(data, bins=256, range=(0, 256))
    
    total = w * h
    avg = np.mean(data)
    
    indices = np.arange(256)
    total_potential_damage = np.sum(hist * np.abs(indices - avg))
        
    target_area = total * (clip_pct / 100.0)
    target_cost = total_potential_damage * (cost_pct / 100.0)
    min_target = total * 0.005 # 0.5% safety clip
    
    left = 0
    right = 255
    clipped_black = 0
    clipped_white = 0
    clipped_total = 0
    total_cost = 0
    
    while left < 255 and clipped_black < min_target:
        clipped_black += hist[left]
        clipped_total += hist[left]
        left += 1
    while right > left and clipped_white < min_target:
        clipped_white += hist[right]
        clipped_total += hist[right]
        right -= 1

    while left < right and total_cost < target_cost and clipped_total < target_area:
        costL = hist[left] * abs(left - avg)
        costR = hist[right] * abs(right - avg)
        
        if costL < costR:
            total_cost += costL
            clipped_total += hist[left]
            left += 1
        else:
            total_cost += costR
            clipped_total += hist[right]
            right -= 1
        
    scale = 255.0 / (right - left if right > left else 1)
    data = data.astype(np.float32)
    data = np.clip((data - left) * scale, 0, 255)
    return data.astype(np.uint8)

def apply_fs(data, strength=1.0):
    """1-bit Floyd-Steinberg Dithering with serpentine scan."""
    h, w = data.shape
    out = data.astype(np.float32)
    
    for y in range(h):
        ltr = (y % 2 == 0)
        rng = range(w) if ltr else range(w - 1, -1, -1)
        for x in rng:
            old_val = out[y, x]
            new_val = 0 if old_val < 128 else 255
            err = (old_val - new_val) * strength
            out[y, x] = new_val
            if ltr:
                if x + 1 < w: out[y, x + 1] += err * 7 / 16
                if y + 1 < h:
                    if x - 1 >= 0: out[y + 1, x - 1] += err * 3 / 16
                    out[y + 1, x] += err * 5 / 16
                    if x + 1 < w: out[y + 1, x + 1] += err * 1 / 16
            else:
                if x - 1 >= 0: out[y, x - 1] += err * 7 / 16
                if y + 1 < h:
                    if x + 1 < w: out[y + 1, x + 1] += err * 3 / 16
                    out[y + 1, x] += err * 5 / 16
                    if x - 1 >= 0: out[y + 1, x - 1] += err * 1 / 16
    return np.clip(out, 0, 255).astype(np.uint8)

def apply_4g_fs(data, strength=1.0):
    """4-level Floyd-Steinberg Dithering (0, 85, 170, 255)."""
    h, w = data.shape
    out = data.astype(np.float32)
    
    for y in range(h):
        ltr = (y % 2 == 0)
        rng = range(w) if ltr else range(w - 1, -1, -1)
        for x in rng:
            old_val = out[y, x]
            new_val = np.round(old_val / 85.0) * 85.0
            err = (old_val - new_val) * strength
            out[y, x] = new_val
            if ltr:
                if x + 1 < w: out[y, x + 1] += err * 7 / 16
                if y + 1 < h:
                    if x - 1 >= 0: out[y + 1, x - 1] += err * 3 / 16
                    out[y + 1, x] += err * 5 / 16
                    if x + 1 < w: out[y + 1, x + 1] += err * 1 / 16
            else:
                if x - 1 >= 0: out[y, x - 1] += err * 7 / 16
                if y + 1 < h:
                    if x + 1 < w: out[y + 1, x + 1] += err * 3 / 16
                    out[y + 1, x] += err * 5 / 16
                    if x - 1 >= 0: out[y + 1, x - 1] += err * 1 / 16
    return np.clip(out, 0, 255).astype(np.uint8)

def load_global_font():
    """Load TTF font for text overlay."""
    font_paths = ["/app/data/ntailu.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    for path in font_paths:
        try:
            return ImageFont.truetype(path, 24)
        except (IOError, OSError):
            continue
    return ImageFont.load_default()

cached_font = load_global_font()

def overlay_title(img, title):
    """Overlay title on the bottom of the image with outline."""
    global cached_font
    if not title: return img
    
    draw = ImageDraw.Draw(img)
    w, h = img.size
    
    try:
        ascent, descent = cached_font.getmetrics()
        actual_height = ascent + descent
    except AttributeError:
        actual_height = 12

    area_h = max(34, actual_height + 4)
    
    def get_text_width(text):
        bbox = draw.textbbox((0, 0), text, font=cached_font)
        return bbox[2] - bbox[0]
    
    text_w = get_text_width(title)
    if text_w > w - 20:
        avg_char_w = text_w / len(title)
        max_chars = int((w - 40) / avg_char_w)
        title = title[:max_chars] 
        while get_text_width(title + "...") > w - 20 and len(title) > 0:
            title = title[:-1]
        title += "..."
        text_w = get_text_width(title)

    x = (w - text_w) // 2
    bbox = draw.textbbox((0, 0), title, font=cached_font)
    text_h = bbox[3] - bbox[1]
    y = h - area_h + (area_h - text_h) // 2 - 2
    
    for dx, dy in [(-1,-1), (-1,0), (-1,1), (0,-1), (0,1), (1,-1), (1,0), (1,1)]:
        draw.text((x + dx, y + dy), title, font=cached_font, fill=255)
    
    draw.text((x, y), title, font=cached_font, fill=0)
    return img

# --- Pipeline Function ---

def process_image_pipeline(img_ori, target_size, resize_method="padding", padding_color="white", 
                           gamma=1.0, sharpen=0.0, dither_strength=1.0, title=None, 
                           bit_depth=1, clip_pct=22, cost_pct=6):
    """
    Main pipeline: Processes an image using explicit technical parameters.
    This is a pure execution layer; all decisions are made by ai_optimizer.py.
    """
    tw, th = target_size
    
    # 1. Resize & Preparation
    if resize_method == "stretch":
        img = img_ori.resize((tw, th), Image.Resampling.LANCZOS)
    elif resize_method == "padding":
        img = img_ori.copy()
        img.thumbnail((tw, th), Image.Resampling.LANCZOS)
        
        bg_color = 255 if padding_color == "white" else 0
        new_img = Image.new("L", (tw, th), bg_color)
        offset = ((tw - img.width) // 2, (th - img.height) // 2)
        new_img.paste(img.convert("L"), offset)
        img = new_img
    else: # Default to crop
        img = fit_resize(img_ori, target_size)
    
    # 2. Enhancement
    if sharpen > 0:
        img = sharpen_image(img, sharpen)
        
    if img.mode != "L":
        img = img.convert("L")
    data = np.array(img).astype(np.float32)
    
    # 3. Grayscale Processing
    if gamma != 1.0:
        data = 255.0 * np.power(data / 255.0, 1.0 / gamma)
    
    data = apply_ac(data.astype(np.uint8), clip_pct, cost_pct)
    
    # 4. Dithering & Quantization
    if bit_depth == 1:
        data = apply_fs(data, strength=dither_strength)
        out_img = Image.fromarray(data).convert("1")
    else:
        data = apply_4g_fs(data, strength=dither_strength)
        out_img = Image.fromarray(data).convert("L")
        
    # 5. Text Overlay
    if title:
        out_img = out_img.convert("L")
        out_img = overlay_title(out_img, title)
        if bit_depth == 1:
            out_img = out_img.convert("1")
            
    return out_img

def save_as_png(img, path, bit_depth=1):
    """Save image as optimized 1-bit or 2-bit (4-color) indexed PNG."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
        
    if bit_depth == 1:
        img.convert("1").save(path, format="PNG", optimize=True)
    elif bit_depth == 2:
        img = img.convert("L")
        data = np.array(img)
        indices = (np.round(data / 85.0)).astype(np.uint8)
        palette_img = Image.fromarray(indices, mode='P')
        palette = [0,0,0, 85,85,85, 170,170,170, 255,255,255] + [0]*(256*3 - 12)
        palette_img.putpalette(palette)
        palette_img.save(path, format="PNG", bits=2, optimize=True)
    else:
        img.save(path, format="PNG", optimize=True)
