import feedparser
import re
import httpx
import os
import asyncio
import datetime
import io
from typing import List, Dict, Optional
from urllib.parse import urlparse
from PIL import Image
import ai_optimizer
import image_processor

async def fetch_general_rss(url: str) -> List[Dict]:
    """
    Fetches a general RSS feed and attempts to extract 5 elements:
    title, img_url, body_text, post_url, date.
    """
    # Use headers that explicitly request RSS/XML content and avoid browser-like HTML responses
    headers = {
        "User-Agent": "epaper-server/1.0 (RSS Reader; +https://github.com/cjccjj/epaper_server)",
        "Accept": "application/rss+xml, application/xml, application/atom+xml, text/xml;q=0.9, */*;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache"
    }
    
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        try:
            response = await client.get(url, headers=headers)
            print(f"DEBUG RSS: Fetching {url}")
            print(f"DEBUG RSS: Status: {response.status_code}")
            print(f"DEBUG RSS: Content-Type: {response.headers.get('content-type')}")
            
            response.raise_for_status()
            xml_data = response.text
            
            print(f"DEBUG RSS: Raw data snippet (500 chars): {xml_data[:500]}...")
        except Exception as e:
            print(f"Error fetching RSS from {url}: {e}")
            return []

    feed = feedparser.parse(xml_data)
    items = []

    for entry in feed.entries:
        # 1. Title
        title = entry.get("title", "No Title")

        # 2. Image URL (Multiple possibilities)
        img_url = None
        
        # Possibility A: Custom tags common in some video feeds (thumb_large, thumb)
        if 'thumb_large' in entry:
            img_url = entry.thumb_large
        elif 'thumb' in entry:
            img_url = entry.thumb
        
        # Possibility B: media_content or media_thumbnail
        if not img_url:
            if 'media_content' in entry and entry.media_content:
                img_url = entry.media_content[0].get('url')
            elif 'media_thumbnail' in entry and entry.media_thumbnail:
                img_url = entry.media_thumbnail[0].get('url')
        
        # Possibility C: enclosure
        if not img_url and 'enclosures' in entry and entry.enclosures:
            for enc in entry.enclosures:
                if enc.get('type', '').startswith('image/'):
                    img_url = enc.get('href')
                    break
        
        # Possibility C: Search in description/content for <img> tags
        if not img_url:
            content = entry.get("description", "") + entry.get("summary", "")
            if 'content' in entry:
                content += entry.content[0].get('value', '')
            
            img_matches = re.findall(r'<img [^>]*src="([^"]+)"', content)
            if img_matches:
                img_url = img_matches[0].replace("&amp;", "&")

        # 3. Body Text (Usually description or summary)
        # We strip HTML tags for the body text
        raw_body = entry.get("summary", entry.get("description", ""))
        body_text = re.sub(r'<[^>]+>', '', raw_body).strip()
        # Limit length
        if len(body_text) > 300:
            body_text = body_text[:297] + "..."

        # 4. URL to full post
        post_url = entry.get("link", "")

        # 5. Date
        date = entry.get("published", entry.get("pubDate", entry.get("updated", "")))

        items.append({
            "title": title,
            "img_url": img_url,
            "body": body_text,
            "post_url": post_url,
            "date": date,
            "status": "ok" if img_url else "no_image"
        })

    return items

