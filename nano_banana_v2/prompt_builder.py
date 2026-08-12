"""
Nano Banana v2 — AI prompt construction utilities.

Improvements over v1:
  - All 20 LIFESTYLE_OPTIONS have rich, specific descriptions (v1 had only 4)
  - All 10 SCENE_OPTIONS have specific descriptions (v1 had 4)
  - All 15 LIGHTING_OPTIONS have specific descriptions (v1 had 10)
  - All 10 SHADOW_OPTIONS have specific descriptions (v1 had 7)
  - Product-fidelity instruction included in ALL prompt types
    (v1 only had it in model prompts)
  - Aspect ratio hint parameter added to all functions
  - Quality suffix is a single constant — change once, applies everywhere
"""
from __future__ import annotations

# ── Quality suffix appended to every prompt ──────────────────────────────────
_QUALITY = (
    "Ultra-high resolution, photorealistic, professional commercial quality, "
    "8K detail, perfect for e-commerce."
)

# ── Fidelity instruction injected in every AI prompt ─────────────────────────
_FIDELITY = (
    "CRITICAL — preserve the product from the reference image EXACTLY: "
    "same color, pattern, print, logo, branding, shape, texture and design — "
    "do NOT alter or reinterpret the product in any way."
)


def _aspect_hint(ratio_label: str) -> str:
    """Convert a ratio label like '1:1' or 'Custom' to a prompt hint."""
    if not ratio_label or ratio_label in ("Custom", ""):
        return ""
    return f"Compose for a {ratio_label} aspect ratio. "


# ── Background prompts ────────────────────────────────────────────────────────

_BACKGROUND_DETAIL: dict[str, str] = {
    "White":          "pure white seamless studio backdrop, clean minimal, #FFFFFF",
    "Grey":           "neutral mid-grey seamless studio backdrop, professional and versatile",
    "Black":          "pure black seamless studio backdrop, bold and dramatic",
    "Luxury White":   "white marble-finish luxury studio backdrop, subtle veining, high-fashion feel",
    "Transparent":    "transparent / no background — product isolated on alpha layer",
    "Marble":         "white Carrara marble surface with fine grey veining, luxury product photography",
    "Concrete":       "raw textured concrete surface, industrial modern aesthetic, muted tones",
    "Wood":           "natural warm-toned wood grain surface, organic artisan texture",
    "Luxury Studio":  "high-end photography studio with soft gradient grey-to-white sweep, premium commercial look",
    "Kitchen":        "modern bright kitchen with clean countertop and soft natural light streaming in",
    "Living Room":    "contemporary Scandinavian living room interior, warm neutral tones, lifestyle product context",
    "Bedroom":        "elegant minimal bedroom with soft white bedding and warm ambient lighting",
    "Office":         "modern professional open-plan office, clean desk environment, corporate lifestyle",
    "Retail Store":   "clean retail store display shelving with warm accent lighting, commercial context",
    "Luxury Boutique":"high-end luxury boutique interior with marble floors, warm gold accents and curated display",
    "Beach":          "tropical white-sand beach with turquoise ocean and clear blue sky, sun-drenched",
    "Mountain":       "dramatic rocky mountain peak with sweeping valley view and moody cloud backdrop",
    "Forest":         "lush verdant forest with dappled sunlight filtering through the canopy",
    "Nature":         "beautiful open natural landscape, rolling meadows and soft natural light",
    "Garden":         "blooming English garden with colourful flowers, green foliage and soft bokeh",
    "Airport":        "modern international airport terminal with polished floors and large windows",
    "Hotel":          "luxurious five-star hotel lobby or suite with elegant décor and ambient lighting",
    "Restaurant":     "upscale restaurant with intimate candlelit tables, warm décor, evening atmosphere",
    "Cafe":           "cosy artisan café with exposed brick, warm lighting and steaming coffee aesthetic",
    "Gym":            "modern professional gym with polished floors, cable machines and motivational energy",
    "Sports Ground":  "outdoor sports field or stadium with green turf, crowd energy and athletic atmosphere",
    "Festival":       "vibrant outdoor music festival with colourful lights, crowd energy and festive atmosphere",
    "Wedding":        "elegant wedding decoration with cascading white florals, fairy lights and silk draping",
    "Christmas":      "festive Christmas scene with decorated tree, warm fairy lights and snow-dusted props",
    "Diwali":         "vibrant Diwali celebration with diyas, rangoli patterns and warm golden festival light",
    "Rain":           "moody rainy atmosphere, wet reflective surfaces, rain streaks on glass, dramatic sky",
    "Snow":           "pristine snow-covered winter landscape, soft white ground, bare trees, cold serene air",
    "Sunset":         "golden sunset sky with warm orange-pink gradient horizon and silhouetted landscape",
    "Golden Hour":    "outdoor golden-hour magic light, long warm shadows, sun low on the horizon",
    "Night":          "dramatic night cityscape with glowing street lights, neon signs and star-lit sky",
}


