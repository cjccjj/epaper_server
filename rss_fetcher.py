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
    Refreshes the Reddit image cache for a specific device.
    """
    import database # Local import to avoid circular dependency if any
    
    device = db.query(database.Device).filter(database.Device.mac_address == mac).first()
    if not device:
        print(f"ERROR: Device {mac} not found for Reddit refresh")
        return
        
    config = device.reddit_config or {}
    subreddit = config.get("subreddit", "aww")
    show_title = config.get("show_title", True)
    bit_depth = int(config.get("bit_depth", 1))
    
    # Use device-level display dimensions
    width = device.display_width or 400
    height = device.display_height or 300
    
    # Use config settings if available, otherwise fallback to defaults
    clip_pct = int(config.get("clip_percent", 22 if bit_depth == 1 else 20))
    cost_pct = int(config.get("cost_percent", 6))
    
    # Gamma handling: use gamma_index or fallback
    gamma_labels = [1.0, 1.2, 1.4, 1.6, 1.8, 2.0, 2.2, 2.4]
    gamma_index = int(config.get("gamma_index", 0 if bit_depth == 1 else 6))
    if gamma_index < 0 or gamma_index >= len(gamma_labels):
        gamma_index = 0
    manual_gamma = gamma_labels[gamma_index]
    
    dither_strength = float(config.get("dither_strength", 1.0))
    sharpen_amount = float(config.get("sharpen_amount", 0.0))
    auto_optimize = config.get("auto_optimize", False)
        
    print(f"\n[REDDIT FETCH] Starting for {mac}")
    print(f"  Config: r/{subreddit}, {bit_depth}-bit, {width}x{height}")
    print(f"  Options: clip={clip_pct}%, cost={cost_pct}%, gamma={manual_gamma}, auto_opt={auto_optimize}")

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
    
    # In a manual fetch, we ignore existing cache to force re-analysis/overwrite
    print(f"  Manual fetch: Ignoring existing cache to force refresh.")
    existing_posts = {}
    
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

    async with httpx.AsyncClient(headers={"User-Agent": REDDIT_USER_AGENT}) as client:
        for strategy_config in strategies:
            sort = strategy_config["sort"]
            time = strategy_config["time"]
            target_count = strategy_config["limit"]
            label = strategy_config["label"]
            
            url = f"https://www.reddit.com/r/{subreddit}/{sort}/.rss?t={time}"
            print(f"\n  [STRATEGY: {label}] Fetching {url}")
            
            try:
                response = await client.get(url, headers={"User-Agent": REDDIT_USER_AGENT}, timeout=15.0)
                if response.status_code != 200:
                    print(f"    ERROR: Strategy {label} failed with status {response.status_code}")
                    continue
                
                feed = feedparser.parse(response.content)
                strategy_posts_added = 0
                
                print(f"    Found {len(feed.entries)} entries in RSS feed.")
                
                for entry in feed.entries[:25]:
                    if strategy_posts_added >= target_count:
                        print(f"    Target count ({target_count}) reached for {label}.")
                        break
                    
                    # Update progress
                    total_so_far = len(all_posts)
                    cache["progress"] = f"Processing {label}: {strategy_posts_added+1}/{target_count} (Total: {total_so_far})"
                    save_device_reddit_cache(mac, cache)

                    post_id = entry.get("id")
                    if not post_id or post_id in seen_ids:
                        continue
                    
                    print(f"    --- Processing Post: {entry.title[:50]}... ---")
                    
                    # Process new image
                    content = entry.get("summary", "") + entry.get("content", [{}])[0].get("value", "")
                    img_matches = re.findall(r'<img [^>]*src="([^"]+)"', content)
                    img_url = None
                    
                    if img_matches:
                        img_url = img_matches[0].replace("&amp;", "&")
                    elif 'media_content' in entry:
                        img_url = entry.media_content[0]['url']
                    elif entry.link.endswith(('.jpg', '.jpeg', '.png', '.gif')):
                        img_url = entry.link
                        
                    if img_url:
                        if "out.reddit.com" in img_url or "pixel.redditmedia.com" in img_url:
                            print(f"      SKIP: Tracking pixel or invalid URL.")
                            continue
                            
                        filename = f"reddit_{clean_mac}_{filename_counter}.png"
                        filepath = os.path.join(BITMAP_DIR, filename)
                        
                        try:
                            # Step 5: AI Analysis (Now includes aspect ratio filter inside)
                            print(f"      AI Analysis: Fetching optimization strategy...")
                            ai_analysis = await ai_optimizer.get_ai_analysis(
                                img_url, 
                                entry.link, 
                                entry.title, 
                                (width, height),
                                ai_prompt=config.get("ai_prompt")
                            )
                            
                            # Process for display
                            ai_parts = [
                                f"Sty:{ai_analysis.get('image_style', '?')}",
                                f"Pur:{ai_analysis.get('post_purpose', '?')}",
                                f"Dec:{ai_analysis.get('decision', '?')}",
                                f"Res:{ai_analysis.get('resize_strategy', '?')}",
                                f"Gam:{ai_analysis.get('gamma', 0.0):.1f}",
                                f"Sha:{ai_analysis.get('sharpen', 0.0):.1f}",
                                f"Dith:{ai_analysis.get('dither', 0)}%"
                            ]
                            ai_summary = "AI: " + " | ".join(ai_parts)

                            # Check AI decision early (including aspect ratio skip)
                            if ai_analysis.get("decision") == "skip":
                                reason = ai_analysis.get("reason", "AI decision")
                                print(f"      DECISION: SKIP ({reason})")
                                code_summary = f"CODE: [SKIP] | Reason: {reason}"
                                all_posts.append({
                                    "id": post_id,
                                    "title": entry.title,
                                    "url": entry.link,
                                    "img_url": img_url,
                                    "filename": None,
                                    "status": "skip",
                                    "strategy": label,
                                    "debug_ai": ai_summary,
                                    "debug_code": code_summary
                                })
                                # Incremental Save
                                cache["posts"] = all_posts
                                save_device_reddit_cache(mac, cache)
                                seen_ids.add(post_id)
                                continue

                            # Step 6: Get technical strategy (using cached dimensions from AI analysis)
                            img_size = ai_analysis.get("_img_size")
                            strategy = ai_optimizer.get_process_strategy(ai_analysis, img_size=img_size, target_res=(width, height))
                            
                            if strategy.get("decision") == "skip":
                                reason = strategy.get("reason", "Thresholds")
                                print(f"      DECISION: SKIP ({reason})")
                                code_summary = f"CODE: [SKIP] | {reason}"
                                all_posts.append({
                                    "id": post_id,
                                    "title": entry.title,
                                    "url": entry.link,
                                    "img_url": img_url,
                                    "filename": None,
                                    "status": "skip",
                                    "strategy": label,
                                    "debug_ai": ai_summary,
                                    "debug_code": code_summary
                                })
                                # Incremental Save
                                cache["posts"] = all_posts
                                save_device_reddit_cache(mac, cache)
                                seen_ids.add(post_id)
                                continue

                            # Apply manual overrides if auto_optimize is OFF
                            if not auto_optimize:
                                print(f"      Strategy: Overriding AI with MANUAL settings.")
                                strategy["gamma"] = manual_gamma
                                strategy["sharpen"] = sharpen_amount
                                strategy["dither_strength"] = dither_strength
                            
                            # Step 7: Final Processing
                            # We need the original image again for processing (it was downloaded in AI step)
                            # But since we didn't keep it, we download it again or refactor to keep it.
                            # For simplicity and given the user's request for "deterministic" processing,
                            # we download it here.
                            img_ori = await asyncio.to_thread(image_processor.download_image_simple, img_url)
                            
                            print(f"      Image Processing: Applying pipeline...")
                            processed_img = await asyncio.to_thread(
                                image_processor.process_image_pipeline,
                                img_ori,
                                (width, height),
                                resize_method=strategy.get("resize_method", "padding"),
                                padding_color=strategy.get("padding_color", "white"),
                                gamma=strategy.get("gamma", 1.0),
                                sharpen=strategy.get("sharpen", 0.0),
                                dither_strength=strategy.get("dither_strength", 1.0),
                                title=entry.title if show_title else None,
                                bit_depth=bit_depth,
                                clip_pct=clip_pct,
                                cost_pct=cost_pct,
                                font_size=12,
                                bold=config.get("bold_title", False)
                            )
                            
                            # Save processed image
                            await asyncio.to_thread(image_processor.save_as_png, processed_img, filepath, bit_depth=bit_depth)
                            print(f"      SUCCESS: Saved to {filename}")
                            
                            # Code summary with technical params
                            code_parts = [
                                "[USE]",
                                f"Method:{strategy.get('resize_method', '?')}",
                                f"Gamma:{strategy.get('gamma', 1.0):.1f}",
                                f"Sharp:{strategy.get('sharpen', 0.0):.1f}",
                                f"Dither:{int(strategy.get('dither_strength', 0.0)*100)}%"
                            ]
                            code_summary = "CODE: " + " | ".join(code_parts)

                            all_posts.append({
                                "id": post_id,
                                "title": entry.title,
                                "url": entry.link,
                                "img_url": img_url,
                                "filename": filename,
                                "status": "use",
                                "strategy": label,
                                "bit_depth": bit_depth,
                                "width": width,
                                "height": height,
                                "debug_ai": ai_summary,
                                "debug_code": code_summary
                            })
                            
                            # Incremental Save
                            cache["posts"] = all_posts
                            save_device_reddit_cache(mac, cache)
                            
                            seen_ids.add(post_id)
                            strategy_posts_added += 1
                            filename_counter += 1
                        except Exception as e:
                            print(f"      ERROR: Image processing failed: {e}")
                            continue
                    else:
                        print(f"      SKIP: No valid image found in entry.")
            except Exception as e:
                print(f"    ERROR: Strategy {label} failed: {e}")
                continue
                        
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
    new_filenames = {p["filename"] for p in all_posts if isinstance(p, dict) and "filename" in p}
    orphaned_files = reddit_files_on_disk - new_filenames
    for orphan in orphaned_files:
        try:
            os.remove(os.path.join(BITMAP_DIR, orphan))
        except:
            pass
    
    print(f"\n[REDDIT FETCH] COMPLETE: {len(all_posts)} posts stored in cache.")