async def refresh_device_rss_cache(mac: str, db, BITMAP_DIR: str, load_cache_func, save_cache_func):
    """
    Refreshes the General RSS image cache for a specific device.
    Similar to Reddit but for any RSS feed.
    """
    import database
    
    device = db.query(database.Device).filter(database.Device.mac_address == mac).first()
    if not device:
        print(f"ERROR: Device {mac} not found for RSS refresh")
        return
        
    config = device.rss_config or {}
    rss_url = config.get("url")
    if not rss_url:
        print(f"ERROR: No RSS URL configured for {mac}")
        return

    bit_depth = int(config.get("bit_depth", 1))
    width = device.display_width or 400
    height = device.display_height or 300
    auto_optimize = config.get("auto_optimize", False)
    ai_prompt = config.get("ai_prompt")
    
    # Manual settings overrides if auto_optimize is False
    clip_pct = int(config.get("clip_percent", 22 if bit_depth == 1 else 20))
    cost_pct = int(config.get("cost_percent", 6))
    
    gamma_labels = [1.0, 1.2, 1.4, 1.6, 1.8, 2.0, 2.2, 2.4]
    # Default to gamma 1.2 (index 1) when auto_optimize is False
    gamma_index = int(config.get("gamma_index", 1)) 
    if gamma_index < 0 or gamma_index >= len(gamma_labels):
        gamma_index = 1
    manual_gamma = gamma_labels[gamma_index]
    
    dither_strength = float(config.get("dither_strength", 1.0))
    sharpen_amount = float(config.get("sharpen_amount", 0.2)) # Default sharpen to 0.2

    print(f"\n[RSS FETCH] Starting for {mac} URL: {rss_url}")
    print(f"  Options: auto_opt={auto_optimize}, gamma={manual_gamma}, dither={dither_strength}")
    
    cache = load_cache_func(mac)
    cache["status"] = "fetching"
    cache["progress"] = "Fetching RSS feed..."
    save_cache_func(mac, cache)
    
    # 1. Clear old files
    clean_mac = re.sub(r'[^a-zA-Z0-9]', '', mac).lower()
    rss_domain = urlparse(rss_url).netloc.replace("www.", "")
    rss_source2 = re.sub(r'[^a-zA-Z0-9]', '', rss_domain).lower() or "rss"
    prefix = f"rss_{rss_source2}_{clean_mac}_"
    
    for f in os.listdir(BITMAP_DIR):
        if f.startswith(prefix):
            try:
                os.remove(os.path.join(BITMAP_DIR, f))
            except:
                pass
    
    # 2. Reset cache
    cache["posts"] = []
    save_cache_func(mac, cache)

    # 3. Fetch items
    items = await fetch_general_rss(rss_url)
    if not items:
        cache["status"] = "error"
        cache["progress"] = "Failed to fetch or parse RSS feed"
        save_cache_func(mac, cache)
        return

    all_processed = []
    filename_counter = 0

    # 4. Process items with images
    for i, item in enumerate(items[:15]): # Limit to 15 items
        img_url = item.get("img_url")
        if not img_url:
            all_processed.append({**item, "filename": None, "status": "no_image"})
            continue

        cache["progress"] = f"Processing item {i+1}/{len(items)}"
        save_cache_func(mac, cache)

        try:
            print(f"      Processing item: {item['title'][:50]}...")
            
            # Step 1: AI Analysis (always done for technical strategy, but used differently if auto_optimize is False)
            ai_analysis, img_ori = await ai_optimizer.get_ai_analysis(
                img_url, 
                item["post_url"], 
                item["title"], 
                (width, height),
                ai_prompt=ai_prompt
            )

            # Debug AI summary for preview
            ai_parts = [
                f"Sty:{ai_analysis.get('image_style', '?')}",
                f"Dec:{ai_analysis.get('decision', '?')}",
                f"Res:{ai_analysis.get('resize_strategy', '?')}",
                f"Gam:{ai_analysis.get('gamma', 0.0):.1f}"
            ]
            ai_summary = "AI: " + " | ".join(ai_parts)

            # Technical strategy
            img_size = ai_analysis.get("_img_size")
            strategy = ai_optimizer.get_process_strategy(ai_analysis, img_size=img_size, target_res=(width, height))
            
            if strategy.get("decision") == "skip":
                all_processed.append({
                    **item, 
                    "filename": None, 
                    "status": "skip", 
                    "reason": strategy.get("reason"),
                    "debug_ai": ai_summary
                })
                continue

            # Apply manual overrides if auto_optimize is False (Default behavior)
            if not auto_optimize:
                print(f"      Strategy: Using MANUAL settings (auto_optimize is False).")
                strategy["gamma"] = manual_gamma
                strategy["sharpen"] = sharpen_amount
                strategy["dither_strength"] = dither_strength
                strategy["resize_method"] = "crop" # Default to crop for manual RSS
                strategy["include_title"] = config.get("show_title", True)
            else:
                print(f"      Strategy: Using AI settings (auto_optimize is True).")
                # If auto_optimize is True, we use the AI's decision on title
                # strategy["include_title"] is already set by get_process_strategy

            # Final debug code summary
            code_parts = [
                f"Meth:{strategy.get('resize_method', '?')}",
                f"Gam:{strategy.get('gamma', 1.0):.1f}",
                f"Sharp:{strategy.get('sharpen', 0.0):.1f}",
                f"Dith:{int(strategy.get('dither_strength', 0.0)*100)}%",
                f"Ttl:{'Y' if strategy.get('include_title') else 'N'}"
            ]
            code_summary = "CODE: " + " | ".join(code_parts)

            # Process image
            final_show_title = strategy.get("include_title", False)
            
            processed_img = await asyncio.to_thread(
                image_processor.process_image_pipeline,
                img_ori,
                (width, height),
                resize_method=strategy.get("resize_method", "padding"),
                padding_color=strategy.get("padding_color", "white"),
                gamma=strategy.get("gamma", 1.0),
                sharpen=strategy.get("sharpen", 0.0),
                dither_strength=strategy.get("dither_strength", 1.0),
                title=item["title"] if final_show_title else None,
                bit_depth=bit_depth,
                clip_pct=clip_pct,
                cost_pct=cost_pct,
                font_size=image_processor.OVERLAY_FONT_SIZE
            )
            
            # Generate structured filename
            img_bytes = await asyncio.to_thread(image_processor.get_image_bytes, processed_img, bit_depth=bit_depth)
            filename = image_processor.generate_processed_filename(
                "rss", rss_source2, mac, filename_counter, img_bytes
            )
            filepath = os.path.join(BITMAP_DIR, filename)

            # Save
            await asyncio.to_thread(image_processor.save_as_png, processed_img, filepath, bit_depth=bit_depth)
            
            all_processed.append({
                **item,
                "filename": filename,
                "status": "ok",
                "img_url": img_url, # Ensure original URL is preserved for preview
                "debug_ai": ai_summary,
                "debug_code": code_summary
            })
            filename_counter += 1

        except Exception as e:
            print(f"      ERROR processing RSS item: {e}")
            all_processed.append({**item, "filename": None, "status": "error", "error": str(e)})

        # Incremental save
        cache["posts"] = all_processed
        save_cache_func(mac, cache)

    cache["status"] = "idle"
    cache["progress"] = "Complete"
    cache["last_refresh"] = datetime.datetime.now().isoformat()
    save_cache_func(mac, cache)
    print(f"[RSS FETCH] Done for {mac}. Processed {filename_counter} images.")
