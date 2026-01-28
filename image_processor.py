import requests
from PIL import Image, ImageDraw, ImageFont
import io
import numpy as np
import os

# Configuration
STRETCH_THRESHOLD = 0.33  # If padding ratio is less than this, stretch image instead of padding

# --- Global Font Loading (Done once to save I/O) ---
def load_global_font():
    font_paths = ["/app/data/ntailu.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    for path in font_paths:
        try:
            # em-size 33 usually yields ~24-26px actual height
            return ImageFont.truetype(path, 33)
        except (IOError, OSError):
            continue
    print("WARNING: Could not load any TTF font, falling back to default.")
    return ImageFont.load_default()

# Initialize cached_font immediately
cached_font = load_global_font()


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
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        return Image.open(io.BytesIO(response.content))
    except Exception as e:
        print(f"Error downloading image: {e}")
        raise

def fit_resize(img, target_size=(400, 300), stretch_threshold=STRETCH_THRESHOLD):
    """
    Resize image to fit within target_size. 
    If the required padding is less than stretch_threshold, stretch the image instead.
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
    # Optimized: Vectorized calculation instead of loop
    indices = np.arange(256)
    total_potential_damage = np.sum(hist * np.abs(indices - avg))
        
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
    """Burkes Dithering logic ported from JS. Standard Error Diffusion."""
    h, w = data.shape
    out = data.astype(np.float32)
    
    # Note: Error diffusion is sequential and hard to vectorize purely.
    # This loop is the bottleneck but necessary for this algorithm.
    for y in range(h):
        for x in range(w):
            old_val = out[y, x]
            new_val = 0 if old_val < 128 else 255
            err = (old_val - new_val) / 32.0
            out[y, x] = new_val
            
            # Unrolled inner calls for slight speedup
            if x + 1 < w:
                out[y, x + 1] += err * 8
            if x + 2 < w:
                out[y, x + 2] += err * 4
            
            if y + 1 < h:
                if x - 2 >= 0:
                    out[y + 1, x - 2] += err * 2
                if x - 1 >= 0:
                    out[y + 1, x - 1] += err * 4
                
                out[y + 1, x] += err * 8
                
                if x + 1 < w:
                    out[y + 1, x + 1] += err * 4
                if x + 2 < w:
                    out[y + 1, x + 2] += err * 2
                
    # Clip final result to ensure valid image data
    return np.clip(out, 0, 255).astype(np.uint8)

def overlay_title(img, title):
    """Overlay title on the bottom of the image with outlined text for legibility."""
    # Use the globally loaded font
    global cached_font
    font = cached_font

    if not title:
        return img
    
    draw = ImageDraw.Draw(img)
    w, h = img.size
    
    # Calculate Line Height
    try:
        ascent, descent = font.getmetrics()
        actual_height = ascent + descent
    except AttributeError:
        # Fallback for default font which lacks getmetrics
        actual_height = 12

    # Bottom area height (ensure it fits glyphs + padding)
    area_h = max(34, actual_height + 4)
    
    # --- Optimized Text Measuring & Truncation ---
    def get_text_width(text):
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0]
    
    text_w = get_text_width(title)
    
    # Truncate if too long (Optimized "Smart Cut")
    if text_w > w - 20:
        # Estimate char width to avoid looping 1 char at a time
        avg_char_w = text_w / len(title)
        # Calculate roughly how many chars fit
        max_chars = int((w - 40) / avg_char_w)
        # Safety buffer
        title = title[:max_chars] 
        # Fine-tune trim if still slightly over
        while get_text_width(title + "...") > w - 20 and len(title) > 0:
            title = title[:-1]
        title += "..."
        text_w = get_text_width(title)

    # --- Positioning ---
    # Center horizontally
    x = (w - text_w) // 2
    # Center vertically within the bottom area
    # Note: textbbox top is often 0 or negative relative to anchor, 
    # but we position by top-left anchor naturally in PIL
    bbox = draw.textbbox((0, 0), title, font=font)
    text_h = bbox[3] - bbox[1]
    y = h - area_h + (area_h - text_h) // 2 - 2
    
    # --- Drawing ---
    # Draw black outline (8-way) for high contrast on dithered bg
    # 0 is black in '1' or 'L' mode
    outline_color = 0 
    text_color = 255
    
    for dx, dy in [(-1,-1), (-1,0), (-1,1), (0,-1), (0,1), (1,-1), (1,0), (1,1)]:
        draw.text((x + dx, y + dy), title, font=font, fill=outline_color)
    
    # Draw white text
    draw.text((x, y), title, font=font, fill=text_color)
    
    return img

def process_and_dither(img, target_size=(400, 300), clip_pct=22, cost_pct=6, resize_mode='fit', stretch_threshold=STRETCH_THRESHOLD, title=None):
    # 1. Resize
    img = fit_resize(img, target_size, stretch_threshold=stretch_threshold)
    
    # 2. Convert to grayscale
    img = img.convert("L")
    data = np.array(img).astype(np.float32)
    
    # Apply Gamma 2.2 Correction
    # Note: Applying before AC keeps linear consistency
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
    # BMP format for epaper usually needs to be 1-bit
    img.save(path, format="BMP")

def process_image_url(url, output_path, target_size=(400, 300), resize_mode='fit', stretch_threshold=STRETCH_THRESHOLD, title=None):
    """Complete helper to download, process, and save an image."""
    img = download_image(url)
    dithered = process_and_dither(img, target_size, resize_mode=resize_mode, stretch_threshold=stretch_threshold, title=title)
    save_as_bmp(dithered, output_path)
    return output_path