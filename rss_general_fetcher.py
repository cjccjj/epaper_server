import feedparser
import re
import httpx
from typing import List, Dict, Optional

async def fetch_general_rss(url: str) -> List[Dict]:
    """
    Fetches a general RSS feed and attempts to extract 5 elements:
    title, img_url, body_text, post_url, date.
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(url)
            response.raise_for_status()
            xml_data = response.text
        except Exception as e:
            print(f"Error fetching RSS: {e}")
            return []

    feed = feedparser.parse(xml_data)
    items = []

    for entry in feed.entries:
        # 1. Title
        title = entry.get("title", "No Title")

        # 2. Image URL (Top 3 possibilities)
        img_url = None
        
        # Possibility A: media_content or media_thumbnail
        if 'media_content' in entry and entry.media_content:
            img_url = entry.media_content[0].get('url')
        elif 'media_thumbnail' in entry and entry.media_thumbnail:
            img_url = entry.media_thumbnail[0].get('url')
        
        # Possibility B: enclosure
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
            "body_text": body_text,
            "post_url": post_url,
            "date": date,
            "status": "ok" if img_url else "no_image"
        })

    return items
