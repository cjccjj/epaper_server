Great — below is the **complete, end‑to‑end design** based on **all your input and our discussion**, with:

1. ✅ **Final system design philosophy**
2. ✅ **Final AI output schema (intent‑level, Reddit‑aware)**
3. ✅ **Full production system prompt (ready to paste)**
4. ✅ **Clear, deterministic code‑side mapping guidelines**  
   (resize, gamma, sharpen, dithering, drop rules)

This is designed specifically for:
- Reddit image posts
- 400×300
- 2‑bit (4 gray) e‑paper
- Digest / glance reader
- Server‑side processing
- High robustness, low surprise

---

# 1️⃣ Final Design Philosophy (Lock This In)

### Core goal (unchanged):

> **Preserve the main meaning of Reddit images on a small 4‑gray e‑paper screen.**

### Key design decisions:

- ✅ AI judges **intent, purpose, and importance**
- ✅ Code executes **pixel math with strict limits**
- ✅ Image content is decisive
- ✅ Title + subreddit are supportive only
- ✅ Slight stretch is acceptable and often preferred
- ✅ Cropping is dangerous and requires high confidence
- ✅ Padding is safe but visually undesirable
- ✅ Losing the main joke / message = failure
- ✅ Losing subtle detail = acceptable

This is **not a general vision system** — it is a **Reddit digest editor**.

---

# 2️⃣ Final AI Output Schema (Intent‑Driven, Stable)

This schema is **deliberately qualitative** and **Reddit‑specific**.

```python
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
```

---

# 3️⃣ FULL PRODUCTION SYSTEM PROMPT (Paste This)

This is the **complete prompt**, incorporating everything we discussed.

---

### ✅ SYSTEM PROMPT

```text
You are an e-paper image editor for a Reddit image digest.

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
```

---

# 4️⃣ CODE‑SIDE MAPPING GUIDELINES (Deterministic)

Below is **how your Python code should translate intent → pixels**.

---

## A. Hard Drop Rules (Before Anything Else)

```python
if intent.decision == "skip":
    drop_image()

if intent.aspect_ratio_risk == "high" and intent.text_density in ["medium", "high"]:
    drop_image()
```

---

## B. Resize Mapping

### Stretch limits (device‑controlled)

```python
STRETCH_LIMITS = {
    "none": 0.0,
    "low": 0.10,
    "medium": 0.20,
    "high": 0.30
}
```

### Resize logic

```python
if intent.resize_strategy == "fill_prefer_stretch":
    resize_fill(
        max_stretch=STRETCH_LIMITS[intent.stretch_tolerance],
        crop=False
    )

elif intent.resize_strategy == "fill_crop_if_safe":
    if intent.crop_safety == "safe":
        smart_crop_then_fill()
    else:
        resize_fill(
            max_stretch=STRETCH_LIMITS[intent.stretch_tolerance],
            crop=False
        )

else:  # fit_with_padding
    resize_fit_with_padding(bg=intent.padding_color)
```

---

## C. Gamma Correction Mapping

```python
GAMMA_BASE = {
    "low": 1.1,
    "medium": 1.0,
    "high": 0.9
}

gamma = GAMMA_BASE[intent.gradient_importance]

# Clamp
gamma = clamp(gamma, 0.7, 1.3)
```

Histogram‑based fine tuning is allowed.

---

## D. Sharpening Mapping

```python
SHARPEN = {
    "low": 0.3,
    "medium": 0.8,
    "high": 1.4
}

sharpen = SHARPEN[intent.edge_importance]

if intent.primary_goal == "text_readability":
    sharpen += 0.2

if intent.primary_goal == "photo_realism":
    sharpen = min(sharpen, 0.6)

sharpen = clamp(sharpen, 0.0, 2.0)
```

---

## E. Dithering Mapping (Critical for 4‑Gray)

```python
DITHER = {
    "low": 20,
    "medium": 50,
    "high": 85
}

dither = DITHER[intent.gradient_importance]

if intent.primary_goal in ["text_readability", "shape_clarity"]:
    dither = min(dither, 30)

dither = clamp(dither, 0, 100)
```

---

## ✅ What This System Gives You

- ✅ Reddit‑aware AI judgment
- ✅ Stable, bounded image processing
- ✅ Graceful handling of mixed content
- ✅ Stretch as a first‑class tool
- ✅ Cropping only when safe
- ✅ Clean separation of concerns
- ✅ Easy tuning per device
- ✅ Future‑proof (new subs just work)

---

## Where to Go Next (Optional)

If you want, next we can:
- Create **golden test cases** from real Reddit posts
- Tune mappings for **specific subreddits**
- Add **text detection feedback loops**
- Optimize dithering patterns for 2‑bit e‑paper

Just tell me.