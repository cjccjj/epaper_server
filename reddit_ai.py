import ai_stylist
import asyncio

async def get_ai_analysis(img_url, post_url, post_title, target_resolution, ai_prompt=None):
    """
    AI Interface: Analyzes image and post metadata using real AI.
    """
    # Use the real AI analysis from ai_stylist
    # Offload the synchronous network call to a thread to avoid blocking the event loop
    style_obj = await asyncio.to_thread(
        ai_stylist.analyze_image,
        img_url, 
        post_title=post_title, 
        post_url=post_url, 
        target_resolution=target_resolution,
        custom_prompt=ai_prompt
    )
    
    # Convert Pydantic object to dict for easier use in main pipeline
    return style_obj.model_dump()

async def get_process_strategy(ai_output):
    """
    Process Strategy Interface: Converts AI analysis into technical parameters.
    Input: 
        ai_output (dict): Output from get_ai_analysis (ImageRenderIntent schema)
    Output:
        dict: Technical processing parameters
    """
    # Hard drop rules - Relaxed: if AI says USE, we try to accommodate.
    if ai_output.get("decision") == "skip":
        return {"decision": "skip"}
    
    # Instead of skipping high aspect ratio risk with text, we force PADDING to ensure no crop/distortion
    force_padding = False
    if ai_output.get("aspect_ratio_risk") == "high" and ai_output.get("text_density") in ["medium", "high"]:
        print(f"      STRATEGY: High AR risk + Text detected. Forcing PADDING to preserve content.")
        force_padding = True

    # Stretch limits (mapping from AI design.md)
    STRETCH_LIMITS = {
        "none": 0.0,
        "low": 0.10,
        "medium": 0.20,
        "high": 0.30
    }

    # Gamma Correction Mapping
    GAMMA_BASE = {
        "low": 1.1,
        "medium": 1.0,
        "high": 0.9
    }
    
    gradient_importance = ai_output.get("gradient_importance", "medium")
    gamma = GAMMA_BASE.get(gradient_importance, 1.0)
    # Note: clamp is handled in image_processor or here if needed. 
    # For now we use the mapped values.

    # Sharpening Mapping
    SHARPEN = {
        "low": 0.3,
        "medium": 0.8,
        "high": 1.4
    }
    
    edge_importance = ai_output.get("edge_importance", "medium")
    sharpen = SHARPEN.get(edge_importance, 0.8)
    
    primary_goal = ai_output.get("primary_goal", "shape_clarity")
    if primary_goal == "text_readability":
        sharpen += 0.2
    elif primary_goal == "photo_realism":
        sharpen = min(sharpen, 0.6)
    
    # Dithering Mapping
    DITHER = {
        "low": 20,
        "medium": 50,
        "high": 85
    }
    
    dither_val = DITHER.get(gradient_importance, 50)
    if primary_goal in ["text_readability", "shape_clarity"]:
        dither_val = min(dither_val, 30)
    
    # Convert dither (0-100) to dither_strength (0.0-1.0) for existing processor
    dither_strength = dither_val / 100.0

    # Resize Strategy Mapping
    resize_strategy = ai_output.get("resize_strategy", "fill_prefer_stretch")
    stretch_tolerance = ai_output.get("stretch_tolerance", "low")
    max_stretch = STRETCH_LIMITS.get(stretch_tolerance, 0.10)
    crop_safety = ai_output.get("crop_safety", "risky")
    
    final_resize_method = "crop" # Default
    final_max_stretch = 0.0

    if force_padding:
        final_resize_method = "padding"
    elif resize_strategy == "fill_prefer_stretch":
        final_resize_method = "stretch"
        final_max_stretch = max_stretch
    elif resize_strategy == "fill_crop_if_safe":
        if crop_safety == "safe":
            final_resize_method = "crop"
        else:
            final_resize_method = "stretch"
            final_max_stretch = max_stretch
    else: # fit_with_padding
        final_resize_method = "padding"

    print(f"      STRATEGY DECISION: {primary_goal} | Resize: {final_resize_method} (stretch={final_max_stretch}) | Gamma: {gamma} | Sharpen: {sharpen} | Dither: {dither_strength}")

    return {
        "decision": "use",
        "resize_method": final_resize_method,
        "max_stretch": final_max_stretch,
        "gamma": gamma,
        "sharpen": sharpen,
        "dither_strength": dither_strength,
        "padding_color": ai_output.get("padding_color", "auto")
    }