def build_background_prompt(
    bg_option: str,
    product_desc: str = "",
    custom: str = "",
    ratio_label: str = "",
) -> str:
    if bg_option == "Custom Prompt":
        base = custom or "professional product photography background"
    else:
        base = _BACKGROUND_DETAIL.get(bg_option, bg_option)
        if base in ("__transparent__", "__custom__"):
            base = custom or "professional product photography background"
        if custom:
            base = f"{base}, {custom}"

    product_part = f" for {product_desc}" if product_desc else ""
    return (
        f"{_aspect_hint(ratio_label)}"
        f"Professional product photography background{product_part}: {base}. "
        "Background only — no products visible, seamless and clean. "
        f"{_QUALITY}"
    )


# ── Lifestyle prompts ─────────────────────────────────────────────────────────

_LIFESTYLE_DETAIL: dict[str, str] = {
    "Casual Street Style": (
        "candid street photography, busy urban pavement, natural daylight with soft shadows, "
        "brick walls and city storefronts in background, authentic and relatable everyday energy"
    ),
    "Active Outdoor": (
        "outdoor adventure lifestyle photography, lush park or trail setting, bright natural sunlight, "
        "dynamic energy and movement, trees and open sky in background"
    ),
    "Urban Professional": (
        "polished city-professional lifestyle, glass-and-steel CBD backdrop, crisp morning light, "
        "confident business-casual atmosphere, clean modern urban environment"
    ),
    "Luxury Lifestyle": (
        "aspirational luxury lifestyle photography, penthouse terrace or designer interior setting, "
        "soft diffused light with premium feel, gold and neutral tones, affluent high-end aesthetic"
    ),
    "Sports & Fitness": (
        "dynamic sports and fitness photography, professional gym or stadium environment, "
        "powerful athletic energy, motivational composition, dramatic sports lighting"
    ),
    "Travel & Adventure": (
        "travel lifestyle photography, iconic destination backdrop — mountains, cobblestone streets "
        "or sun-drenched coastline, sense of adventure and exploration, wanderlust aesthetic"
    ),
    "Home & Comfort": (
        "cosy home lifestyle photography, warm inviting living room or kitchen interior, "
        "soft ambient light, hygge comfort aesthetic, domestic everyday warmth"
    ),
    "Beach & Summer": (
        "sunny beach and summer lifestyle, white-sand shoreline with turquoise ocean, "
        "bright natural sunlight, carefree summer energy, coastal vacation atmosphere"
    ),
    "Winter & Snow": (
        "winter lifestyle photography, snow-covered outdoor scene or cosy chalet interior, "
        "cool crisp light, festive or adventurous winter energy, frosty atmospheric mood"
    ),
    "Festival & Party": (
        "vibrant festival and party lifestyle photography, colourful outdoor event atmosphere, "
        "bokeh party lights, celebratory crowd energy, joyful and energetic composition"
    ),
    "Wedding & Formal": (
        "elegant wedding and formal event photography, romantic floral décor and soft candlelight, "
        "sophisticated polished setting, tender and ceremonious atmosphere"
    ),
    "Gym & Workout": (
        "intense gym workout lifestyle photography, professional fitness facility, "
        "overhead industrial lighting on polished floors, raw athletic motivation and effort"
    ),
    "Running & Marathon": (
        "outdoor running and marathon lifestyle photography, open road or park trail setting, "
        "natural daylight with movement blur, endurance and determination energy"
    ),
    "Yoga & Wellness": (
        "serene yoga and wellness lifestyle photography, sunlit studio or peaceful outdoor space, "
        "soft natural light with neutral tones, mindful calm and balance aesthetic"
    ),
    "Hiking & Nature": (
        "hiking and nature lifestyle photography, mountain trail or forest path setting, "
        "dramatic natural landscape, adventurous outdoor exploration energy"
    ),
    "Office & Business": (
        "professional office and business lifestyle photography, clean modern open-plan workspace, "
        "neutral corporate tones, confident productive business atmosphere"
    ),
    "Date Night": (
        "romantic date-night lifestyle photography, upscale restaurant or glowing city evening backdrop, "
        "warm candlelit amber tones, sophisticated and intimate atmosphere"
    ),
    "Brunch & Social": (
        "trendy brunch and social lifestyle photography, stylish café or rooftop terrace setting, "
        "bright natural light with lush greenery, social connection and food culture energy"
    ),
    "Cultural & Ethnic": (
        "rich cultural lifestyle photography, vibrant traditional festival or cultural landmark setting, "
        "warm jewel tones, celebration of heritage and cultural identity"
    ),
    "Vintage & Retro": (
        "nostalgic vintage and retro lifestyle photography, 1970s–90s aesthetic styling, "
        "film-grain texture, faded warm colour grading, classic retro composition"
    ),
}


