import ai_stylist

async def get_ai_analysis(img_for_ai, post_url, post_title, target_resolution, ai_prompt=None):
    """
    AI Interface: Analyzes image and post metadata using real AI.
    """
    # Use the real AI analysis from ai_stylist
    style_obj = ai_stylist.analyze_image(
        img_for_ai, 
        post_title=post_title, 
        post_url=post_url, 
        target_resolution=target_resolution,
        custom_prompt=ai_prompt
    )
    
    return {
        "content_type": style_obj.content_type,
        "has_text_overlay": style_obj.has_text_overlay,
        "gradient_complexity": style_obj.gradient_complexity,
        "contrast_priority": style_obj.contrast_priority,
        "resize_method": style_obj.resize_method
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
