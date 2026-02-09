import random

async def get_ai_analysis(img_for_ai, post_url, post_title, target_resolution):
    """
    AI Interface: Analyzes image and post metadata.
    Input: 
        img_for_ai (PIL): Image scaled to <= 512x512
        post_url (str): URL of the Reddit post
        post_title (str): Title of the post
        target_resolution (tuple): (width, height)
    Output:
        dict: AI analysis results
    """
    # Placeholder logic for initial implementation
    is_meme = any(word in post_title.lower() for word in ["meme", "funny", "when you", "relatable"])
    
    # style: photo, poster, meme, sketch, comic
    style = "meme" if is_meme else "photo"
    
    # gradient: rich, medium, low
    gradient = "rich" if style == "photo" else "low"
    
    # text_heavy: bool
    text_heavy = is_meme
    
    # has_overlay_text: bool (e.g. subtitles in a comic or text in a poster)
    has_overlay_text = is_meme
    
    # resize_method: crop fit, stretch fit, padding fit
    # Logic: Memes usually stretch, photos usually crop-to-fill
    resize_method = "stretch fit" if is_meme else "crop fit"

    return {
        "style": style,
        "has_overlay_text": has_overlay_text,
        "text_heavy": text_heavy,
        "gradient": gradient,
        "resize_method": resize_method
    }

async def get_process_strategy(ai_output):
    """
    Process Strategy Interface: Converts AI analysis into technical parameters.
    Input: 
        ai_output (dict): Output from get_ai_analysis
    Output:
        dict: Technical processing parameters
    """
    style = ai_output.get("style", "photo")
    text_heavy = ai_output.get("text_heavy", False)
    gradient = ai_output.get("gradient", "medium")
    
    # Default parameters
    gamma = 1.0
    sharpen = 0.0
    dither_strength = 1.0
    
    # Refine based on AI output
    if style == "photo":
        gamma = 1.2 if gradient == "rich" else 1.1
        sharpen = 0.2
    elif style == "meme":
        gamma = 1.0
        sharpen = 0.6 # High sharpening for text clarity
        dither_strength = 0.8 # Less dither to keep text clean
    elif style == "poster":
        gamma = 1.1
        sharpen = 0.4
    
    if text_heavy:
        sharpen = max(sharpen, 0.8)
        dither_strength = min(dither_strength, 0.7)

    return {
        "resize_method": ai_output.get("resize_method", "crop fit"),
        "gamma": gamma,
        "sharpen": sharpen,
        "dither_strength": dither_strength
    }
