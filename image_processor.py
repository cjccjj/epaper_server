import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import io
import numpy as np
import os

# --- Configuration ---
OVERLAY_FONT_SIZE = 12  # Default font size for title overlay

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

def load_global_font(size=None):
    """Load TTF font for text overlay."""
    if size is None:
        size = OVERLAY_FONT_SIZE
        
    font_paths = [
        os.path.join(os.path.dirname(__file__), "static/DejaVuSans-Bold.ttf"),
        os.path.join(os.path.dirname(__file__), "static/ntailu.ttf"),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    ]
    for path in font_paths:
        try:
            return ImageFont.truetype(path, size)
        except (IOError, OSError):
            continue
    return ImageFont.load_default()

def overlay_title(img, title, font_size=None):
    """Overlay title on the bottom of the image with outline, max 2 lines."""
    if not title: return img
    
    if font_size is None:
        font_size = OVERLAY_FONT_SIZE
        
    # User preference: dejavu_bold_outline style
    # We use DejaVuSans-Bold and ensure it's centered with white outline.
    font = load_global_font(font_size)
    draw = ImageDraw.Draw(img)
    w, h = img.size
    
    # Estimate characters per line (approx 20-30 for 400px width at 12px)
    # We'll use a conservative estimate based on font_size
    chars_per_line = int((w - 20) / (font_size * 0.6)) 
    
    words = title.split()
    lines = []
    current_line = []
    
    for word in words:
        if len(" ".join(current_line + [word])) <= chars_per_line:
            current_line.append(word)
        else:
            if current_line:
                lines.append(" ".join(current_line))
            current_line = [word]
            if len(lines) >= 2: break
    
    if len(lines) < 2 and current_line:
        lines.append(" ".join(current_line))
    
    # Truncate if still too many lines or last line too long
    if len(lines) > 2:
        lines = lines[:2]
        
    if len(lines) == 2:
        if len(lines[1]) > chars_per_line - 3:
            lines[1] = lines[1][:chars_per_line-3] + "..."
    elif len(lines) == 1:
        if len(lines[0]) > chars_per_line - 3:
             # If it's just one line but it's super long, try to split it or truncate
             if len(lines[0]) > chars_per_line * 1.5:
                 split_point = chars_per_line
                 lines = [lines[0][:split_point], lines[0][split_point:split_point+chars_per_line-3] + "..."]
             else:
                 lines[0] = lines[0][:chars_per_line-3] + "..."

    # Draw lines from bottom up
    # y = h - 10 (margin) - line_height
    line_spacing = 2
    bbox = draw.textbbox((0, 0), "Ay", font=font)
    line_h = bbox[3] - bbox[1]
    
    # dejavu_bold_outline style uses a 1px stroke for the outline effect
    # We use DejaVuSans-Bold as the base font, which gives a clean bold look.
    main_stroke = 0
    
    for i, line in enumerate(reversed(lines)):
        text_bbox = draw.textbbox((0, 0), line, font=font, stroke_width=main_stroke)
        tw = text_bbox[2] - text_bbox[0]
        x = (w - tw) // 2
        y = h - 10 - (i + 1) * (line_h + line_spacing)
        
        # White outline (drawn manually for maximum compatibility/control)
        for dx, dy in [(-1,-1), (-1,0), (-1,1), (0,-1), (0,1), (1,-1), (1,0), (1,1)]:
            draw.text((x + dx, y + dy), line, font=font, fill=255, stroke_width=main_stroke)
        
        # Black main text
        draw.text((x, y), line, font=font, fill=0, stroke_width=main_stroke)
        
    return img

# --- Pipeline Function ---

def process_image_pipeline(img_ori, target_size, resize_method="padding", padding_color="white", 
                           gamma=1.0, sharpen=0.0, dither_strength=1.0, title=None, 
                           bit_depth=1, clip_pct=22, cost_pct=6, font_size=None):
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
        out_img = overlay_title(out_img, title, font_size=font_size)
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