def build_lifestyle_prompt(
    style: str,
    product_desc: str = "",
    custom_prompt: str = "",
    ratio_label: str = "",
) -> str:
    product_part = f" featuring {product_desc}" if product_desc else ""
    scene_desc = _LIFESTYLE_DETAIL.get(style, f"{style} lifestyle photography scene")
    if custom_prompt:
        scene_desc = f"{scene_desc}, {custom_prompt}"
    return (
        f"{_aspect_hint(ratio_label)}"
        f"Professional lifestyle product photography{product_part}, {scene_desc}. "
        f"{_FIDELITY} "
        f"{_QUALITY}"
    )


# ── Model prompts ─────────────────────────────────────────────────────────────

_MODEL_ANGLE_MAP: dict[str, str] = {
    "Front":      "full-body front-facing view, model facing the camera directly",
    "Back":       "full-body rear view, model facing away from the camera",
    "¾ Left":     "three-quarter front view angled to the left",
    "¾ Right":    "three-quarter front view angled to the right",
    "Left Side":  "full-body left profile view, model facing left",
    "Right Side": "full-body right profile view, model facing right",
}


def build_model_prompt(
    gender: str,
    age: str,
    ethnicity: str,
    style: str,
    product_desc: str = "",
    angle: str = "Front",
    ratio_label: str = "",
) -> str:
    product_part = f" wearing/using {product_desc}" if product_desc else ""
    angle_desc   = _MODEL_ANGLE_MAP.get(angle, "")
    angle_part   = f", {angle_desc}" if angle_desc else ""
    return (
        f"{_aspect_hint(ratio_label)}"
        f"Professional fashion model photography, {gender.lower()} model, "
        f"age range {age}, {ethnicity} ethnicity, {style} style{product_part}{angle_part}. "
        f"{_FIDELITY} "
        "Photorealistic, commercial quality, clean studio or lifestyle background, "
        f"professional lighting, high resolution, fashion catalog quality. {_QUALITY}"
    )


