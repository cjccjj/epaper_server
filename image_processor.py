import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import io
import numpy as np
import os
import ai_stylist

# Configuration
STRETCH_THRESHOLD = 0.33  # If padding ratio is less than this, stretch image instead of padding

def check_ratio_fit(img, target_size=(400, 300), threshold=STRETCH_THRESHOLD):
    """
    Step 3: Check if image resolution fits within STRETCH_THRESHOLD.
    Returns True if it fits, False otherwise.
    """
    tw, th = target_size
    iw, ih = img.size
    
    target_ratio = tw / th
    img_ratio = iw / ih
    
    # Calculate how much we'd need to stretch/crop
    ratio_diff = abs(img_ratio - target_ratio) / target_ratio
    
    # If the difference is within threshold, it's a fit
    return ratio_diff <= threshold

def download_image_simple(url):
    """Step 2: Download image as img_ori"""
    headers = {"User-Agent": "linux:epaper-rss-reader:v1.0.0 (by /u/cj)"}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        return Image.open(io.BytesIO(response.content))
    except Exception as e:
        print(f"Error downloading image: {e}")
        return None

def process_with_ai_strategy(img_ori, target_size, ai_analysis, strategy, title=None, bit_depth=1, 
                             clip_pct=22, cost_pct=6):
    """
    Step 6 & 7: Process the image according to AI analysis and strategy parameters.
    Note: Process from img_ori.
    """
    # 1. Decide resize method from strategy
    # Literals: "crop", "padding", "stretch"
    resize_method = strategy.get("resize_method", "crop")
    max_stretch = strategy.get("max_stretch", 0.0)
    tw, th = target_size
    
    if resize_method == "stretch":
        # Check if we should use smart stretch (within limits) or fill
        iw, ih = img_ori.size
        target_ratio = tw / th
        img_ratio = iw / ih
        ratio_diff = abs(img_ratio - target_ratio) / target_ratio
        
        if ratio_diff <= max_stretch:
            # Within stretch tolerance: pure stretch
            img = img_ori.resize((tw, th), Image.Resampling.LANCZOS)
        else:
            # Beyond stretch tolerance: fill (crop-to-fill)
            img = fit_resize(img_ori, target_size)
            
    elif resize_method == "padding":
        # Padding fit: resize to fit inside target and pad with white/black
        padding_color_pref = strategy.get("padding_color", "auto")
        
        img = img_ori.copy()
        img.thumbnail((tw, th), Image.Resampling.LANCZOS)
        
        # Determine background color
        bg_color = 255 # Default white
        if padding_color_pref == "black":
            bg_color = 0
        elif padding_color_pref == "auto":
            # Simple auto: if image is dark, use black; if light, use white
            # We use the thumbnail to get a quick average
            temp_l = img.convert("L")
            avg_pixel = np.mean(np.array(temp_l))
            bg_color = 0 if avg_pixel < 128 else 255
            
        new_img = Image.new("L", (tw, th), bg_color)
        offset = ((tw - img.width) // 2, (th - img.height) // 2)
        new_img.paste(img.convert("L"), offset)
        img = new_img
    else:
        # Default to crop (crop-to-fill)
        img = fit_resize(img_ori, target_size)
    
    # 2. Apply strategy parameters
    gamma_val = strategy.get("gamma", 1.0)
    sharpen_amount = strategy.get("sharpen", 0.0)
    dither_strength = strategy.get("dither_strength", 1.0)
    
    # 3. Sharpening
    if sharpen_amount > 0:
        img = sharpen_image(img, sharpen_amount)
        
    # 4. Convert to grayscale (if not already done by padding)
    if img.mode != "L":
        img = img.convert("L")
    data = np.array(img).astype(np.float32)
    
    # 5. Gamma Correction
    if gamma_val != 1.0:
        # Clamp gamma between 0.7 and 1.3 per AI design.md
        gamma_val = max(0.7, min(1.3, gamma_val))
        data = 255.0 * np.power(data / 255.0, 1.0 / gamma_val)
    
    data = data.astype(np.uint8)
    
    # 6. Auto-Contrast
    data = apply_ac(data, clip_pct, cost_pct)
    
    # 7. Dithering
    if bit_depth == 1:
        data = apply_fs(data, strength=dither_strength)
        out_img = Image.fromarray(data).convert("1")
    else:
        data = apply_4g_fs(data, strength=dither_strength)
        out_img = Image.fromarray(data).convert("L")
        
    # 8. Text Overlay (Step 7)
    # Use AI's analysis for text_density and show_titles preference
    # If text_density is high, we might want to skip title overlay to avoid clutter
    text_density = ai_analysis.get("text_density", "none")
    show_titles_config = ai_analysis.get("show_titles", True)
    
    if title and show_titles_config and text_density != "high":
        out_img = overlay_title(out_img, title)
        
    # Build debug info string
    debug_info = {
        "ai": ai_analysis,
        "process": strategy
    }
        
    return out_img, debug_info

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
    Resize and crop image to fill target_size (Crop-to-fill).
    This matches the frontend logic and ensures we always have an image.
    """
    tw, th = target_size
    iw, ih = img.size
    
    # Calculate scale factor for filling (crop-to-fill)
    scale = max(tw / iw, th / ih)
    nw, nh = int(iw * scale), int(ih * scale)
    
    # Calculate offsets for centering the crop
    ox = (tw - nw) // 2
    oy = (th - nh) // 2
    
    # Resize and then crop (or paste onto a target canvas)
    img = img.resize((nw, nh), Image.Resampling.LANCZOS)
    
    # Create target canvas and paste the resized image centered
    target = Image.new("RGB", (tw, th), (255, 255, 255))
    target.paste(img, (ox, oy))
    
    return target

def apply_ac(data, clip_pct=22, cost_pct=6):
    """Weighted Approaching Auto-Contrast logic ported from JS (Fixed version)."""
    h, w = data.shape
    hist, _ = np.histogram(data, bins=256, range=(0, 256))
    
    total = w * h
    avg = np.mean(data)
    
    # Calculate potential damage
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
    
    # 1. Safety clips first
    while left < 255 and clipped_black < min_target:
        clipped_black += hist[left]
        clipped_total += hist[left]
        left += 1
    while right > left and clipped_white < min_target:
        clipped_white += hist[right]
        clipped_total += hist[right]
        right -= 1

    # 2. Weighted approaching
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
    
    # Apply contrast
    data = data.astype(np.float32)
    data = np.clip((data - left) * scale, 0, 255)
    return data.astype(np.uint8)

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
        try:
            style = ai_stylist.analyze_image(img)
            ai_labels = style.model_dump() if style else None
        except Exception as e:
            print(f"Error in Gallery AI analysis: {e}")
            # Fallback to a safe default object if AI fails
            ai_labels = {
                "decision": "use",
                "image_style": "photography",
                "post_purpose": "others",
                "resize_strategy": "pad_white",
                "gamma": 1.0,
                "sharpen": 0.5,
                "dither": 50
            }
            # Create a mock style object for the rest of the logic
            from ai_stylist import ImageRenderIntent
            style = ImageRenderIntent(**ai_labels)
        
        print(f"AI Optimization labels: {ai_labels}")
        
        # Mapping labels to parameters
        # 1. Sharpening: aggressive for text, moderate for comics (to keep lines clean), low for photos
        if style.has_text_overlay or style.content_type == "text_heavy":
            sharpen_amount = 1.0
        elif style.content_type == "comic_illustration":
            sharpen_amount = 0.5
        else:
            sharpen_amount = 0.2
            
        # 2. Dithering: low for flat colors (comics), high for photos
        if style.gradient_complexity == "low":
            dither_strength = 0.4
        else:
            dither_strength = 1.0
            
        # 3. Gamma: 
        # For comics/illustrations, we often want more punchy contrast (higher gamma to darken mids or keep them clean)
        # For photos, 2.2 is standard.
        if style.content_type == "comic_illustration":
            apply_gamma = 2.2 # Use 2.2 gamma
        else:
            apply_gamma = 1.0 # Use linear/no-gamma (default)

        # Record applied settings in labels for UI transparency
        if ai_labels:
            ai_labels["applied"] = {
                "sharpen": f"{int(sharpen_amount*100)}%",
                "dither": f"{int(dither_strength*100)}%",
                "gamma": f"{apply_gamma}" if apply_gamma > 1.0 else "1.0"
            }
            
    # 3. Sharpening
    if sharpen_amount > 0:
        img = sharpen_image(img, sharpen_amount)

    # 4. Convert to grayscale
    img = img.convert("L")
    data = np.array(img).astype(np.float32)
    
    # Apply Gamma Correction if requested
    # apply_gamma can be a boolean (True=2.2, False=1.0) or a float
    gamma_val = 1.0
    if isinstance(apply_gamma, bool):
        gamma_val = 2.2 if apply_gamma else 1.0
    else:
        try:
            gamma_val = float(apply_gamma)
        except:
            gamma_val = 1.0
            
    if gamma_val > 1.0:
        data = 255.0 * np.power(data / 255.0, 1.0 / gamma_val)
    
    data = data.astype(np.uint8)
    
    # 5. Apply Weighted Approaching Auto-Contrast
    data = apply_ac(data, clip_pct, cost_pct)
    
    # 6. Apply Dithering
    if bit_depth == 1:
        # 1-bit: Use FS (Burkes is removed as requested)
        data = apply_fs(data, strength=dither_strength)
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
                      clip_pct=22, cost_pct=6, apply_gamma=False, dither_mode='fs',
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