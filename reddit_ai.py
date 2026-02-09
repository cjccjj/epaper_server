import base64
import io
import json
import os
from PIL import Image
import httpx

# Simplified AI logic for Reddit image analysis
# We'll use this to decide if an image is suitable and how to process it.

async def analyze_reddit_image(img_to_ai: Image.Image, title: str, target_size: tuple):
    """
    Sends a resized image and title to AI for processing strategy.
    Returns a dict with purpose, style, crop/stretch recommendation, text detection, etc.
    """
    # For now, we'll return a simplified strategy based on the content and target size
    # In a real scenario, this would call OpenAI/Gemini/etc.
    
    tw, th = target_size
    iw, ih = img_to_ai.size
    
    # Placeholder for actual AI call
    # We will implement a mock response that follows the requested structure
    
    # Basic heuristic-based "AI" for now
    is_text_heavy = False
    if len(title) > 100: # Very long titles might indicate text-heavy context
        is_text_heavy = True
        
    # Determine if it's likely a meme or photo
    style = "photo"
    if "meme" in title.lower() or "dank" in title.lower():
        style = "meme"
    
    # Recommendation logic
    recommendation = "fit" # default
    ratio_diff = abs((iw/ih) - (tw/th))
    if ratio_diff < 0.1:
        recommendation = "stretch"
    elif ratio_diff > 0.5:
        recommendation = "skip" # Too much would be lost in crop
        
    return {
        "purpose": "Reddit post display",
        "style": style,
        "strategy": recommendation, # "crop", "stretch", "skip"
        "text_heavy": is_text_heavy,
        "has_text_overlay": style == "meme",
        "content_type": "illustration" if style == "meme" else "photography",
        "suggested_gamma": 2.2 if style == "meme" else 1.0,
        "suggested_sharpen": 0.5 if is_text_heavy else 0.2
    }

async def get_ai_strategy(img: Image.Image, title: str, target_size: tuple):
    """
    Step 5: Use AI to decide what to do with the image.
    Resizes to 512x512 first (img_to_AI).
    """
    # Resize to 512x512 for AI (fit resize, no stretch)
    ai_input_img = img.copy()
    ai_input_img.thumbnail((512, 512), Image.Resampling.LANCZOS)
    
    # In a real implementation, we'd convert to base64 and send to an LLM
    # For now, we use our simplified analyzer
    return await analyze_reddit_image(ai_input_img, title, target_size)