# ── Scene prompts ─────────────────────────────────────────────────────────────

_SCENE_DETAIL: dict[str, str] = {
    "Luxury Flat Lay": (
        "elegant flat lay overhead arrangement, luxury props — silk fabric, marble surface, "
        "gold accents, fresh botanicals — with editorial-quality composition"
    ),
    "Overhead Knolling": (
        "precise knolling overhead arrangement, perfectly aligned components on pure white, "
        "geometric symmetry, designer product-detail composition"
    ),
    "Hero Product Shot": (
        "dramatic hero product shot, product as sole subject, three-point studio lighting, "
        "premium commercial photography with strong visual impact"
    ),
    "360 View Composite": (
        "360-degree product view composite, multiple angles displayed in a single frame, "
        "clean white background, complete product visibility for e-commerce"
    ),
    "Group / Collection Shot": (
        "curated product collection group shot, multiple related items beautifully arranged, "
        "consistent lighting, editorial product family composition"
    ),
    "Scale Reference Shot": (
        "product size reference shot, everyday object placed alongside product for scale context, "
        "clean background, clear size comparison for consumer confidence"
    ),
    "Detail / Macro Shot": (
        "extreme close-up macro product detail shot, crisp focus on texture, stitching, "
        "material quality or finish, showcasing craftsmanship and premium detail"
    ),
    "Packaging & Product": (
        "product with its original packaging displayed together, clean studio setting, "
        "packaging design clearly visible, unboxing-ready composition"
    ),
    "Ghost / Invisible Mannequin": (
        "ghost / invisible mannequin photography technique, garment displayed as if being worn, "
        "hollow interior visible, clean white background, standard e-commerce apparel format"
    ),
    "Hanging Product": (
        "product displayed hanging — on a hanger, hook or floating — against clean background, "
        "full garment or item visible, crisp and wrinkle-free presentation"
    ),
}


def build_scene_prompt(
    scene_type: str,
    product_desc: str = "",
    custom_prompt: str = "",
    ratio_label: str = "",
) -> str:
    product_part = f" of {product_desc}" if product_desc else ""
    desc = _SCENE_DETAIL.get(scene_type, f"{scene_type} product photography scene")
    if custom_prompt:
        desc = f"{desc}, {custom_prompt}"
    return (
        f"{_aspect_hint(ratio_label)}"
        f"Professional product scene{product_part}: {desc}. "
        f"{_FIDELITY} "
        f"{_QUALITY}"
    )


# ── Lighting prompts ──────────────────────────────────────────────────────────

_LIGHTING_DETAIL: dict[str, str] = {
    "Soft Studio":          "soft diffused studio lighting, broad light sources, even shadow-free illumination",
    "Hard Dramatic":        "hard dramatic directional lighting, crisp deep shadows, bold high-contrast look",
    "Rembrandt":            "Rembrandt lighting, triangular highlight on the shadow-side cheek, classic portrait chiaroscuro",
    "Butterfly / Clamshell":"butterfly clamshell beauty lighting, light directly above lens, soft fill below, no under-eye shadows",
    "Loop Lighting":        "loop lighting, small nose shadow dropping diagonally, flattering three-dimensional product look",
    "Ring Light":           "ring light, circular catchlights, even frontal beauty illumination, fashion photography",
    "Natural Daylight":     "natural window daylight, soft side-lit directional light, organic airy feel",
    "Golden Hour Warm":     "warm golden-hour sunlight, low-angle orange-gold rays, magical long shadows",
    "Neon / Cyberpunk":     "neon cyberpunk lighting, vivid magenta and cyan gels, futuristic urban night atmosphere",
    "Backlit / Silhouette": "dramatic backlit lighting, subject silhouetted against bright background, rim-light glow",
    "High-Key (Bright)":    "high-key bright studio lighting, minimal shadows, airy overexposed whites, clean and fresh",
    "Low-Key (Dark)":       "low-key moody lighting, deep shadows, single dramatic spotlight, cinematic dark atmosphere",
    "Product Lightbox":     "professional product lightbox, perfectly even shadowless wrap-around illumination, e-commerce standard",
    "Side Lighting":        "dramatic side lighting, strong directional key from 90 degrees, textured product surface detail",
    "Three-Point Studio":   "classic three-point studio lighting — key, fill, rim — balanced professional portrait and product setup",
}


