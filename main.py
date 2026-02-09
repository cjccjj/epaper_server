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
import feedparser
import requests
import httpx
import re
import asyncio
import image_processor
import ai_stylist
import reddit_ai
import random
import io
from PIL import Image
from typing import Optional, List
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

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
        "config": {"subreddit": "aww", "show_titles": True}
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

# Initialize scheduler
scheduler = AsyncIOScheduler()

# --- App Lifecycle ---
# Initialize database
database.init_db()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic
    if not scheduler.running:
        scheduler.start()
    
    # Check for devices that need Reddit updates
    db = database.SessionLocal()
    try:
        devices = db.query(database.Device).all()
        for device in devices:
            if device.active_dish == "reddit":
                # Trigger initial refresh in background
                asyncio.create_task(refresh_device_reddit_cache(device.mac_address))
    finally:
        db.close()
    
    yield
    
    # Shutdown logic
    scheduler.shutdown()

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

async def scheduled_reddit_update():
    """Periodic job to update Reddit content for all active devices."""
    db = database.SessionLocal()
    try:
        devices = db.query(database.Device).all()
        for device in devices:
            if device.active_dish == "reddit":
                # Only refresh if cache is older than 3 hours
                cache = load_device_reddit_cache(device.mac_address)
                if cache["last_update"]:
                    elapsed = (datetime.datetime.now() - cache["last_update"]).total_seconds()
                    if elapsed < 3 * 3600:
                        continue
                
                print(f"DEBUG: Scheduled Reddit update for {device.mac_address}")
                asyncio.create_task(refresh_device_reddit_cache(device.mac_address))
    finally:
        db.close()

async def initial_fetch_check():
    """Check if any device needs an initial Reddit fetch."""
    await scheduled_reddit_update()

