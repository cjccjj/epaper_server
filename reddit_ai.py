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
        dict: {
            content_type: Literal["photo", "comic_cartoon", "text_heavy", "memes", "UI", "charts", "outline", "line arts", "Others"],
            has_text_overlay: bool,
            gradient_complexity: Literal["high", "low"],
            contrast_priority: Literal["detail", "bold"],
            resize_method: Literal["crop", "padding", "stretch"]
        }
    """
    # Placeholder logic for initial implementation
    is_meme = any(word in post_title.lower() for word in ["meme", "funny", "when you", "relatable"])
    is_comic = any(word in post_title.lower() for word in ["comic", "cartoon", "art"])
    
    # content_type
    if is_meme:
        content_type = "memes"
    elif is_comic:
        content_type = "comic_cartoon"
    else:
        content_type = "photo"
    
    # has_text_overlay
    has_text_overlay = is_meme or is_comic
    
    # gradient_complexity: high, low
    gradient_complexity = "high" if content_type == "photo" else "low"
    
    # contrast_priority: detail, bold
    contrast_priority = "bold" if has_text_overlay else "detail"
    
    # resize_method: crop, padding, stretch
    # Logic: Memes usually stretch, photos usually crop
    if is_meme:
        resize_method = "stretch"
    elif is_comic:
        resize_method = "padding"
    else:
        resize_method = "crop"

    return {
        "content_type": content_type,
        "has_text_overlay": has_text_overlay,
        "gradient_complexity": gradient_complexity,
        "contrast_priority": contrast_priority,
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
    content_type = ai_output.get("content_type", "photo")
    has_text_overlay = ai_output.get("has_text_overlay", False)
    gradient_complexity = ai_output.get("gradient_complexity", "high")
    contrast_priority = ai_output.get("contrast_priority", "detail")
    
    # Default parameters
    gamma = 1.0
    sharpen = 0.0
    dither_strength = 1.0
    
    # Refine based on AI output
    if content_type == "photo":
        gamma = 1.2 if gradient_complexity == "high" else 1.1
        sharpen = 0.2
    elif content_type == "memes":
        gamma = 1.0
        sharpen = 0.6 # High sharpening for text clarity
        dither_strength = 0.8 # Less dither to keep text clean
    elif content_type == "comic_cartoon":
        gamma = 1.1
        sharpen = 0.4
    
    if has_text_overlay:
        sharpen = max(sharpen, 0.8)
        dither_strength = min(dither_strength, 0.7)
    
    if contrast_priority == "bold":
        # Maybe slightly adjust gamma or sharpening for "bold" look
        gamma = max(gamma, 1.2)

    return {
        "resize_method": ai_output.get("resize_method", "crop"),
        "gamma": gamma,
        "sharpen": sharpen,
        "dither_strength": dither_strength
    }
