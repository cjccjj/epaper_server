import os
import json
import base64
from io import BytesIO
from openai import OpenAI
from pydantic import BaseModel
from typing import Literal

# Initialize OpenAI client
# It will look for OPENAI_API_KEY in environment variables
client = OpenAI()

class ImageRenderIntent(BaseModel):
    # Overall decision
    decision: Literal["use", "skip"]

    # Understanding
    post_purpose: Literal[
        "humor",          # memes, jokes
        "informational",  # charts, guides, screenshots
        "artistic",       # photography, illustration
        "showcase",       # cosplay, products, fashion
        "social",         # tweets, conversations
        "reaction",       # funny moments, expressions
        "unclear"
    ]

    # Layout understanding
    layout_complexity: Literal["single", "multi_panel"]
    text_density: Literal["none", "low", "medium", "high"]

    # Resize intent
    resize_strategy: Literal[
        "fill_prefer_stretch",
        "fill_crop_if_safe",
        "fit_with_padding"
    ]

    stretch_tolerance: Literal[
        "none",
        "low",     # ~10%
        "medium",  # ~20%
        "high"     # ~30%
    ]

    crop_safety: Literal[
        "forbidden",
        "risky",
        "safe"
    ]

    padding_color: Literal[
        "auto",
        "white",
        "black"
    ]

    # Visual priorities
    primary_goal: Literal[
        "text_readability",
        "shape_clarity",
        "photo_realism",
        "artistic_tone"
    ]

    edge_importance: Literal["low", "medium", "high"]
    gradient_importance: Literal["low", "medium", "high"]

    # Risk assessment
    aspect_ratio_risk: Literal["low", "medium", "high"]

    confidence: float  # 0.0 – 1.0

DEFAULT_SYSTEM_PROMPT = """You are an e-paper image editor for a Reddit image digest.

The target display is a small 400×300, 2-bit grayscale (4 gray levels) e-paper screen.
This is a quick-glance digest, not a full reader.

Your task is to analyze:
- the image itself (primary and decisive),
- visible text inside the image,
- the post title and subreddit (supporting context only),

and determine how the image should be rendered to preserve its main meaning.

────────────────────────────
PERCEPTION PRIORITY (IMPORTANT)
────────────────────────────
1. What is visible in the image is always decisive.
2. Text visible inside the image is often the main meaning.
3. Image style and structure matter.
4. The post title explains intent but may be misleading.
5. The subreddit provides weak contextual bias only.

Always trust the image over metadata.

────────────────────────────
REDDIT CONTEXT & PURPOSE
────────────────────────────
Reddit images are posted for a purpose.

Common purposes include:
- humor (memes, jokes)
- informational (charts, guides, screenshots)
- artistic (photography, illustrations)
- showcase (cosplay, fashion, objects)
- social (tweets, conversations)
- reaction (expressive moments)

The purpose determines what must survive on a small grayscale display.

────────────────────────────
DISPLAY BIAS (VERY IMPORTANT)
────────────────────────────
- Filling the screen is usually better than preserving exact proportions.
- Mild stretching is acceptable and often preferred over padding:
  - Up to ~30% stretch is acceptable for memes and text-heavy images.
  - Up to ~10% stretch is acceptable for photos.
- Cropping is dangerous and should only be suggested if you are confident that
  no important content (especially text) will be lost.
- If the image contains readable text, cropping should generally be forbidden.
- Padding is safe but visually undesirable and should be a last resort.
- High contrast and clear edges often read better than subtle shading on e-paper.

It is acceptable to lose minor detail.
It is unacceptable to lose the main joke, message, or subject.

────────────────────────────
HOW TO JUDGE IMAGES
────────────────────────────
Think like a human Reddit reader:

- For memes and screenshots, text usually carries the meaning.
- For reaction images, the expression or moment matters.
- For photography or art, subject clarity and tonal balance matter.
- For informational graphics, legibility matters more than aesthetics.

Ask yourself:
“What must a viewer understand in 2 seconds for this image to work?”

────────────────────────────
DECISION RULES
────────────────────────────
- Use "skip" if the image is too small, extremely blurry, has unreadable tiny text,
  extreme aspect ratio, tracking pixels, or no practical way to show meaningfully
  on a 400×300 screen.
- Otherwise, use "use" and provide a rendering intent.

Return ONLY values allowed by the output schema.
Do not explain your reasoning.
"""

def analyze_image(image_input, post_title="", post_url="", target_resolution=(400, 300), custom_prompt=None) -> ImageRenderIntent:
    """
    Analyzes an image (URL or PIL Image) using OpenAI Vision and returns a structured style object.
    """
    system_prompt = custom_prompt if custom_prompt else DEFAULT_SYSTEM_PROMPT
    
    if not os.getenv("OPENAI_API_KEY"):
        # Fallback if no API key is provided
        return ImageRenderIntent(
            decision="use",
            post_purpose="unclear",
            layout_complexity="single",
            text_density="none",
            resize_strategy="fill_prefer_stretch",
            stretch_tolerance="low",
            crop_safety="safe",
            padding_color="auto",
            primary_goal="shape_clarity",
            edge_importance="medium",
            gradient_importance="medium",
            aspect_ratio_risk="low",
            confidence=0.5
        )

    # Handle image input
    if isinstance(image_input, str):
        # It's a URL
        image_url_str = image_input
    else:
        # It's a PIL Image, convert to base64
        buffered = BytesIO()
        image_input.save(buffered, format="JPEG", quality=85)
        base64_image = base64.b64encode(buffered.getvalue()).decode('utf-8')
        image_url_str = f"data:image/jpeg;base64,{base64_image}"

    user_content = [
        {"type": "input_text", "text": f"Analyze this image for e-paper optimization.\nPost Title: {post_title}\nPost URL: {post_url}\nTarget Resolution: {target_resolution[0]}x{target_resolution[1]}"},
        {
            "type": "input_image",
            "image_url": image_url_str,
            "detail": "low"
        },
    ]

    try:
        response = client.responses.parse(
            model="gpt-5-mini",
            instructions=system_prompt,
            input=[
                {
                    "role": "user",
                    "content": user_content,
                }
            ],
            text_format=ImageRenderIntent,
        )
        return response.output_parsed
    except Exception as e:
        print(f"Error calling AI Stylist: {e}")
        # Fallback to safe defaults
        return ImageStyle(
            decision="use",
            content_type="Others",
            has_text_overlay=False,
            gradient_complexity="high",
            contrast_priority="detail",
            resize_method="crop"
        )
