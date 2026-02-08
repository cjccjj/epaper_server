import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import io
import numpy as np
import os
import ai_stylist

# Configuration
STRETCH_THRESHOLD = 0.33  # If padding ratio is less than this, stretch image instead of padding

def sharpen_image(img, amount=1.0):
    """Apply Laplacian-style sharpening to a PIL image."""
    if amount <= 0:
        return img
    # Simple sharpening using PIL's built-in filter as a base, or custom kernel
    # For e-paper, a slightly more aggressive UnsharpMask often works well
    return img.filter(ImageFilter.UnsharpMask(radius=1, percent=int(amount * 100), threshold=3))

# --- Global Font Loading (Done once to save I/O) ---
def load_global_font():
    font_paths = ["/app/data/ntailu.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    for path in font_paths:
        try:
            # em-size 33 usually yields ~24-26px actual height
            return ImageFont.truetype(path, 24)
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
    headers = {"User-Agent": "linux:epaper-rss-reader:v1.0.0 (by /u/cj)"}
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
    outline_color = 255 
    text_color = 0
    
    for dx, dy in [(-1,-1), (-1,0), (-1,1), (0,-1), (0,1), (1,-1), (1,0), (1,1)]:
        draw.text((x + dx, y + dy), title, font=font, fill=outline_color)
    
    # Draw white text
    draw.text((x, y), title, font=font, fill=text_color)
    
    return img

def apply_fs(data, strength=1.0):
    """1-bit Floyd-Steinberg Dithering with serpentine scan and strength control."""
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
            
            # Error distribution
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
    """4-level Floyd-Steinberg Dithering (0, 85, 170, 255) with strength control."""
    h, w = data.shape
    out = data.astype(np.float32)
    
    for y in range(h):
        # Serpentine scan for better quality
        ltr = (y % 2 == 0)
        rng = range(w) if ltr else range(w - 1, -1, -1)
        
        for x in rng:
            old_val = out[y, x]
            # Quantize to 0, 85, 170, 255
            new_val = np.round(old_val / 85.0) * 85.0
            err = (old_val - new_val) * strength
            out[y, x] = new_val
            
            # Error distribution
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

def save_as_png(img, path, bit_depth=1):
    """Save image as indexed PNG with specific bit depth (1 or 2)."""
    dir_name = os.path.dirname(path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
        
    if bit_depth == 1:
        # Pillow's '1' mode is already 1-bit indexed
        img = img.convert("1")
        img.save(path, format="PNG", optimize=True)
    elif bit_depth == 2:
        # Pillow doesn't easily save 2-bit indexed PNGs directly through .save()
        # It usually saves 8-bit indexed. To get true 2-bit, we need more control.
        # However, for most epaper clients, an 8-bit indexed PNG with 4 colors
        # is also very small and often easier to decode.
        # But the user specifically asked for "correctly handle our 1 and 2 bit raw png".
        
        # Let's use 'P' mode with a 4-color palette
        img = img.convert("L")
        data = np.array(img)
        # Map 0, 85, 170, 255 to indices 0, 1, 2, 3
        indices = (np.round(data / 85.0)).astype(np.uint8)
        
        palette_img = Image.fromarray(indices, mode='P')
        # Set palette: [0,0,0, 85,85,85, 170,170,170, 255,255,255]
        palette = [0,0,0, 85,85,85, 170,170,170, 255,255,255] + [0]*(256*3 - 12)
        palette_img.putpalette(palette)
        
        # PNG 2-bit (bit_depth=2) is a valid IHDR parameter.
        # Pillow's PNG encoder supports bits=2 for 'P' mode if we provide it.
        palette_img.save(path, format="PNG", bits=2, optimize=True)
    else:
        img.save(path, format="PNG", optimize=True)

def process_and_dither(img, target_size=(400, 300), clip_pct=22, cost_pct=6, resize_mode='fit', 
                       stretch_threshold=STRETCH_THRESHOLD, title=None, bit_depth=1, 
                       apply_gamma=False, dither_mode='burkes', dither_strength=1.0,
                       sharpen_amount=0.0, auto_optimize=False):
    # 1. Resize
    img = fit_resize(img, target_size, stretch_threshold=stretch_threshold)
    
    ai_labels = None
    # 2. AI Optimization (if requested)
    if auto_optimize:
        style = ai_stylist.analyze_image(img)
        ai_labels = style.model_dump() if style else None
        print(f"AI Optimization labels: {ai_labels}")
        
        # Mapping labels to parameters
        if style.has_text_overlay:
            sharpen_amount = 1.0
        else:
            sharpen_amount = 0.2
            
        if style.gradient_complexity == "low":
            dither_strength = 0.4
        else:
            dither_strength = 1.0
            
        if style.content_type == "comic_illustration":
            apply_gamma = True # Force gamma for comics
            
    # 3. Sharpening
    if sharpen_amount > 0:
        img = sharpen_image(img, sharpen_amount)

    # 4. Convert to grayscale
    img = img.convert("L")
    data = np.array(img).astype(np.float32)
    
    # Apply Gamma 2.2 Correction if requested
    if apply_gamma:
        data = 255.0 * np.power(data / 255.0, 1.0 / 2.2)
    
    data = data.astype(np.uint8)
    
    # 5. Apply Weighted Approaching Auto-Contrast
    data = apply_ac(data, clip_pct, cost_pct)
    
    # 6. Apply Dithering
    if bit_depth == 1:
        if dither_mode == 'fs':
            data = apply_fs(data, strength=dither_strength)
        else:
            data = apply_burkes(data)
        out_img = Image.fromarray(data).convert("1")
    else:
        # 2-bit (4G)
        # Always use 4G FS as planned
        data = apply_4g_fs(data, strength=dither_strength)
        out_img = Image.fromarray(data).convert("L")
    
    # 7. Overlay title if provided
    if title:
        out_img = overlay_title(out_img, title)
        
    return out_img, ai_labels

def process_image_url(url, output_path, target_size=(400, 300), resize_mode='fit', 
                      stretch_threshold=STRETCH_THRESHOLD, title=None, bit_depth=1,
                      clip_pct=22, cost_pct=6, apply_gamma=False, dither_mode='burkes',
                      dither_strength=1.0, sharpen_amount=0.0, auto_optimize=False):
    """Complete helper to download, process, and save an image."""
    img = download_image(url)
    processed, ai_labels = process_and_dither(img, target_size, clip_pct=clip_pct, cost_pct=cost_pct, 
                                   resize_mode=resize_mode, stretch_threshold=stretch_threshold, 
                                   title=title, bit_depth=bit_depth, apply_gamma=apply_gamma, 
                                   dither_mode=dither_mode, dither_strength=dither_strength,
                                   sharpen_amount=sharpen_amount, auto_optimize=auto_optimize)
    save_as_png(processed, output_path, bit_depth=bit_depth)
    return output_path, ai_labels