from fastapi import FastAPI, Header, HTTPException, Depends, Body, File, UploadFile, BackgroundTasks, Request, Response
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from contextlib import asynccontextmanager
import database
import uuid
import datetime
import pytz
import os
import shutil
import json
import asyncio
import image_processor
import ai_optimizer
import rss_fetcher
import rss_general_fetcher
import random
import io
from PIL import Image
from typing import Optional, List

# Configuration
BITMAP_DIR = "bitmaps"
DATA_DIR = "data"
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "z0000l")
SESSION_COOKIE_NAME = "admin_session"
SESSION_EXPIRY_HOURS = 24
REDDIT_CACHE_FILE = os.path.join(DATA_DIR, "reddit_cache.json")
os.makedirs(BITMAP_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

# Reddit User Agent
REDDIT_USER_AGENT = "linux:epaper-server:v1.0.0 (by /u/cj)"

# --- Reddit Cache Management ---
# Global dictionary to store per-device caches: {mac: cache_dict}
reddit_device_caches = {}

def get_device_cache_path(mac):
    clean_mac = mac.replace(":", "").lower()
    return os.path.join(DATA_DIR, f"reddit_cache_{clean_mac}.json")

def load_device_reddit_cache(mac):
    path = get_device_cache_path(mac)
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                cache = json.load(f)
                if cache.get("last_update"):
                    cache["last_update"] = datetime.datetime.fromisoformat(cache["last_update"])
                return cache
        except Exception as e:
            print(f"Error loading reddit cache for {mac}: {e}")
    
    return {
        "posts": [],
        "last_update": None,
        "config": {"subreddit": "aww"}
    }

def save_device_reddit_cache(mac, cache):
    path = get_device_cache_path(mac)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    
    # Create a copy for JSON serialization
    serializable = cache.copy()
    if serializable.get("last_update"):
        serializable["last_update"] = serializable["last_update"].isoformat()
    
    try:
        with open(path, "w") as f:
            json.dump(serializable, f)
    except Exception as e:
        print(f"Error saving reddit cache for {mac}: {e}")

# --- RSS Cache Management ---
def get_rss_cache_path(mac):
    clean_mac = mac.replace(":", "").lower()
    return os.path.join(DATA_DIR, f"rss_cache_{clean_mac}.json")

def load_device_rss_cache(mac):
    path = get_rss_cache_path(mac)
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                cache = json.load(f)
                return cache
        except Exception as e:
            print(f"Error loading rss cache for {mac}: {e}")
    
    return {
        "posts": [],
        "status": "idle",
        "progress": ""
    }

def save_device_rss_cache(mac, cache):
    path = get_rss_cache_path(mac)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open(path, "w") as f:
            json.dump(cache, f)
    except Exception as e:
        print(f"Error saving rss cache for {mac}: {e}")

# --- App Lifecycle ---
# Initialize database
database.init_db()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic
    yield
    # Shutdown logic

app = FastAPI(lifespan=lifespan)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# --- Authentication Middleware & Logic ---

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    # Paths that don't require authentication
    open_paths = ["/api/setup", "/api/display", "/api/bitmap", "/api/log", "/login", "/static"]
    
    # Check if path starts with any open paths
    is_open = any(request.url.path.startswith(p) for p in open_paths)
    
    # Root redirect
    if request.url.path == "/":
        return RedirectResponse(url="/admin")
        
    if not is_open:
        # Check session cookie
        session_id = request.cookies.get(SESSION_COOKIE_NAME)
        if not session_id:
            return RedirectResponse(url="/login")
        
        # In a real app we'd verify session_id against a DB/store.
        # For this "simple password" requirement, we just check if it exists.
        # The login endpoint sets this.
            
    response = await call_next(request)
    return response

@app.get("/login", response_class=HTMLResponse)
def login_page():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Login - E-Paper Admin</title>
        <style>
            body { font-family: sans-serif; background: #0f172a; color: white; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }
            .login-box { background: #1e293b; padding: 2rem; border-radius: 8px; border: 1px solid #334155; width: 300px; }
            input { width: 100%; padding: 8px; margin: 10px 0; background: #0f172a; border: 1px solid #334155; color: white; box-sizing: border-box; }
            button { width: 100%; padding: 10px; background: #3b82f6; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: bold; }
            .error { color: #ef4444; font-size: 12px; margin-bottom: 10px; }
        </style>
    </head>
    <body>
        <div class="login-box">
            <h2>Admin Login</h2>
            <form action="/login" method="post">
                <input type="password" name="password" placeholder="Password" required autofocus>
                <button type="submit">Login</button>
            </form>
            <div id="error-msg" class="error"></div>
        </div>
        <script>
            const urlParams = new URLSearchParams(window.location.search);
            if (urlParams.has('error')) {
                document.getElementById('error-msg').textContent = 'Invalid password';
            }
        </script>
    </body>
    </html>
    """

@app.post("/login")
async def login(response: Response, password: str = Body(None), request: Request = None):
    # FastAPI Body doesn't work well with form-data by default unless using Form class
    # But we can grab it from request.form()
    form_data = await request.form()
    input_password = form_data.get("password")
    
    if input_password == ADMIN_PASSWORD:
        # Set session cookie for 24 hours
        session_id = str(uuid.uuid4())
        response = RedirectResponse(url="/admin", status_code=303)
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=session_id,
            max_age=SESSION_EXPIRY_HOURS * 3600,
            httponly=True,
            samesite="lax"
        )
        return response
    else:
        return RedirectResponse(url="/login?error=1", status_code=303)

async def refresh_device_reddit_cache(mac, db_session=None):
    """Fetch and dither images for a specific device using the rss_fetcher module."""
    if db_session is None:
        db = database.SessionLocal()
    else:
        db = db_session
        
    try:
        await rss_fetcher.refresh_device_reddit_cache(
            mac, 
            db, 
            BITMAP_DIR, 
            load_device_reddit_cache, 
            save_device_reddit_cache
        )
    finally:
        if db_session is None:
            db.close()


# Dependency to get the database session
def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- Device APIs ---

DEFAULT_REDDIT_CONFIG = {
    "subreddit": "aww", 
    "sort": "top", 
    "time": "day", 
    "bit_depth": 2,
    "width": 400,
    "height": 300,
    "apply_gamma": True,
    "clip_pct": 20,
    "cost_pct": 6,
    "dither_strength": 1.0,
    "sharpen_amount": 0.0,
    "auto_optimize": False,
    "ai_prompt": ai_optimizer.DEFAULT_SYSTEM_PROMPT
}

DEFAULT_RSS_CONFIG = {
    "url": "",
    "bit_depth": 2,
    "auto_optimize": False,
    "ai_prompt": ai_optimizer.DEFAULT_SYSTEM_PROMPT
}

@app.get("/api/setup")
def setup_device(id: str = Header(None), db: Session = Depends(get_db)):
    if not id:
        raise HTTPException(status_code=400, detail="ID header (MAC address) is required")
    
    device = db.query(database.Device).filter(database.Device.mac_address == id).first()
    
    if not device:
        api_key = str(uuid.uuid4()).replace("-", "")
        friendly_id = f"DEVICE_{id.replace(':', '')[-6:]}"
        device = database.Device(
            mac_address=id, 
            api_key=api_key, 
            friendly_id=friendly_id,
            reddit_config=DEFAULT_REDDIT_CONFIG
        )
        db.add(device)
        db.commit()
        db.refresh(device)
        message = "Device successfully registered"
    else:
        # Update old devices if they lack reddit_config fields
        if not device.reddit_config:
            device.reddit_config = DEFAULT_REDDIT_CONFIG
            db.commit()
        message = "Device already registered"

    return {"status": 200, "api_key": device.api_key, "friendly_id": device.friendly_id, "message": message}

@app.get("/api/display")
def get_display(
    id: str = Header(None), 
    access_token: Optional[str] = Header(None),
    battery_voltage: Optional[float] = Header(None, alias="Battery-Voltage"),
    fw_version: Optional[str] = Header(None, alias="FW-Version"),
    rssi: Optional[int] = Header(None, alias="RSSI"),
    refresh_rate: Optional[int] = Header(None, alias="Refresh-Rate"),
    db: Session = Depends(get_db)
):
    if not id:
        raise HTTPException(status_code=400, detail="ID header (MAC address) is required")

    device = None
    if access_token:
        device = db.query(database.Device).filter(database.Device.api_key == access_token).first()
    if not device:
        device = db.query(database.Device).filter(database.Device.mac_address == id).first()
        
    if not device and access_token:
        friendly_id = f"DEVICE_{id.replace(':', '')[-6:]}"
        device = database.Device(mac_address=id, api_key=access_token, friendly_id=friendly_id)
        db.add(device)
        db.commit()
        db.refresh(device)

    if not device:
        raise HTTPException(status_code=401, detail="Device not found")

    # Update device status (except last_update_time which we update only on successful response)
    device.battery_voltage = battery_voltage
    device.fw_version = fw_version
    device.rssi = rssi
    
    # Use device's refresh_rate or fallback to provided header or default 60
    current_refresh_rate = refresh_rate if refresh_rate else device.refresh_rate
    if not current_refresh_rate:
        current_refresh_rate = 60
        
    # Logic to select content based on active dish and display mode
    enabled_dishes = device.enabled_dishes or ["gallery"]
    display_mode = device.display_mode or "sequence"
    
    # Try up to len(enabled_dishes) to find a dish with valid content
    for _ in range(len(enabled_dishes)):
        # Pick the dish to use for this request
        current_dish = "gallery"
        if display_mode == "random" and enabled_dishes:
            current_dish = random.choice(enabled_dishes)
        elif enabled_dishes: # sequence
            dish_idx = device.last_dish_index % len(enabled_dishes)
            current_dish = enabled_dishes[dish_idx]
            device.last_dish_index = (dish_idx + 1) % len(enabled_dishes)

        filename = None
        
        if current_dish == "gallery":
            # Filter to only images that actually exist on disk
            images = sorted(device.images, key=lambda x: x.order)
            valid_images = [img for img in images if img.filename and os.path.exists(os.path.join(BITMAP_DIR, img.filename))]
            
            if valid_images:
                idx = device.current_image_index % len(valid_images)
                filename = valid_images[idx].filename
                device.current_image_index = (idx + 1) % len(valid_images)
                
        elif current_dish == "reddit":
            cache = load_device_reddit_cache(id)
            posts = cache.get("posts", [])
            # Filter to only posts that actually have files on disk
            valid_posts = [p for p in posts if p.get("filename") and os.path.exists(os.path.join(BITMAP_DIR, p["filename"]))]
            
            if valid_posts:
                idx = device.current_image_index % len(valid_posts)
                filename = valid_posts[idx].get("filename")
                device.current_image_index = (idx + 1) % len(valid_posts)
                
        elif current_dish == "rss":
            cache = load_device_rss_cache(id)
            posts = cache.get("posts", [])
            # Filter to only posts that actually have files on disk
            valid_posts = [p for p in posts if p.get("filename") and os.path.exists(os.path.join(BITMAP_DIR, p["filename"]))]
            
            if valid_posts:
                idx = device.current_image_index % len(valid_posts)
                filename = valid_posts[idx].get("filename")
                device.current_image_index = (idx + 1) % len(valid_posts)

        if filename:
            # Found a valid file, we're done
            break
        else:
            # If no content for this dish, sequence mode naturally moves to next dish on next call
            # But for this call, we continue the loop to try another enabled dish immediately
            if display_mode == "random":
                continue # Try another random dish
            else:
                # In sequence mode, we already advanced last_dish_index, so just loop to try next
                continue

    if not filename:
        raise HTTPException(status_code=404, detail="No valid content found in any enabled source")
        
    # Update contact time only after successful image selection
    now_utc = datetime.datetime.now(datetime.UTC)
    now = now_utc.replace(tzinfo=None)
    device.last_update_time = now
    device.next_expected_update = now + datetime.timedelta(seconds=current_refresh_rate)
    
    db.commit()

    # Add cache-busting path for CloudFront/CDNs
    # By putting the timestamp in the path, CloudFront will always see a unique URL
    # even if it is configured to ignore query strings.
    t_bust = int(now_utc.timestamp())
    image_url = f"/api/bitmap/{t_bust}/{filename}"

    return {
        "status": 0,
        "image_url": image_url,
        "filename": filename,
        "refresh_rate": current_refresh_rate,
        "reset_firmware": False,
        "update_firmware": False,
        "firmware_url": None,
        "special_function": None
    }

@app.get("/api/bitmap/{timestamp}/{filename}")
@app.get("/api/bitmap/{filename}")
def serve_bitmap(filename: str, timestamp: Optional[str] = None):
    path = os.path.join(BITMAP_DIR, filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Bitmap not found")
    return FileResponse(path)

@app.post("/api/log")
def log_event(id: str = Header(None), body: dict = Body(...), db: Session = Depends(get_db)):
    if not id: raise HTTPException(status_code=400, detail="ID required")
    new_log = database.DeviceLog(mac_address=id, message=body.get("message", "No message"), metadata_json=body.get("metadata", {}))
    db.add(new_log)
    db.commit()
    return {"status": 200, "message": "Log captured"}

# --- Admin APIs ---

@app.post("/admin/analyze_style")
async def analyze_style(file: UploadFile = File(...)):
    """Analyze image style using AI Optimizer (for manual Gallery processing)."""
    try:
        contents = await file.read()
        img = Image.open(io.BytesIO(contents))
        style = ai_optimizer.analyze_image(img)
        return style
    except Exception as e:
        return {"error": str(e)}

@app.get("/admin", response_class=HTMLResponse)
def admin_page():
    with open("static/admin.html", "r") as f:
        return f.read()

@app.get("/admin/devices")
def list_devices(db: Session = Depends(get_db)):
    devices = db.query(database.Device).all()
    result = []
    for d in devices:
        # Ensure reddit_config has all fields and a prompt
        config = d.reddit_config or DEFAULT_REDDIT_CONFIG.copy()
        needs_commit = False
        
        if not config.get("ai_prompt"):
            config["ai_prompt"] = ai_optimizer.DEFAULT_SYSTEM_PROMPT
            d.reddit_config = config
            needs_commit = True
        
        if needs_commit:
            db.commit()
            
        # Calculate current local time for the device
        device_time = "Unknown"
        try:
            tz = pytz.timezone(d.timezone or "UTC")
            device_time = datetime.datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
        except Exception as e:
            print(f"Error calculating time for TZ {d.timezone}: {e}")

        result.append({
            "mac_address": d.mac_address,
            "friendly_id": d.friendly_id,
            "battery_voltage": d.battery_voltage,
            "rssi": d.rssi,
            "refresh_rate": d.refresh_rate,
            "display_width": d.display_width,
            "display_height": d.display_height,
            "timezone": d.timezone,
            "device_time": device_time,
            "active_dish": d.active_dish,
            "enabled_dishes": d.enabled_dishes or ["gallery"],
            "display_mode": d.display_mode or "sequence",
            "reddit_config": config,
            "rss_config": d.rss_config or DEFAULT_RSS_CONFIG.copy(),
            "last_update_time": d.last_update_time.isoformat() if d.last_update_time else None,
            "images": [{"id": i.id, "filename": i.filename, "original_name": i.original_name} for i in d.images]
        })
    return result

@app.post("/admin/device/{mac}/settings")
def update_device_settings(mac: str, settings: dict = Body(...), db: Session = Depends(get_db)):
    device = db.query(database.Device).filter(database.Device.mac_address == mac).first()
    if not device: raise HTTPException(status_code=404, detail="Device not found")
    
    if "refresh_rate" in settings:
        device.refresh_rate = int(settings["refresh_rate"])
    if "display_width" in settings:
        device.display_width = int(settings["display_width"])
    if "display_height" in settings:
        device.display_height = int(settings["display_height"])
    if "timezone" in settings:
        device.timezone = settings["timezone"]
    if "active_dish" in settings:
        device.active_dish = settings["active_dish"]
    if "enabled_dishes" in settings:
        device.enabled_dishes = settings["enabled_dishes"]
    if "display_mode" in settings:
        device.display_mode = settings["display_mode"]
    if "reddit_config" in settings:
        device.reddit_config = settings["reddit_config"]
    if "rss_config" in settings:
        device.rss_config = settings["rss_config"]
    
    db.commit()
    return {"status": "success"}

@app.get("/admin/reddit/preview/{mac}")
def reddit_preview(mac: str, db: Session = Depends(get_db)):
    cache = load_device_reddit_cache(mac)
    
    now = datetime.datetime.now()
    try:
        import time
        server_tz = time.tzname[0] if time.daylight == 0 else time.tzname[1]
    except:
        server_tz = "Local"

    # Get device rate from database if available, or default to 3
    rate_hours = 3
    device = db.query(database.Device).filter(database.Device.mac_address == mac).first()
    
    return {
        "posts": cache["posts"],
        "status": cache.get("status", "idle"),
        "progress": cache.get("progress", ""),
        "last_update": cache["last_update"].isoformat() if cache["last_update"] else None,
        "last_update_formatted": cache["last_update"].strftime("%Y-%m-%d %H:%M:%S") if cache["last_update"] else "Never",
        "server_time": now.strftime("%Y-%m-%d %H:%M:%S"),
        "server_tz": server_tz,
        "rate_hours": rate_hours,
        "config": cache.get("config", {})
    }

@app.post("/admin/reddit/fetch_now/{mac}")
async def fetch_reddit_now(mac: str, db: Session = Depends(get_db)):
    """Manually trigger a Reddit cache refresh for a specific device."""
    device = db.query(database.Device).filter(database.Device.mac_address == mac).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
        
    print(f"DEBUG: Manual fetch triggered for {mac}")
    
    # Start the fetch in the background
    asyncio.create_task(refresh_device_reddit_cache(mac))
    
    return {"status": "fetch_started"}

@app.get("/admin/rss/preview/{mac}")
def rss_preview(mac: str):
    cache = load_device_rss_cache(mac)
    return {
        "posts": cache.get("posts", []),
        "status": cache.get("status", "idle"),
        "progress": cache.get("progress", ""),
        "last_refresh": cache.get("last_refresh")
    }

@app.post("/admin/rss/fetch_now/{mac}")
async def fetch_rss_now_device(mac: str, db: Session = Depends(get_db)):
    """Trigger a full RSS refresh (fetching images and processing) for a device."""
    device = db.query(database.Device).filter(database.Device.mac_address == mac).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
        
    asyncio.create_task(rss_general_fetcher.refresh_device_rss_cache(
        mac, db, BITMAP_DIR, load_device_rss_cache, save_device_rss_cache
    ))
    return {"status": "fetch_started"}

@app.post("/admin/rss/fetch_now")
async def fetch_rss_now_general(data: dict = Body(...)):
    """Fetch and parse a general RSS feed (preview only)."""
    url = data.get("url")
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")
    
    items = await rss_general_fetcher.fetch_general_rss(url)
    return {"status": "success", "items": items}

@app.post("/admin/upload/{mac}")
async def upload_image(mac: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    device = db.query(database.Device).filter(database.Device.mac_address == mac).first()
    if not device: raise HTTPException(status_code=404, detail="Device not found")

    contents = await file.read()
    
    # Generate structured filename
    # source1=gallery, source2=gallery, counter=current image count
    filename = image_processor.generate_processed_filename(
        "gallery", "gallery", mac, len(device.images), contents
    )
    file_path = os.path.join(BITMAP_DIR, filename)

    with open(file_path, "wb") as buffer:
        buffer.write(contents)

    new_img = database.DeviceImage(
        mac_address=mac,
        filename=filename,
        original_name=file.filename,
        order=len(device.images)
    )
    db.add(new_img)
    db.commit()
    return {"status": "success", "filename": filename}

@app.delete("/admin/image/{image_id}")
def delete_image(image_id: int, db: Session = Depends(get_db)):
    img = db.query(database.DeviceImage).filter(database.DeviceImage.id == image_id).first()
    if img:
        path = os.path.join(BITMAP_DIR, img.filename)
        if os.path.exists(path):
            os.remove(path)
        db.delete(img)
        db.commit()
    return {"status": "success"}

@app.delete("/admin/reddit/cache/{mac}")
def clear_reddit_cache(mac: str):
    """Clear Reddit cache and delete all associated images."""
    clean_mac = re.sub(r'[^a-zA-Z0-9]', '', mac).lower()
    
    # Delete files by pattern: reddit_source2_mac_counter_hash.png
    for f in os.listdir(BITMAP_DIR):
        if f.startswith("reddit_") and f"_{clean_mac}_" in f:
            try: os.remove(os.path.join(BITMAP_DIR, f))
            except: pass
    
    # Save empty cache
    new_cache = {"posts": [], "status": "idle", "progress": "Cache cleared", "last_update": None}
    save_device_reddit_cache(mac, new_cache)
    return {"status": "success"}

@app.delete("/admin/rss/cache/{mac}")
def clear_rss_cache(mac: str):
    """Clear RSS cache and delete all associated images."""
    clean_mac = re.sub(r'[^a-zA-Z0-9]', '', mac).lower()
    
    # Delete files by pattern: rss_source2_mac_counter_hash.png
    for f in os.listdir(BITMAP_DIR):
        if f.startswith("rss_") and f"_{clean_mac}_" in f:
            try: os.remove(os.path.join(BITMAP_DIR, f))
            except: pass
    
    # Save empty cache
    new_cache = {"posts": [], "status": "idle", "progress": "Cache cleared", "last_refresh": None}
    save_device_rss_cache(mac, new_cache)
    return {"status": "success"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=4200)
