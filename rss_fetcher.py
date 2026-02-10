import os
import json
import datetime
import httpx
import feedparser
import re
import asyncio
import ai_optimizer
import image_processor
from PIL import Image

# Reddit User Agent
REDDIT_USER_AGENT = "linux:epaper-server:v1.0.0 (by /u/cj)"

async def refresh_device_reddit_cache(mac, db, BITMAP_DIR, load_device_reddit_cache, save_device_reddit_cache):
    """
    Main logic to fetch Reddit RSS, analyze with AI, and process images for a device.
    """
    import database
    
    device = db.query(database.Device).filter(database.Device.mac_address == mac).first()
    if not device:
        print(f"ERROR: Device {mac} not found for Reddit refresh")
        return
        
    config = device.reddit_config or {}
    subreddit = config.get("subreddit", "aww")
    bit_depth = int(config.get("bit_depth", 1))
    
    # Display dimensions
    width = device.display_width or 400
    height = device.display_height or 300
    
    # Processing parameters (manual fallback)
    clip_pct = int(config.get("clip_percent", 22 if bit_depth == 1 else 20))
    cost_pct = int(config.get("cost_percent", 6))
    
    gamma_labels = [1.0, 1.2, 1.4, 1.6, 1.8, 2.0, 2.2, 2.4]
    gamma_index = int(config.get("gamma_index", 0 if bit_depth == 1 else 6))
    if not (0 <= gamma_index < len(gamma_labels)): gamma_index = 0
    manual_gamma = gamma_labels[gamma_index]
    
    dither_strength = float(config.get("dither_strength", 1.0))
    sharpen_amount = float(config.get("sharpen_amount", 0.0))
    auto_optimize = config.get("auto_optimize", False)
        
    print(f"\n[REDDIT FETCH] Starting for {mac}")
    print(f"  Config: r/{subreddit}, {bit_depth}-bit, {width}x{height}")
    print(f"  Manual Fallbacks: clip={clip_pct}%, cost={cost_pct}%, gamma={manual_gamma}, auto_opt={auto_optimize}")

    # Fetching strategies
    strategies = [
        {"sort": "top", "time": "day", "limit": 15, "label": "Top Day"},
        {"sort": "hot", "time": "", "limit": 10, "label": "Hot"}
    ]
    
    all_posts = []
    seen_ids = set()
    
    # Initialize cache status
    cache = load_device_reddit_cache(mac)
    cache["status"] = "fetching"
    cache["progress"] = "Starting..."
    save_device_reddit_cache(mac, cache)
    
    # Determine filename counter
    clean_mac = mac.replace(":", "").lower()
    reddit_files = [f for f in os.listdir(BITMAP_DIR) if f.startswith(f"reddit_{clean_mac}_") and f.endswith(".png")]
    filename_counter = 0
    if reddit_files:
        try:
            filename_counter = max([int(f.split("_")[-1].split(".")[0]) for f in reddit_files]) + 1
        except:
            filename_counter = len(reddit_files)

    async with httpx.AsyncClient(headers={"User-Agent": REDDIT_USER_AGENT}) as client:
        for strat in strategies:
            sort, time, target_count, label = strat["sort"], strat["time"], strat["limit"], strat["label"]
            url = f"https://www.reddit.com/r/{subreddit}/{sort}/.rss?t={time}"
            print(f"\n  [STRATEGY: {label}] Fetching {url}")
            
            try:
                response = await client.get(url, timeout=15.0)
                if response.status_code != 200:
                    print(f"    ERROR: Status {response.status_code}")
                    continue
                
                feed = feedparser.parse(response.content)
                added_count = 0
                
                for entry in feed.entries[:25]:
                    if added_count >= target_count: break
                    
                    # Update progress in cache
                    cache["progress"] = f"Processing {label}: {added_count+1}/{target_count}"
                    save_device_reddit_cache(mac, cache)

                    post_id = entry.get("id")
                    if not post_id or post_id in seen_ids: continue
                    
                    print(f"    --- Post: {entry.title[:50]}... ---")
                    
                    # Extract image URL
                    content = entry.get("summary", "") + entry.get("content", [{}])[0].get("value", "")
                    img_matches = re.findall(r'<img [^>]*src="([^"]+)"', content)
                    img_url = img_matches[0].replace("&amp;", "&") if img_matches else None
                    if not img_url and entry.link.endswith(('.jpg', '.jpeg', '.png', '.gif')):
                        img_url = entry.link
                        
                    if img_url:
                        # Skip tracking pixels
                        if "out.reddit.com" in img_url or "pixel.redditmedia.com" in img_url: continue
                            
                        filename = f"reddit_{clean_mac}_{filename_counter}.png"
                        filepath = os.path.join(BITMAP_DIR, filename)
                        
                        try:
                            # 1. AI Analysis & Filtering
                            print(f"      AI Analysis...")
                            ai_analysis = await ai_optimizer.get_ai_analysis(
                                img_url, entry.link, entry.title, (width, height),
                                ai_prompt=config.get("ai_prompt")
                            )
                            
                            # Debug summary
                            ai_sum = f"AI: Sty:{ai_analysis.get('image_style', '?')} | Pur:{ai_analysis.get('post_purpose', '?')} | Dec:{ai_analysis.get('decision', '?')}"
                            
                            # Check decision
                            if ai_analysis.get("decision") == "skip":
                                reason = ai_analysis.get("reason", "AI decision")
                                print(f"      DECISION: SKIP ({reason})")
                                all_posts.append({
                                    "id": post_id, "title": entry.title, "url": entry.link, 
                                    "img_url": img_url, "filename": None, "status": "skip",
                                    "strategy": label, "debug_ai": ai_sum, "debug_code": f"CODE: [SKIP] | {reason}"
                                })
                                save_device_reddit_cache(mac, cache)
                                seen_ids.add(post_id)
                                continue

                            # 2. Get technical strategy
                            strategy = ai_optimizer.get_process_strategy(
                                ai_analysis, img_size=ai_analysis.get("_img_size"), target_res=(width, height)
                            )
                            
                            if strategy.get("decision") == "skip":
                                reason = strategy.get("reason", "Thresholds")
                                print(f"      DECISION: SKIP ({reason})")
                                all_posts.append({
                                    "id": post_id, "title": entry.title, "url": entry.link, 
                                    "img_url": img_url, "filename": None, "status": "skip",
                                    "strategy": label, "debug_ai": ai_sum, "debug_code": f"CODE: [SKIP] | {reason}"
                                })
                                save_device_reddit_cache(mac, cache)
                                seen_ids.add(post_id)
                                continue

                            # Manual overrides if AI is OFF
                            if not auto_optimize:
                                strategy.update({"gamma": manual_gamma, "sharpen": sharpen_amount, "dither_strength": dither_strength})
                            
                            # 3. Final Image Processing
                            img_ori = await asyncio.to_thread(image_processor.download_image_simple, img_url)
                            
                            # AI-only decision for title inclusion:
                            # 1. Must be auto_optimize (AI Mode)
                            # 2. AI must have decided include_title=True
                            show_title = strategy.get("include_title", False) if auto_optimize else False

                            print(f"      Applying pipeline (AI Title Decision: {show_title})...")
                            processed_img = await asyncio.to_thread(
                                image_processor.process_image_pipeline,
                                img_ori, (width, height),
                                resize_method=strategy.get("resize_method", "padding"),
                                padding_color=strategy.get("padding_color", "white"),
                                gamma=strategy.get("gamma", 1.0),
                                sharpen=strategy.get("sharpen", 0.0),
                                dither_strength=strategy.get("dither_strength", 1.0),
                                title=entry.title if show_title else None,
                                bit_depth=bit_depth, clip_pct=clip_pct, cost_pct=cost_pct,
                                font_size=image_processor.OVERLAY_FONT_SIZE
                            )
                            
                            await asyncio.to_thread(image_processor.save_as_png, processed_img, filepath, bit_depth=bit_depth)
                            
                            # Code debug summary
                            code_sum = f"CODE: [USE] | {strategy.get('resize_method')} | G:{strategy.get('gamma'):.1f} | S:{strategy.get('sharpen'):.1f} | D:{int(strategy.get('dither_strength')*100)}%"

                            all_posts.append({
                                "id": post_id, "title": entry.title, "url": entry.link, "img_url": img_url,
                                "filename": filename, "status": "use", "strategy": label,
                                "debug_ai": ai_sum, "debug_code": code_sum
                            })
                            
                            cache["posts"] = all_posts
                            save_device_reddit_cache(mac, cache)
                            seen_ids.add(post_id)
                            added_count += 1
                            filename_counter += 1
                        except Exception as e:
                            print(f"      ERROR: {e}")
            except Exception as e:
                print(f"    ERROR: Strategy {label} failed: {e}")
                        
    if not all_posts:
        print(f"\n[REDDIT FETCH] FAILED: No posts fetched for {mac}. Keeping old cache.")
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
    new_filenames = {p["filename"] for p in all_posts if isinstance(p, dict) and p.get("filename")}
    orphaned_files = reddit_files_on_disk - new_filenames
    for orphan in orphaned_files:
        try:
            os.remove(os.path.join(BITMAP_DIR, orphan))
        except:
            pass
    
    print(f"\n[REDDIT FETCH] COMPLETE: {len(all_posts)} posts stored in cache.")

async def cleanup_orphaned_bitmaps(BITMAP_DIR, db):
    """
    Periodic cleanup of bitmaps that are no longer referenced by any device cache.
    """
    import database
    from main import load_device_reddit_cache
    
    all_devices = db.query(database.Device).all()
    referenced_files = {"placeholder.png"}
    
    for dev in all_devices:
        # Gallery images
        for img in dev.images:
            referenced_files.add(img.filename)
            
        # Reddit images
        cache = load_device_reddit_cache(dev.mac_address)
        posts = cache.get("posts", [])
        for post in posts:
            if post.get("filename"):
                referenced_files.add(post.filename)
                
    # Scan directory
    on_disk = {f for f in os.listdir(BITMAP_DIR) if f.endswith(".png")}
    to_delete = on_disk - referenced_files
    
    deleted_count = 0
    for f in to_delete:
        try:
            os.remove(os.path.join(BITMAP_DIR, f))
            deleted_count += 1
        except:
            pass
            
    if deleted_count > 0:
        print(f"[CLEANUP] Deleted {deleted_count} unreferenced bitmaps.")
