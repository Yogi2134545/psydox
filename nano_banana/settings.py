"""Nano Banana AI Studio — configuration and constants."""
import os

GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")

BACKGROUND_OPTIONS = {
    "White": "pure white studio background, clean minimal",
    "Grey": "neutral grey studio background, professional",
    "Black": "pure black studio background, dramatic",
    "Luxury White": "luxury white marble-like studio background, high-end fashion",
    "Transparent": "__transparent__",
    "Marble": "white marble background with subtle veining, luxury product photography",
    "Concrete": "textured concrete background, industrial modern aesthetic",
    "Wood": "natural wood surface background, warm organic texture",
    "Luxury Studio": "high-end luxury photography studio background with soft gradient lighting",
    "Kitchen": "modern kitchen environment, lifestyle product setting",
    "Living Room": "contemporary living room interior, lifestyle product setting",
    "Bedroom": "elegant bedroom interior, lifestyle product setting",
    "Office": "modern professional office environment",
    "Retail Store": "clean retail store display environment",
    "Luxury Boutique": "high-end luxury boutique store interior",
    "Beach": "tropical beach setting with sand and ocean",
    "Mountain": "dramatic mountain landscape background",
    "Forest": "lush green forest nature background",
    "Nature": "beautiful natural outdoor environment",
    "Garden": "blooming garden with flowers and greenery",
    "Airport": "modern airport terminal environment",
    "Hotel": "luxury hotel room or lobby setting",
    "Restaurant": "elegant restaurant or dining setting",
    "Cafe": "cozy cafe interior setting",
    "Gym": "modern fitness gym environment",
    "Sports Ground": "outdoor sports field or stadium environment",
    "Festival": "vibrant festival or event atmosphere",
    "Wedding": "elegant wedding decoration background with flowers",
    "Christmas": "festive Christmas decoration with lights and ornaments",
    "Diwali": "vibrant Diwali festival lights and decorations",
    "Rain": "moody rainy atmosphere with rain drops and wet surfaces",
    "Snow": "clean snow-covered winter landscape",
    "Sunset": "beautiful golden sunset sky background",
    "Golden Hour": "warm golden hour natural lighting outdoor setting",
    "Night": "dramatic night photography background with city lights",
    "Custom Prompt": "__custom__",
}

LIFESTYLE_OPTIONS = [
    "Casual Street Style",
    "Active Outdoor",
    "Urban Professional",
    "Luxury Lifestyle",
    "Sports & Fitness",
    "Travel & Adventure",
    "Home & Comfort",
    "Beach & Summer",
    "Winter & Snow",
    "Festival & Party",
    "Wedding & Formal",
    "Gym & Workout",
    "Running & Marathon",
    "Yoga & Wellness",
    "Hiking & Nature",
    "Office & Business",
    "Date Night",
    "Brunch & Social",
    "Cultural & Ethnic",
    "Vintage & Retro",
]

MODEL_OPTIONS = {
    "gender": ["Female", "Male", "Child", "Teen", "Senior"],
    "age": ["18-25", "25-35", "35-45", "45-55", "55+"],
    "ethnicity": [
        "South Asian / Indian",
        "East Asian",
        "Southeast Asian",
        "Caucasian / White",
        "African / Black",
        "Hispanic / Latino",
        "Middle Eastern",
        "Mixed / Multiracial",
    ],
    "style": [
        "Natural / Minimal",
        "High Fashion",
        "Commercial / Catalog",
        "Athletic / Sports",
        "Casual Lifestyle",
        "Luxury Editorial",
        "Street Style",
        "Professional / Business",
    ],
}

