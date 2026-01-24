import requests
from PIL import Image
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

def apply_ac(data, clip_pct=30):
    """Auto-Contrast logic ported from JS applyAC."""
    h, w = data.shape
    hist, _ = np.histogram(data, bins=256, range=(0, 256))
    
    total = w * h
    target = total * (clip_pct / 100.0)
    min_t = total * 0.005
    
    l, r = 0, 255
    cb, cw, ct = 0, 0, 0
    rb, rw = total, total
    
    while l < r and ct < target:
        if rw >= rb:
            cw += hist[r]
            rw -= hist[r]
            ct += hist[r]
            r -= 1
        else:
            cb += hist[l]
            rb -= hist[l]
            ct += hist[l]
            l += 1
            
    while l < r and cb < min_t:
        cb += hist[l]
        ct += hist[l]
        l += 1
    while l < r and cw < min_t:
        cw += hist[r]
        ct += hist[r]
        r -= 1
        
    sc = 255.0 / (r - l if r > l else 1)
    
    # Apply contrast
    data = data.astype(np.float32)
    data = np.clip((data - l) * sc, 0, 255)
    return data.astype(np.uint8)

def apply_tp(data, layers=32, user_str=0.0):
    """Tone-Preserving adjustment logic ported from JS applyTP."""
    if layers <= 1:
        return data
        
    # Get values between 0 and 255 (exclusive)
    vals = data[(data > 0) & (data < 255)]
    if len(vals) == 0:
        return data
        
    vals = np.sort(vals)
    thres = []
    for i in range(1, layers):
        idx = int(len(vals) * i / layers)
        thres.append(vals[idx])
        
    step = 253.0 / (layers - 1)
    
    # We'll do this pixel by pixel for now to match the JS logic exactly
    # although a vectorized version would be faster.
    h, w = data.shape
    out = data.astype(np.float32)
    
    for y in range(h):
        for x in range(w):
            v = out[y, x]
            if v == 0 or v == 255:
                continue
            
            # Find threshold index
            idx = -1
            for i, t in enumerate(thres):
                if v < t:
                    idx = i
                    break
            
            if idx == -1:
                idx = layers - 1
                
            target = 1 + idx * step
            str_val = (0.2 + 0.8 * (abs(v - 128.0) / 128.0)) * user_str
            out[y, x] = np.clip(v + str_val * (target - v), 0, 255)
            
    return out.astype(np.uint8)

def apply_fs(data):
    """Floyd-Steinberg Dithering with serpentine scan logic ported from JS applyFS."""
    h, w = data.shape
    out = data.astype(np.float32)
    
    for y in range(h):
        ltr = (y % 2 == 0)
        x_range = range(w) if ltr else range(w - 1, -1, -1)
        
        for x in x_range:
            old_val = out[y, x]
            new_val = 0 if old_val < 128 else 255
            err = old_val - new_val
            out[y, x] = new_val
            
            def add_err(nx, ny, factor):
                if 0 <= nx < w and 0 <= ny < h:
                    out[ny, nx] = np.clip(out[ny, nx] + err * factor, 0, 255)
            
            if ltr:
                add_err(x + 1, y, 7/16)
                add_err(x - 1, y + 1, 3/16)
                add_err(x, y + 1, 5/16)
                add_err(x + 1, y + 1, 1/16)
            else:
                add_err(x - 1, y, 7/16)
                add_err(x + 1, y + 1, 3/16)
                add_err(x, y + 1, 5/16)
                add_err(x - 1, y + 1, 1/16)
                
    return out.astype(np.uint8)

def process_and_dither(img, target_size=(400, 300), clip_pct=18, layers=32, strength=0.0, resize_mode='fit', stretch_threshold=STRETCH_THRESHOLD):
    # Revert to only fit_resize as requested
    img = fit_resize(img, target_size, stretch_threshold=stretch_threshold)
    
    # 2. Convert to grayscale
    img = img.convert("L")
    data = np.array(img)
    
    # 3. Apply Auto-Contrast
    data = apply_ac(data, clip_pct)
    
    # 4. Apply Tone-Preserving adjustment
    data = apply_tp(data, layers, strength)
    
    # 5. Apply Floyd-Steinberg Dithering
    data = apply_fs(data)
    
    # 6. Convert back to Pillow image (1-bit mode)
    # FS result is 0 or 255, so we can convert directly to '1' mode
    dithered_img = Image.fromarray(data).convert("1")
    return dithered_img

def save_as_bmp(img, path):
    # Ensure directory exists if path contains one
    dir_name = os.path.dirname(path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
    # BMP format for epaper usually needs to be 1-bit or 8-bit
    img.save(path, format="BMP")

def process_image_url(url, output_path, target_size=(400, 300), resize_mode='fit', stretch_threshold=STRETCH_THRESHOLD):
    """Complete helper to download, process, and save an image."""
    img = download_image(url)
    dithered = process_and_dither(img, target_size, resize_mode=resize_mode, stretch_threshold=stretch_threshold)
    save_as_bmp(dithered, output_path)
    return output_path