async def refresh_device_reddit_cache(mac, db_session=None):
    """Fetch and dither images for a specific device."""
    # 1. Get device and its config
    if db_session is None:
        db = database.SessionLocal()
    else:
        db = db_session
        
    try:
        # Check if directory exists
        os.makedirs(BITMAP_DIR, exist_ok=True)
        
        device = db.query(database.Device).filter(database.Device.mac_address == mac).first()
        if not device:
            print(f"ERROR: Device {mac} not found for Reddit refresh")
            return
            
        config = device.reddit_config or {}
        subreddit = config.get("subreddit", "aww")
        show_titles = config.get("show_titles", True)
        bit_depth = int(config.get("bit_depth", 1))
        
        # Use device-level display dimensions
        width = device.display_width or 400
        height = device.display_height or 300
        
        # Use config settings if available, otherwise fallback to defaults
        clip_pct = int(config.get("clip_pct", 22 if bit_depth == 1 else 20))
        cost_pct = int(config.get("cost_pct", 6))
        apply_gamma = config.get("apply_gamma", bit_depth == 2)
        dither_mode = config.get("dither_mode", 'fs4g' if bit_depth == 2 else 'fs')
        dither_strength = float(config.get("dither_strength", 1.0))
        sharpen_amount = float(config.get("sharpen_amount", 0.0))
        auto_optimize = config.get("auto_optimize", False)
            
        print(f"DEBUG: Starting Reddit refresh for {mac} (r/{subreddit}, {bit_depth}-bit, {width}x{height})")

        # Mixed strategy: get Top/Day and Hot
        strategies = [
            {"sort": "top", "time": "day", "limit": 15, "label": "Top Day", "type": "recent"},
            {"sort": "hot", "time": "", "limit": 10, "label": "Hot", "type": "old_good"}
        ]
        
        all_posts = []
        seen_ids = set()
        
        cache = load_device_reddit_cache(mac)
        cache["status"] = "fetching"
        cache["progress"] = "Starting..."
        save_device_reddit_cache(mac, cache)

        existing_posts = {p["id"]: p for p in cache.get("posts", []) if isinstance(p, dict) and "id" in p}
        
        # Filename counter per device
        clean_mac = mac.replace(":", "").lower()
        reddit_files = [f for f in os.listdir(BITMAP_DIR) if f.startswith(f"reddit_{clean_mac}_") and f.endswith(".png")]
        if reddit_files:
            try:
                filename_counter = max([int(f.split("_")[-1].split(".")[0]) for f in reddit_files]) + 1
            except:
                filename_counter = len(reddit_files)
        else:
            filename_counter = 0

        async with httpx.AsyncClient() as client:
            for strategy in strategies:
                sort = strategy["sort"]
                time = strategy["time"]
                target_count = strategy["limit"]
                label = strategy["label"]
                s_type = strategy["type"]
                
                url = f"https://www.reddit.com/r/{subreddit}/{sort}/.rss?t={time}"
                
                try:
                    response = await client.get(url, headers={"User-Agent": REDDIT_USER_AGENT}, timeout=15.0)
                    if response.status_code != 200:
                        print(f"  ERROR: Strategy {label} failed with status {response.status_code}")
                        continue
                    
                    feed = feedparser.parse(response.content)
                    strategy_posts_added = 0
                    
                    print(f"  DEBUG: Strategy {label} found {len(feed.entries)} entries")
                    
                    for entry in feed.entries[:25]:
                        if strategy_posts_added >= target_count:
                            break
                        
                        # Update progress
                        total_so_far = len(all_posts)
                        cache["progress"] = f"Processing {label}: {strategy_posts_added+1}/{target_count} (Total: {total_so_far})"
                        save_device_reddit_cache(mac, cache)

                        post_id = entry.get("id")
                        if not post_id or post_id in seen_ids:
                            continue
                        
                        is_in_cache = post_id in existing_posts
                        
                        # Reuse existing if same config
                        if is_in_cache:
                            existing = existing_posts[post_id]
                            # Check if the existing image matches current bit_depth and dimensions
                            # For simplicity, if we change config, we re-process.
                            # But if nothing changed, reuse.
                            if existing.get("bit_depth") == bit_depth and \
                               existing.get("width") == width and \
                               existing.get("height") == height and \
                               os.path.exists(os.path.join(BITMAP_DIR, existing["filename"])):
                                
                                all_posts.append(existing)
                                seen_ids.add(post_id)
                                strategy_posts_added += 1
                                continue

                        # Process new image
                        content = entry.get("summary", "") + entry.get("content", [{}])[0].get("value", "")
                        img_matches = re.findall(r'<img [^>]*src="([^"]+)"', content)
                        img_url = None
                        
                        if img_matches:
                            img_url = img_matches[0].replace("&amp;", "&")
                        elif 'media_content' in entry:
                            # Some feeds use media_content
                            img_url = entry.media_content[0]['url']
                        elif entry.link.endswith(('.jpg', '.jpeg', '.png', '.gif')):
                            # Sometimes the link itself is the image
                            img_url = entry.link
                            
                        if img_url:
                            # Filter out tracking pixels or small icons if possible
                            if "out.reddit.com" in img_url or "pixel.redditmedia.com" in img_url:
                                continue
                                
                            filename = f"reddit_{clean_mac}_{filename_counter}.png"
                            filepath = os.path.join(BITMAP_DIR, filename)
                            
                            try:
                                # Step 2: Download image as img_ori
                                img_ori = await asyncio.to_thread(image_processor.download_image_simple, img_url)
                                if not img_ori:
                                    continue
                                
                                # Step 3: Check ratio fit
                                if not image_processor.check_ratio_fit(img_ori, target_size=(width, height)):
                                    print(f"  SKIPPED: Ratio misfit for {img_url}")
                                    continue
                                
                                # Step 5: AI analysis and Strategy
                                img_for_ai = img_ori.copy()
                                img_for_ai.thumbnail((512, 512), Image.Resampling.LANCZOS)
                                
                                ai_analysis = await reddit_ai.get_ai_analysis(img_for_ai, entry.link, entry.title, (width, height))
                                strategy = await reddit_ai.get_process_strategy(ai_analysis)
                                
                                # Inject user preference into analysis for display/processing
                                ai_analysis["show_titles"] = show_titles
                                
                                # Step 6 & 7: Process from img_ori
                                processed_img, debug_info = await asyncio.to_thread(
                                    image_processor.process_with_ai_strategy,
                                    img_ori,
                                    (width, height),
                                    ai_analysis,
                                    strategy,
                                    title=entry.title if show_titles else None,
                                    bit_depth=bit_depth,
                                    clip_pct=clip_pct,
                                    cost_pct=cost_pct
                                )
                                
                                # Save processed image
                                await asyncio.to_thread(image_processor.save_as_png, processed_img, filepath, bit_depth=bit_depth)
                                
                                all_posts.append({
                                    "id": post_id,
                                    "title": entry.title,
                                    "url": entry.link,
                                    "img_url": img_url,
                                    "filename": filename,
                                    "strategy": label,
                                    "bit_depth": bit_depth,
                                    "width": width,
                                    "height": height,
                                    "ai_labels": debug_info # Store full debug info here
                                })
                                
                                seen_ids.add(post_id)
                                strategy_posts_added += 1
                                filename_counter += 1
                            except Exception as e:
                                print(f"  SKIPPED: Image processing failed for {post_id}: {e}")
                                import traceback
                                traceback.print_exc()
                                continue
                        else:
                            # print(f"  DEBUG: No image found for {post_id}")
                            pass
                except Exception as e:
                    print(f"ERROR: Strategy {label} failed: {e}")
                    continue
                            
        if not all_posts:
            print(f"WARNING: No posts fetched for {mac}. Keeping old cache.")
            return

        # Update cache
        cache["posts"] = all_posts
        cache["last_update"] = datetime.datetime.now()
        cache["config"] = config
        cache["status"] = "idle"
        cache["progress"] = ""
        save_device_reddit_cache(mac, cache)
        
        # Cleanup orphaned files for THIS device
        reddit_files_on_disk = {f for f in os.listdir(BITMAP_DIR) if f.startswith(f"reddit_{clean_mac}_")}
        new_filenames = {p["filename"] for p in all_posts if isinstance(p, dict) and "filename" in p}
        orphaned_files = reddit_files_on_disk - new_filenames
        for orphan in orphaned_files:
            try:
                os.remove(os.path.join(BITMAP_DIR, orphan))
            except:
                pass

        print(f"Reddit cache updated for {mac}: {len(all_posts)} posts")
        
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
    "show_titles": True,
    "bit_depth": 2,
    "width": 400,
    "height": 300,
    "apply_gamma": True,
    "clip_pct": 20,
    "cost_pct": 6,
    "dither_strength": 1.0,
    "sharpen_amount": 0.0,
    "auto_optimize": False
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
        
    # Logic to select content based on active dish
    filename = "placeholder.png" # Fallback
    
    if device.active_dish == "gallery":
        images = sorted(device.images, key=lambda x: x.order)
        if images:
            # Use a modulo to ensure index is within range if list shrunk
            idx = device.current_image_index % len(images)
            current_img = images[idx]
            filename = current_img.filename
            
            # Increment for next time
            device.current_image_index = (idx + 1) % len(images)
    elif device.active_dish == "reddit":
        # Load per-device Reddit cache
        cache = load_device_reddit_cache(id)
        posts = cache.get("posts", [])
        
        if posts:
            # Simple rotation or pick based on time
            # For now, just use the current_image_index to cycle through reddit posts
            idx = device.current_image_index % len(posts)
            filename = posts[idx].get("filename", "placeholder.png")
            
            # Increment index for next time
            device.current_image_index = (device.current_image_index + 1) % len(posts)
        else:
            # If cache is empty, trigger a background refresh and show placeholder
            asyncio.create_task(refresh_device_reddit_cache(id))
            filename = "placeholder.png"
    
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
    """Analyze image style using AI Stylist (for manual Gallery processing)."""
    try:
        contents = await file.read()
        img = Image.open(io.BytesIO(contents))
        style = ai_stylist.analyze_image(img)
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
            "reddit_config": d.reddit_config,
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
    if "reddit_config" in settings:
        device.reddit_config = settings["reddit_config"]
    
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

@app.post("/admin/upload/{mac}")
async def upload_image(mac: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    device = db.query(database.Device).filter(database.Device.mac_address == mac).first()
    if not device: raise HTTPException(status_code=404, detail="Device not found")

    # Use the original filename or generate a new one, but keep the extension
    # Actually, we should probably force .png extension if we expect PNGs
    ext = os.path.splitext(file.filename)[1]
    if not ext: ext = ".png" # Default to .png if no extension
    
    filename = f"{mac.replace(':', '')}_{uuid.uuid4().hex}{ext}"
    file_path = os.path.join(BITMAP_DIR, filename)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=4200)