STYLE_PRESETS = {
    "Luxury": (
        "ultra-luxury product photography, gold and marble accents, soft diffused light, "
        "Hermes/Chanel/LV aesthetic, extreme detail, 8K quality, impeccable shadows"
    ),
    "Minimal": (
        "clean minimalist product photography, pure white background, "
        "single soft light source, Apple-inspired aesthetic, negative space"
    ),
    "Nike Style": (
        "dynamic athletic product photography, motion energy, professional studio lighting, "
        "clean white or gradient background, bold composition, Nike/Jordan aesthetic, "
        "high contrast, sharp details"
    ),
    "Adidas Style": (
        "modern athletic lifestyle photography, clean lines, "
        "Adidas three-stripe aesthetic, urban energy, crisp product detail"
    ),
    "Apple Style": (
        "minimalist product photography on pure white, perfect studio lighting, "
        "razor-sharp focus, Apple keynote aesthetic, no shadows"
    ),
    "Premium": (
        "premium product photography, dramatic studio lighting, "
        "dark or gradient background, luxury feel, cinematic quality"
    ),
    "Commercial": (
        "clean commercial product photography, bright even lighting, "
        "white background, catalog style, professional composition"
    ),
    "Editorial": (
        "editorial fashion photography, creative composition, "
        "artistic lighting, magazine-quality aesthetic, storytelling"
    ),
    "Amazon": (
        "Amazon marketplace product photo, pure white #FFFFFF background, "
        "product fills 85% of frame, even soft lighting, no props, clear details"
    ),
    "Flipkart": (
        "Flipkart marketplace product photo, white background, "
        "product centered, clean professional lighting, catalog standard"
    ),
    "Myntra": (
        "Myntra fashion catalog photo, clean white background, "
        "fashion-forward styling, clear product detail, standard aspect ratio"
    ),
    "AJIO": (
        "AJIO fashion product photo, trendy lifestyle or white background, "
        "fashion-forward composition, vibrant colors, youthful energy"
    ),
    "Meesho": (
        "Meesho product photo, clean white or light background, "
        "clear product view, good lighting, affordable fashion style"
    ),
    "Shopify": (
        "Shopify ecommerce product photo, clean minimal background, "
        "professional lighting, lifestyle or white background, conversion-optimized"
    ),
    "Luxury Catalog": (
        "high-end luxury catalog photography, premium feel, "
        "dark moody or white background, perfect lighting, designer brand aesthetic"
    ),
    "Website Banner": (
        "wide-format website banner product photography, dramatic lighting, "
        "space for text overlay, landscape composition, professional"
    ),
    "Social Media": (
        "social media optimized product photo, square or portrait format, "
        "eye-catching composition, vibrant and engaging, shareable aesthetic"
    ),
    "Instagram": (
        "Instagram-worthy product photography, aesthetic composition, "
        "beautiful natural light, lifestyle feel, #aesthetic quality"
    ),
    "Facebook": (
        "Facebook commerce product photo, clean background, "
        "clear product detail, good lighting, ad-ready composition"
    ),
    "Pinterest": (
        "Pinterest-style product photography, aspirational lifestyle, "
        "beautiful composition, inspirational aesthetic, tall format"
    ),
}

EXPORT_FORMATS = ["JPEG", "PNG", "WEBP"]

LIGHTING_OPTIONS = [
    "Soft Studio",
    "Hard Dramatic",
    "Rembrandt",
    "Butterfly / Clamshell",
    "Loop Lighting",
    "Ring Light",
    "Natural Daylight",
    "Golden Hour Warm",
    "Neon / Cyberpunk",
    "Backlit / Silhouette",
    "High-Key (Bright)",
    "Low-Key (Dark)",
    "Product Lightbox",
    "Side Lighting",
    "Three-Point Studio",
]

SHADOW_OPTIONS = [
    "No Shadow",
    "Natural Drop Shadow",
    "Soft Diffused Shadow",
    "Hard Shadow",
    "Long Shadow",
    "Reflection Shadow",
    "Ground Shadow",
    "Multiple Light Shadows",
    "Colored Shadow",
    "Inner Glow",
]

SCENE_OPTIONS = [
    "Luxury Flat Lay",
    "Overhead Knolling",
    "Hero Product Shot",
    "360 View Composite",
    "Group / Collection Shot",
    "Scale Reference Shot",
    "Detail / Macro Shot",
    "Packaging & Product",
    "Ghost / Invisible Mannequin",
    "Hanging Product",
]

ENHANCEMENT_OPTIONS = [
    "Remove Dust",
    "Remove Wrinkles",
    "Remove Scratches",
    "Improve Stitching",
    "Improve Fabric",
    "Improve Leather",
    "Improve Jewelry",
    "Improve Glass",
    "Improve Metal",
    "Improve Product Edges",
    "Improve Colors",
    "Premium Marketplace Optimization",
]
