import ai_stylist
import asyncio

async def get_ai_analysis(img_url, post_url, post_title, target_resolution, ai_prompt=None):
    """
    AI Interface: Analyzes image and post metadata using real AI.
    """
    # Use the real AI analysis from ai_stylist
    # Offload the synchronous network call to a thread to avoid blocking the event loop
    try:
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
    except Exception as e:
        print(f"Error in AI analysis for {post_title}: {e}")
        # Higher-level fallback for Reddit
        return {
            "decision": "use",
            "image_style": "photography",
            "post_purpose": "others",
            "resize_strategy": "pad_white",
            "gamma": 1.0,
            "sharpen": 0.5,
            "dither": 50
        }

def get_process_strategy(ai_output, img_size=None, target_res=None):
    """
    Process Strategy Interface: Converts AI analysis into technical parameters.
    Input: 
        ai_output (dict): Output from get_ai_analysis (ImageRenderIntent schema)
        img_size (tuple): (width, height) of original image
        target_res (tuple): (width, height) of target display
    Output:
        dict: Technical processing parameters
    """
    # 1. Decision from AI
    if ai_output.get("decision") == "skip":
        return {"decision": "skip"}
    
    # Thresholds
    CROP_THRESHOLD = 0.12
    STRETCH_THRESHOLD = 0.3

    # Default values for processing
    gamma = ai_output.get("gamma", 1.0)
    sharpen = ai_output.get("sharpen", 0.5)
    dither_strength = ai_output.get("dither", 50) / 100.0

    # Range checks
    if not (1.0 <= gamma <= 2.4): gamma = 1.0
    if not (0.0 <= sharpen <= 2.0): sharpen = 0.5
    if not (0 <= ai_output.get("dither", 50) <= 100): dither_strength = 0.5

    strategy = ai_output.get("resize_strategy", "pad_white")
    final_method = "padding"
    padding_color = "white"

    # If we have image size, we check thresholds for crop/stretch
    if img_size and target_res:
        w, h = img_size
        tw, th = target_res
        img_ar = w / h
        target_ar = tw / th

        if strategy == "crop":
            # Calculate how much we need to crop
            if img_ar > target_ar: # Wider than target, crop width
                crop_amt = (w - h * target_ar) / w
            else: # Taller than target, crop height
                crop_amt = (h - w / target_ar) / h
            
            if crop_amt <= CROP_THRESHOLD:
                final_method = "crop"
            else:
                print(f"      STRATEGY: Crop too aggressive ({crop_amt:.2%}). Skipping.")
                return {"decision": "skip"}

        elif strategy == "stretch":
            # Calculate distortion
            stretch_amt = abs(img_ar / target_ar - 1)
            if stretch_amt <= STRETCH_THRESHOLD:
                final_method = "stretch"
                # For our processor, "stretch" is actually "stretch" method 
                # but we need to pass the stretch amount if it's handled by stretch_to_fit
            else:
                print(f"      STRATEGY: Stretch too aggressive ({stretch_amt:.2%}). Skipping.")
                return {"decision": "skip"}
        
        elif strategy == "pad_white":
            final_method = "padding"
            padding_color = "white"
        elif strategy == "pad_black":
            final_method = "padding"
            padding_color = "black"
    else:
        # No image size yet (shouldn't happen with new flow), fallback to pad
        if strategy == "stretch": final_method = "stretch"
        elif strategy == "crop": final_method = "crop"
        elif strategy == "pad_black": padding_color = "black"
        else: padding_color = "white"

    return {
        "decision": "use",
        "resize_method": final_method,
        "padding_color": padding_color,
        "gamma": gamma,
        "sharpen": sharpen,
        "dither_strength": dither_strength
    }
