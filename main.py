from fastapi import FastAPI, Header, HTTPException, Depends, Body, File, UploadFile, BackgroundTasks
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
import database
import uuid
import datetime
import os
import shutil
import json
import feedparser
import requests
import httpx
import re
import asyncio
import image_processor
import random
from typing import Optional, List
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

app = FastAPI()

# Configuration
BITMAP_DIR = "bitmaps"
DATA_DIR = "data"
REDDIT_CACHE_FILE = os.path.join(DATA_DIR, "reddit_cache.json")
os.makedirs(BITMAP_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

# Reddit User Agent
REDDIT_USER_AGENT = "linux:epaper-server:v1.0.0 (by /u/cj)"

# Cache for Reddit top images to avoid frequent fetching
# Format: { "posts": [], "last_update": datetime, "config": {}, "rate_hours": 8 }
reddit_global_cache = {
    "posts": [], 
    "last_update": None, 
    "config": {"subreddit": "memes"},
    "rate_hours": 8
}

# Initialize scheduler
scheduler = AsyncIOScheduler()

def save_reddit_cache():
    """Save the global reddit cache to a persistent JSON file."""
    try:
        cache_data = reddit_global_cache.copy()
        if cache_data["last_update"]:
            cache_data["last_update"] = cache_data["last_update"].isoformat()
        
        with open(REDDIT_CACHE_FILE, "w") as f:
            json.dump(cache_data, f)
        print(f"DEBUG: Reddit cache saved to {REDDIT_CACHE_FILE}")
    except Exception as e:
        print(f"ERROR: Failed to save reddit cache: {e}")

def load_reddit_cache():
    """Load the global reddit cache from the persistent JSON file."""
    global reddit_global_cache
    if os.path.exists(REDDIT_CACHE_FILE):
        try:
            with open(REDDIT_CACHE_FILE, "r") as f:
                data = json.load(f)
                if data.get("last_update"):
                    data["last_update"] = datetime.datetime.fromisoformat(data["last_update"])
                
                # Merge loaded data into global cache
                reddit_global_cache.update(data)
                print(f"DEBUG: Reddit cache loaded from {REDDIT_CACHE_FILE} (Last update: {reddit_global_cache['last_update']})")
        except Exception as e:
            print(f"ERROR: Failed to load reddit cache: {e}")

# Load cache on module import
load_reddit_cache()

# Initialize database
database.init_db()

@app.on_event("startup")
async def startup_event():
    # Start the scheduler
    scheduler.start()
    
    # Add Reddit update job
    scheduler.add_job(
        scheduled_reddit_update,
        IntervalTrigger(hours=reddit_global_cache["rate_hours"]),
        id="reddit_update",
        replace_existing=True
    )
    
    # Initial check/fetch
    asyncio.create_task(initial_fetch_check())

async def initial_fetch_check():
    """Check if we need to fetch on startup."""
    needs_fetch = False
    if not reddit_global_cache["posts"]:
        print("DEBUG: No posts in cache, triggering initial fetch")
        needs_fetch = True
    elif reddit_global_cache["last_update"]:
        elapsed = datetime.datetime.now() - reddit_global_cache["last_update"]
        if elapsed.total_seconds() > reddit_global_cache["rate_hours"] * 3600:
            print(f"DEBUG: Cache expired ({elapsed.total_seconds()/3600:.1f}h old), triggering fetch")
            needs_fetch = True
    
    if needs_fetch:
        await scheduled_reddit_update()

async def scheduled_reddit_update():
    """Job wrapper with retry logic."""
    config = reddit_global_cache["config"]
    retries = 2
    for attempt in range(retries + 1):
        try:
            print(f"DEBUG: Scheduled Reddit fetch attempt {attempt + 1}")
            await refresh_global_reddit_cache(
                subreddit=config.get("subreddit", "memes")
            )
            print("DEBUG: Scheduled Reddit fetch successful")
            return
        except Exception as e:
            print(f"ERROR: Reddit fetch attempt {attempt + 1} failed: {e}")
            if attempt < retries:
                wait_time = 30 * (attempt + 1)
                print(f"DEBUG: Retrying in {wait_time}s...")
                await asyncio.sleep(wait_time)
    print("ERROR: All Reddit fetch attempts failed. Waiting for next scheduled run.")

async def refresh_global_reddit_cache(subreddit="memes"):
    """Fetches images from Reddit using a mixed strategy (uprising, day, week, month, year)."""
    print(f"DEBUG: refresh_global_reddit_cache called with subreddit={subreddit}")
    
    strategies = [
        {"sort": "rising", "time": "all", "limit": 6, "label": "uprising"},
        {"sort": "top", "time": "day", "limit": 5, "label": "top_today"},
        {"sort": "top", "time": "week", "limit": 3, "label": "top_week"},
        {"sort": "top", "time": "month", "limit": 3, "label": "top_month"},
        {"sort": "top", "time": "year", "limit": 3, "label": "top_year"}
    ]
    
    all_posts = []
    seen_ids = set()
    
    # Map of existing posts for reuse: {id: post_dict}
    existing_posts = {p["id"]: p for p in reddit_global_cache.get("posts", []) if isinstance(p, dict) and "id" in p}
    old_filenames = {p["bmp_filename"] for p in reddit_global_cache.get("posts", []) if isinstance(p, dict) and "bmp_filename" in p}
    
    # We'll use a local counter for filenames to avoid collisions
    # Start counter after existing reddit files if any
    reddit_files = [f for f in os.listdir(BITMAP_DIR) if f.startswith("reddit_") and f.endswith(".bmp")]
    if reddit_files:
        try:
            filename_counter = max([int(f.split("_")[1].split(".")[0]) for f in reddit_files]) + 1
        except:
            filename_counter = len(reddit_files)
    else:
        filename_counter = 0

    try:
        async with httpx.AsyncClient() as client:
            for strategy in strategies:
                sort = strategy["sort"]
                time = strategy["time"]
                target_count = strategy["limit"]
                
                url = f"https://www.reddit.com/r/{subreddit}/{sort}/.rss?t={time}"
                print(f"DEBUG: Fetching strategy {strategy['label']} from: {url}")
                
                response = await client.get(url, headers={"User-Agent": REDDIT_USER_AGENT}, timeout=15.0)
                if response.status_code != 200:
                    print(f"ERROR: Failed to fetch strategy {strategy['label']}: {response.status_code}")
                    continue
                
                feed = feedparser.parse(response.content)
                print(f"DEBUG: Strategy {strategy['label']} found {len(feed.entries)} entries")
                
                strategy_posts_added = 0
                for entry in feed.entries:
                    if strategy_posts_added >= target_count:
                        break
                    
                    post_id = entry.get("id")
                    if post_id in seen_ids:
                        continue
                    
                    # Try to reuse existing post if available and bitmap exists
                    if post_id in existing_posts:
                        existing = existing_posts[post_id]
                        if os.path.exists(os.path.join(BITMAP_DIR, existing["bmp_filename"])):
                            all_posts.append(existing)
                            seen_ids.add(post_id)
                            strategy_posts_added += 1
                            print(f"  REUSED [{strategy['label']}]: Post {post_id}")
                            continue

                    content = entry.get("summary", "") + entry.get("content", [{}])[0].get("value", "")
                    img_matches = re.findall(r'<img [^>]*src="([^"]+)"', content)
                    if img_matches:
                        img_url = img_matches[0].replace("&amp;", "&")
                        
                        # Process image
                        filename = f"reddit_{filename_counter}.bmp"
                        filepath = os.path.join(BITMAP_DIR, filename)
                        
                        try:
                            await asyncio.to_thread(
                                image_processor.process_image_url, 
                                img_url, filepath,
                                resize_mode='fit'
                            )
                            
                            all_posts.append({
                                "id": post_id,
                                "title": entry.title,
                                "url": entry.link,
                                "img_url": img_url,
                                "bmp_filename": filename,
                                "strategy": strategy['label']
                            })
                            
                            seen_ids.add(post_id)
                            strategy_posts_added += 1
                            filename_counter += 1
                            
                            # Incremental save
                            reddit_global_cache["posts"] = all_posts
                            save_reddit_cache()
                            
                            print(f"  SUCCESS [{strategy['label']}]: Added post {len(all_posts)}")
                        except ValueError as ve:
                            print(f"  SKIPPED: {ve}")
                            continue
                        except Exception as img_err:
                            print(f"  ERROR: Failed to process image: {img_err}")
                            continue
                            
        reddit_global_cache["posts"] = all_posts
        reddit_global_cache["last_update"] = datetime.datetime.now()
        reddit_global_cache["config"] = {"subreddit": subreddit}
        save_reddit_cache()
        
        # Cleanup orphaned files: files that were in old cache but not in new cache
        new_filenames = {p["bmp_filename"] for p in all_posts if isinstance(p, dict) and "bmp_filename" in p}
        orphaned_files = old_filenames - new_filenames
        for orphan in orphaned_files:
            orphan_path = os.path.join(BITMAP_DIR, orphan)
            if os.path.exists(orphan_path):
                try:
                    os.remove(orphan_path)
                    print(f"DEBUG: Cleaned up orphaned reddit bitmap: {orphan}")
                except Exception as e:
                    print(f"ERROR: Failed to remove orphan {orphan}: {e}")

        print(f"Reddit global cache updated: {len(all_posts)} posts dithered using mixed strategy")
        
    except Exception as e:
        print(f"Failed to refresh global Reddit cache: {e}")


# Dependency to get the database session
def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- Device APIs ---

@app.get("/api/setup")
def setup_device(id: str = Header(None), db: Session = Depends(get_db)):
    if not id:
        raise HTTPException(status_code=400, detail="ID header (MAC address) is required")
    
    device = db.query(database.Device).filter(database.Device.mac_address == id).first()
    
    if not device:
        api_key = str(uuid.uuid4()).replace("-", "")
        friendly_id = f"DEVICE_{id.replace(':', '')[-6:]}"
        device = database.Device(mac_address=id, api_key=api_key, friendly_id=friendly_id)
        db.add(device)
        db.commit()
        db.refresh(device)
        message = "Device successfully registered"
    else:
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
    filename = "placeholder.bmp" # Fallback
    
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
        posts = reddit_global_cache.get("posts", [])
        if posts:
            # Stateless selection: use current total minutes from epoch mod total posts
            # This ensures that as long as the client doesn't request more than once per minute,
            # they get a consistent sequence without duplicates for the duration of the cache size.
            total_minutes = int(datetime.datetime.now(datetime.UTC).timestamp() // 60)
            idx = total_minutes % len(posts)
            
            current_post = posts[idx]
            filename = current_post["bmp_filename"]
            
            # Update current_image_index for visibility in Admin UI
            device.current_image_index = idx
        else:
            filename = "placeholder.bmp" # Fallback if no reddit posts found
    
    # Update contact time only after successful image selection
    now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    device.last_update_time = now
    device.next_expected_update = now + datetime.timedelta(seconds=current_refresh_rate)
    
    db.commit()

    return {
        "status": 0,
        "image_url": f"/api/bitmap/{filename}",
        "filename": filename,
        "refresh_rate": current_refresh_rate,
        "reset_firmware": False,
        "update_firmware": False,
        "firmware_url": None,
        "special_function": None
    }

@app.get("/api/bitmap/{filename}")
def serve_bitmap(filename: str):
    path = os.path.join(BITMAP_DIR, filename)
    if not os.path.exists(path):
        # Create a tiny dummy BMP if not found so the device doesn't crash
        return HTTPException(status_code=404, detail="Bitmap not found")
    return FileResponse(path)

@app.post("/api/log")
def log_event(id: str = Header(None), body: dict = Body(...), db: Session = Depends(get_db)):
    if not id: raise HTTPException(status_code=400, detail="ID required")
    new_log = database.DeviceLog(mac_address=id, message=body.get("message", "No message"), metadata_json=body.get("metadata", {}))
    db.add(new_log)
    db.commit()
    return {"status": 200, "message": "Log captured"}

# --- Admin APIs ---

@app.get("/admin", response_class=HTMLResponse)
def admin_page():
    with open("static/admin.html", "r") as f:
        return f.read()

@app.get("/admin/devices")
def list_devices(db: Session = Depends(get_db)):
    devices = db.query(database.Device).all()
    result = []
    for d in devices:
        result.append({
            "mac_address": d.mac_address,
            "friendly_id": d.friendly_id,
            "battery_voltage": d.battery_voltage,
            "rssi": d.rssi,
            "refresh_rate": d.refresh_rate,
            "timezone": d.timezone,
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
    # Return the global cache. The mac is kept for future per-device customization if needed.
    return {
        "posts": reddit_global_cache["posts"],
        "last_update": reddit_global_cache["last_update"].isoformat() if reddit_global_cache["last_update"] else None,
        "rate_hours": reddit_global_cache["rate_hours"]
    }

@app.post("/admin/reddit/fetch_now")
async def fetch_reddit_now(config: dict = Body(...), db: Session = Depends(get_db)):
    """Manually trigger a Reddit cache refresh."""
    subreddit = config.get("subreddit")
    
    # Update cache config
    reddit_global_cache["config"] = {
        "subreddit": subreddit or reddit_global_cache["config"].get("subreddit", "memes")
    }
    save_reddit_cache()

    print(f"DEBUG: Manual fetch triggered for r/{reddit_global_cache['config']['subreddit']}")
    
    # Start the fetch in the background
    asyncio.create_task(refresh_global_reddit_cache(
        subreddit=reddit_global_cache["config"]["subreddit"]
    ))
    
    return {"status": "fetch_started"}

@app.post("/admin/upload/{mac}")
async def upload_image(mac: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    device = db.query(database.Device).filter(database.Device.mac_address == mac).first()
    if not device: raise HTTPException(status_code=404, detail="Device not found")

    ext = os.path.splitext(file.filename)[1]
    filename = f"{mac.replace(':', '')}_{uuid.uuid4().hex}{ext}"
    file_path = os.path.join(BITMAP_DIR, filename)

    # Save as temporary PNG first
    temp_path = file_path + ".png"
    with open(temp_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        # Convert to 1-bit BMP using Pillow to ensure 0=black, 1=white
        from PIL import Image
        with Image.open(temp_path) as img:
            # The canvas upload is already dithered (0,0,0 and 255,255,255)
            # convert("1") will map 0 to 0 and 255 to 1
            bmp_path = os.path.splitext(file_path)[0] + ".bmp"
            img.convert("1").save(bmp_path, "BMP")
            filename = os.path.basename(bmp_path)
        
        # Clean up temp file
        os.remove(temp_path)
    except Exception as e:
        print(f"Error converting upload to BMP: {e}")
        # Fallback to the original file if conversion fails
        filename = os.path.basename(file_path)
        os.rename(temp_path, file_path)

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