def build_lighting_prompt(
    lighting_type: str,
    product_desc: str = "",
    custom_prompt: str = "",
    ratio_label: str = "",
) -> str:
    product_part = f" on {product_desc}" if product_desc else ""
    desc = _LIGHTING_DETAIL.get(lighting_type, f"{lighting_type} lighting setup")
    if custom_prompt:
        desc = f"{desc}, {custom_prompt}"
    return (
        f"{_aspect_hint(ratio_label)}"
        f"Apply {desc}{product_part} to this product image. "
        f"{_FIDELITY} "
        f"Photorealistic lighting result. {_QUALITY}"
    )


# ── Shadow prompts ────────────────────────────────────────────────────────────

_SHADOW_DETAIL: dict[str, str] = {
    "No Shadow":             "remove all shadows completely — perfectly clean shadowless product image",
    "Natural Drop Shadow":   "natural drop shadow beneath and slightly behind the product, soft-edged and realistic",
    "Soft Diffused Shadow":  "soft wide diffused shadow, gentle gradual fade, natural ambient light source",
    "Hard Shadow":           "crisp hard cast shadow, sharp-edged, strong single directional light",
    "Long Shadow":           "long graphic stylised shadow stretching at low angle, editorial design aesthetic",
    "Reflection Shadow":     "product reflection on a glossy floor surface, perfect mirror reflection, luxury feel",
    "Ground Shadow":         "realistic ground-contact shadow, product anchored solidly to the surface, studio photography",
    "Multiple Light Shadows":"multiple overlapping shadows from several light sources, complex dynamic lighting",
    "Colored Shadow":        "stylised coloured shadow — shadow tinted with a complementary or brand colour",
    "Inner Glow":            "soft inner glow or halo effect around the product edges, premium hero-shot look",
}


def build_shadow_prompt(
    shadow_type: str,
    product_desc: str = "",
    custom_prompt: str = "",
    ratio_label: str = "",
) -> str:
    product_part = f" of {product_desc}" if product_desc else ""
    desc = _SHADOW_DETAIL.get(shadow_type, f"{shadow_type} shadow effect")
    if custom_prompt:
        desc = f"{desc}, {custom_prompt}"
    return (
        f"{_aspect_hint(ratio_label)}"
        f"Add {desc}{product_part} to this product image. "
        f"{_FIDELITY} "
        f"Photorealistic, professional e-commerce quality. {_QUALITY}"
    )


# ── Enhancement prompts ───────────────────────────────────────────────────────

def build_enhancement_prompt(
    enhancements: list,
    product_desc: str = "",
    ratio_label: str = "",
) -> str:
    enh_list = ", ".join(enhancements)
    product_part = f" of {product_desc}" if product_desc else ""
    return (
        f"{_aspect_hint(ratio_label)}"
        f"Enhance this product image{product_part}: apply {enh_list}. "
        f"{_FIDELITY} "
        f"Professional e-commerce retouching, photorealistic result. {_QUALITY}"
    )


# ── Style preset prompts ──────────────────────────────────────────────────────

def build_from_preset(
    preset_name: str,
    product_desc: str = "",
    ratio_label: str = "",
) -> str:
    from nano_banana.settings import STYLE_PRESETS
    base = STYLE_PRESETS.get(preset_name, "professional product photography")
    product_part = f" of {product_desc}" if product_desc else ""
    return (
        f"{_aspect_hint(ratio_label)}"
        f"Professional product photography{product_part}. {base}. "
        f"{_FIDELITY} "
        f"{_QUALITY}"
    )
