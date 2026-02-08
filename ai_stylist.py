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

class ImageStyle(BaseModel):
    content_type: Literal["photo", "comic_illustration", "text_heavy", "other"]
    has_text_overlay: bool
    gradient_complexity: Literal["high", "low"]
    contrast_priority: Literal["detail", "bold"]

SYSTEM_PROMPT = """You are an e-paper image optimization expert. 
Analyze the provided image and categorize its visual characteristics to help choose the best dithering and sharpening parameters.

Guidelines:
1. content_type: 'photo' for real-life images, 'comic_illustration' for flat colors/line art, 'text_heavy' if text is the main focus.
2. has_text_overlay: true if there is clear readable text (titles, subtitles, memes). Ignore tiny footers or text on objects.
3. gradient_complexity: 'high' for photos with smooth skies/skin, 'low' for comics/logos/flat designs.
4. contrast_priority: 'detail' for photos where textures matter, 'bold' for comics or text where edges matter more.
"""

def analyze_image(image_pil) -> ImageStyle:
    """
    Analyzes a PIL image using OpenAI Vision and returns a structured style object.
    """
    if not os.getenv("OPENAI_API_KEY"):
        # Fallback if no API key is provided
        return ImageStyle(
            content_type="other",
            has_text_overlay=False,
            gradient_complexity="high",
            contrast_priority="detail"
        )

    # Resize to 400x300 as planned for the vision request
    vision_img = image_pil.copy()
    vision_img.thumbnail((400, 300))
    
    buffered = BytesIO()
    vision_img.save(buffered, format="JPEG", quality=85)
    base64_image = base64.b64encode(buffered.getvalue()).decode('utf-8')

    try:
        completion = client.beta.chat.completions.parse(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Analyze this image for e-paper optimization."},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_image}"
                            },
                        },
                    ],
                }
            ],
            response_format=ImageStyle,
        )
        return completion.choices[0].message.parsed
    except Exception as e:
        print(f"Error calling AI Stylist: {e}")
        # Fallback to safe defaults
        return ImageStyle(
            content_type="other",
            has_text_overlay=False,
            gradient_complexity="high",
            contrast_priority="detail"
        )
