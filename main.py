from fastapi import FastAPI, Header, HTTPException, Depends, Body, File, UploadFile, BackgroundTasks
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
import database
import uuid
import datetime
import os
import shutil
import feedparser
import requests
import httpx
import re
import asyncio
import image_processor
from typing import Optional, List

app = FastAPI()

# Configuration
BITMAP_DIR = "bitmaps"
os.makedirs(BITMAP_DIR, exist_ok=True)

# Reddit User Agent
REDDIT_USER_AGENT = "linux:epaper-server:v1.0.0 (by /u/cj)"

# Cache for Reddit top images to avoid frequent fetching
# Format: { "images": [filenames], "last_update": datetime }
reddit_global_cache = {"posts": [], "last_update": None}

# Initialize database
database.init_db()

@app.on_event("startup")
async def startup_event():
    # Start a background task to refresh Reddit feeds periodically
    # It will use the last known config or wait for manual fetch
    asyncio.create_task(reddit_update_daemon())

async def refresh_global_reddit_cache(subreddit="pics", sort="top", time="day"):
    """Fetches the top images from Reddit RSS and dithers them for the global cache."""
    print(f"DEBUG: refresh_global_reddit_cache called with subreddit={subreddit}, sort={sort}, time={time}")
    url = f"https://www.reddit.com/r/{subreddit}/{sort}/.rss?t={time}"
    print(f"DEBUG: Fetching RSS URL: {url}")
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers={"User-Agent": REDDIT_USER_AGENT}, timeout=15.0)
            print(f"RSS response status: {response.status_code}")
            if response.status_code != 200:
                print(f"Error: Failed to fetch RSS: {response.text}")
                return
            content = response.content
            
        feed = feedparser.parse(content)
        print(f"Found {len(feed.entries)} entries in RSS feed for r/{subreddit}")
        posts = []
        # Process up to all entries in the feed (usually 25) to find up to 10 good ones
        for i, entry in enumerate(feed.entries):
            if len(posts) >= 10: 
                print("DEBUG: Reached target of 10 good images.")
                break
            
            content = entry.get("summary", "") + entry.get("content", [{}])[0].get("value", "")
            img_matches = re.findall(r'<img [^>]*src="([^"]+)"', content)
            if img_matches:
                img_url = img_matches[0].replace("&amp;", "&")
                print(f"[{i+1}/{len(feed.entries)}] Attempting: {img_url}")
                
                # Process image
                filename = f"reddit_{len(posts)}.bmp"
                filepath = os.path.join(BITMAP_DIR, filename)
                try:
                    # Run image processing in a thread to not block the event loop
                    # Note: process_image_url will now raise ValueError if image requires padding > 30%
                    await asyncio.to_thread(
                        image_processor.process_image_url, 
                        img_url, filepath,
                        resize_mode='fit'
                    )
                    posts.append({
                        "title": entry.title, 
                        "url": entry.link, 
                        "img_url": img_url, 
                        "bmp_filename": filename
                    })
                    # Update global cache immediately so it's visible in preview and API
                    reddit_global_cache["posts"] = posts
                    print(f"  SUCCESS: Added post {len(posts)}: {entry.title}")
                except ValueError as ve:
                    print(f"  SKIPPED: {ve}")
                    continue
                except Exception as img_err:
                    print(f"  ERROR: Failed to process image: {img_err}")
                    continue
            else:
                print(f"[{i+1}/{len(feed.entries)}] No image found in post: {entry.title}")

        reddit_global_cache["posts"] = posts
        reddit_global_cache["last_update"] = datetime.datetime.now()
        reddit_global_cache["config"] = {"subreddit": subreddit, "sort": sort, "time": time}
        print(f"Reddit global cache updated: {len(posts)} posts dithered")
    except Exception as e:
        print(f"Failed to refresh global Reddit cache: {e}")

async def reddit_update_daemon():
    """Background daemon to update Reddit feeds periodically."""
    while True:
        # Wait for an hour
        await asyncio.sleep(3600)
        
        # Try to use the last known successful config, or default
        config = reddit_global_cache.get("config", {"subreddit": "pics", "sort": "top", "time": "day"})
        print(f"DEBUG: Background daemon refreshing Reddit cache for r/{config.get('subreddit')}")
        await refresh_global_reddit_cache(
            subreddit=config.get("subreddit", "pics"),
            sort=config.get("sort", "top"),
            time=config.get("time", "day")
        )

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

    # Update device status
    device.battery_voltage = battery_voltage
    device.fw_version = fw_version
    device.rssi = rssi
    device.last_update_time = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    
    # Use device's refresh_rate or fallback to provided header or default 60
    current_refresh_rate = refresh_rate if refresh_rate else device.refresh_rate
    if not current_refresh_rate:
        current_refresh_rate = 60
        
    device.next_expected_update = device.last_update_time + datetime.timedelta(seconds=current_refresh_rate)

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
            # Use a modulo to ensure index is within range if list shrunk
            idx = device.current_image_index % len(posts)
            current_post = posts[idx]
            filename = current_post["bmp_filename"]
            
            # Increment for next time
            device.current_image_index = (idx + 1) % len(posts)
        else:
            filename = "placeholder.bmp" # Fallback if no reddit posts found
    
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
    if "active_dish" in settings:
        device.active_dish = settings["active_dish"]
    if "reddit_config" in settings:
        device.reddit_config = settings["reddit_config"]
    
    db.commit()
    return {"status": "success"}

@app.get("/admin/reddit/preview/{mac}")
def reddit_preview(mac: str, db: Session = Depends(get_db)):
    # Return the global cache. The mac is kept for future per-device customization if needed.
    return {"posts": reddit_global_cache["posts"]}

@app.post("/admin/reddit/fetch_now")
async def reddit_fetch_now(background_tasks: BackgroundTasks, config: dict = Body(...)):
    """Triggers an immediate refresh of the global Reddit cache."""
    subreddit = config.get("subreddit")
    sort = config.get("sort")
    time = config.get("time")
    
    if not subreddit:
        # Fallback to last known or default if not provided
        last_config = reddit_global_cache.get("config", {})
        subreddit = last_config.get("subreddit", "pics")
        sort = last_config.get("sort", "top")
        time = last_config.get("time", "day")

    print(f"DEBUG: Manual fetch triggered for r/{subreddit} ({sort}/{time})")
    background_tasks.add_task(refresh_global_reddit_cache, subreddit, sort, time)
    return {"status": "success", "message": f"Fetch started for r/{subreddit}"}

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
