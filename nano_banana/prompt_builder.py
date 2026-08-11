"""Nano Banana — AI prompt construction utilities."""
from .settings import BACKGROUND_OPTIONS, STYLE_PRESETS


def build_background_prompt(
    bg_option: str, product_desc: str = "", custom: str = ""
) -> str:
    """Build an optimized prompt for background generation/replacement."""
    if bg_option == "Custom Prompt":
        base = custom or "professional product photography background"
    else:
        base = BACKGROUND_OPTIONS.get(bg_option, bg_option)
        if base in ("__transparent__", "__custom__"):
            base = custom or "professional product photography background"

    product_part = f" for {product_desc}" if product_desc else ""
    return (
        f"Professional product photography background{product_part}: {base}. "
        "Ultra-high resolution, photorealistic, perfect for e-commerce product display. "
        "Background only, no products, seamless and clean."
    )


def build_lifestyle_prompt(style: str, product_desc: str = "") -> str:
    """Build an optimized prompt for lifestyle scene generation."""
    product_part = f" featuring {product_desc}" if product_desc else ""
    style_map = {
        "Casual Street Style": (
            "candid street photography style, urban environment, natural light, "
            "authentic and relatable lifestyle scene"
        ),
        "Active Outdoor": (
            "active outdoor lifestyle photography, natural light, energy and movement, "
            "outdoors setting with nature elements"
        ),
        "Luxury Lifestyle": (
            "luxury lifestyle photography, high-end environment, aspirational setting, "
            "premium aesthetic, affluent lifestyle"
        ),
        "Sports & Fitness": (
            "sports and fitness photography, dynamic action, athletic energy, "
            "gym or sports environment, motivational"
        ),
    }
    scene_desc = style_map.get(style, f"{style} lifestyle photography")
    return (
        f"Professional lifestyle product photography{product_part}, {scene_desc}. "
        "Photorealistic, commercial quality, 8K resolution, natural composition."
    )


_MODEL_ANGLE_MAP = {
    "Front":         "full-body front-facing view, model facing the camera directly",
    "Back":          "full-body rear view, model facing away from the camera",
    "¾ Left":        "three-quarter front view angled to the left",
    "¾ Right":       "three-quarter front view angled to the right",
    "Left Side":     "full-body left profile view, model facing left",
    "Right Side":    "full-body right profile view, model facing right",
}


def build_model_prompt(
    gender: str,
    age: str,
    ethnicity: str,
    style: str,
    product_desc: str = "",
    angle: str = "Front",
) -> str:
    """Build an optimized prompt for AI model generation."""
    product_part = f" wearing/using {product_desc}" if product_desc else ""
    angle_desc   = _MODEL_ANGLE_MAP.get(angle, "")
    angle_part   = f", {angle_desc}" if angle_desc else ""
    return (
        f"Professional fashion model photography, {gender.lower()} model, "
        f"age range {age}, {ethnicity} ethnicity, {style} style{product_part}{angle_part}. "
        "CRITICAL — preserve the product from the reference image EXACTLY: "
        "same color, same pattern, same print, same logo, same branding, same design — "
        "do NOT change or reinterpret the product's appearance in any way. "
        "Photorealistic, commercial quality, clean studio or lifestyle background, "
        "professional lighting, high resolution, fashion catalog quality."
    )


def build_from_preset(preset_name: str, product_desc: str = "") -> str:
    """Build a complete optimized prompt from a named style preset."""
    base = STYLE_PRESETS.get(preset_name, "professional product photography")
    product_part = f" of {product_desc}" if product_desc else ""
    return (
        f"Professional product photography{product_part}. {base}. "
        "Ultra-high resolution, photorealistic, commercial grade quality."
    )


def build_enhancement_prompt(enhancements: list, product_desc: str = "") -> str:
    """Build a prompt for product enhancement operations."""
    enh_list = ", ".join(enhancements)
    product_part = f" of {product_desc}" if product_desc else ""
    return (
        f"Enhance this product image{product_part}: {enh_list}. "
        "Maintain original product shape and colors. "
        "Professional e-commerce quality output, photorealistic retouching."
    )


def build_scene_prompt(scene_type: str, product_desc: str = "") -> str:
    """Build a prompt for scene composition."""
    product_part = f" of {product_desc}" if product_desc else ""
    scene_map = {
        "Luxury Flat Lay": (
            "elegant flat lay arrangement, overhead view, luxury props and textures, "
            "marble or silk background, editorial quality"
        ),
        "Overhead Knolling": (
            "knolling overhead arrangement, perfectly organized components, "
            "clean white background, geometric alignment"
        ),
        "Hero Product Shot": (
            "hero product shot, dramatic studio lighting, product as central focus, "
            "premium commercial photography"
        ),
        "Ghost / Invisible Mannequin": (
            "invisible mannequin / ghost mannequin photography technique, "
            "garment displayed as if worn, clean white background"
        ),
    }
    desc = scene_map.get(scene_type, f"{scene_type} product photography")
    return (
        f"Professional product scene{product_part}: {desc}. "
        "Ultra-high resolution, photorealistic, commercial e-commerce quality."
    )


def build_lighting_prompt(lighting_type: str, product_desc: str = "") -> str:
    """Build a prompt for lighting application."""
    product_part = f" on {product_desc}" if product_desc else ""
    lighting_map = {
        "Soft Studio": "soft diffused studio lighting, even illumination, minimal shadows",
        "Hard Dramatic": "hard dramatic lighting, strong shadows, high contrast",
        "Rembrandt": "Rembrandt portrait lighting, triangular highlight on cheek, classic",
        "Ring Light": "ring light illumination, circular catchlights, beauty photography",
        "Natural Daylight": "natural window daylight, soft directional light, organic feel",
        "Golden Hour Warm": "warm golden hour sunlight, orange-golden tones, magical",
        "Neon / Cyberpunk": "neon light photography, cyberpunk color palette, futuristic",
        "High-Key (Bright)": "high-key bright lighting, overexposed whites, airy feel",
        "Low-Key (Dark)": "low-key dark moody lighting, deep shadows, dramatic",
        "Product Lightbox": "professional product lightbox, even shadowless lighting, e-commerce",
    }
    desc = lighting_map.get(lighting_type, f"{lighting_type} lighting")
    return (
        f"Apply professional {desc}{product_part} to this product image. "
        "Maintain product integrity, photorealistic result."
    )


def build_shadow_prompt(shadow_type: str) -> str:
    """Build a prompt for shadow generation."""
    shadow_map = {
        "Natural Drop Shadow": "natural drop shadow beneath product, subtle and realistic",
        "Soft Diffused Shadow": "soft diffused shadow, gentle and natural",
        "Hard Shadow": "crisp hard shadow, strong directional light",
        "Long Shadow": "long stylized shadow, graphic design aesthetic",
        "Reflection Shadow": "product reflection on glossy surface, luxury feel",
        "Ground Shadow": "realistic ground contact shadow, studio photography",
        "No Shadow": "remove all shadows, clean shadowless product image",
    }
    desc = shadow_map.get(shadow_type, f"{shadow_type}")
    return (
        f"Add {desc} to this product image. "
        "Photorealistic, professional e-commerce quality."
    )
