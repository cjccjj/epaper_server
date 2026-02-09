import ai_stylist

async def get_ai_analysis(img_url, post_url, post_title, target_resolution, ai_prompt=None):
    """
    AI Interface: Analyzes image and post metadata using real AI.
    """
    # Use the real AI analysis from ai_stylist
    style_obj = ai_stylist.analyze_image(
        img_url, 
        post_title=post_title, 
        post_url=post_url, 
        target_resolution=target_resolution,
        custom_prompt=ai_prompt
    )
    
    return {
        "decision": style_obj.decision,
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
    reasoning = []
    
    # Refine based on AI output
    if content_type == "photo":
        gamma = 1.2 if gradient_complexity == "high" else 1.1
        sharpen = 0.2
        reasoning.append(f"Photo detected: setting gamma={gamma} for {'smooth' if gradient_complexity == 'high' else 'low'} gradients.")
    elif content_type == "memes":
        gamma = 1.0
        sharpen = 0.6 # High sharpening for text clarity
        dither_strength = 0.8 # Less dither to keep text clean
        reasoning.append("Meme detected: maximizing sharpening (0.6) and reducing dither (0.8) for text legibility.")
    elif content_type == "comic_cartoon":
        gamma = 1.1
        sharpen = 0.4
        reasoning.append("Comic/Cartoon detected: balanced sharpening (0.4) and gamma (1.1).")
    elif content_type == "text_heavy":
        gamma = 1.0
        sharpen = 0.8
        dither_strength = 0.5
        reasoning.append("Text-heavy image: aggressive sharpening (0.8) and low dither (0.5) for crispness.")
    elif content_type in ["UI", "charts"]:
        gamma = 1.0
        sharpen = 0.5
        dither_strength = 0.6
        reasoning.append(f"{content_type} detected: low dither (0.6) to preserve clean lines.")
    else:
        reasoning.append(f"Content type '{content_type}' uses default safe parameters.")
    
    if has_text_overlay:
        sharpen = max(sharpen, 0.8)
        dither_strength = min(dither_strength, 0.7)
        reasoning.append("Text overlay found: boosted sharpening to 0.8+ and capped dither at 0.7.")
    
    if contrast_priority == "bold":
        gamma = max(gamma, 1.2)
        reasoning.append("Contrast priority is 'bold': increased gamma to 1.2+.")

    print(f"      STRATEGY DECISION: {' | '.join(reasoning)}")

    return {
        "resize_method": ai_output.get("resize_method", "crop"),
        "gamma": gamma,
        "sharpen": sharpen,
        "dither_strength": dither_strength
    }
