"""
Psydox Lifestyle Scene Library

Structured scene definitions for AI lifestyle image generation.
Each scene maps to a detailed prompt description, lighting notes,
camera angle, and category tags.

Source: canonical extension of nano_banana_v2._LIFESTYLE_DETAIL — all 20
original scenes are preserved; 10 additional studio/editorial scenes added.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SceneDefinition:
    id:           str
    label:        str
    description:  str         # detailed environment description for the prompt
    lighting:     str         # lighting notes
    camera:       str         # suggested camera angle
    mood:         str         # emotional quality (authentic, aspirational, etc.)
    category_tags: list[str] = field(default_factory=list)   # category ids this scene fits best

    def prompt_fragment(self) -> str:
        """Compact, prompt-ready description of the scene."""
        return self.description


_SCENES: list[dict] = [
    # ── Street & Urban ────────────────────────────────────────────────────────
    {
        "id": "casual_street",
        "label": "Casual Street Style",
        "description": (
            "candid street photography, busy urban pavement, natural daylight with soft shadows, "
            "brick walls and city storefronts in background, authentic and relatable everyday energy"
        ),
        "lighting": "natural daylight, soft street shadows",
        "camera":   "eye level, medium shot, slight tilt",
        "mood":     "authentic, relatable",
        "category_tags": ["footwear", "apparel", "accessories"],
    },
    {
        "id": "urban_professional",
        "label": "Urban Professional",
        "description": (
            "polished city-professional lifestyle, glass-and-steel CBD backdrop, crisp morning light, "
            "confident business-casual atmosphere, clean modern urban environment"
        ),
        "lighting": "crisp morning light, blue hour cityscape",
        "camera":   "slightly elevated, 3/4 angle",
        "mood":     "confident, polished",
        "category_tags": ["apparel", "accessories", "electronics"],
    },
    {
        "id": "night_city",
        "label": "Night City",
        "description": (
            "dramatic night cityscape with glowing street lights, neon signs and star-lit sky, "
            "wet reflective pavement, moody cinematic night atmosphere"
        ),
        "lighting": "neon signs, street lights, bokeh reflections",
        "camera":   "low angle, dramatic perspective",
        "mood":     "dramatic, cinematic",
        "category_tags": ["footwear", "apparel", "accessories"],
    },
    # ── Nature & Outdoor ─────────────────────────────────────────────────────
    {
        "id": "active_outdoor",
        "label": "Active Outdoor",
        "description": (
            "outdoor adventure lifestyle photography, lush park or trail setting, bright natural sunlight, "
            "dynamic energy and movement, trees and open sky in background"
        ),
        "lighting": "bright natural sunlight, open sky",
        "camera":   "wide angle, action freeze",
        "mood":     "energetic, dynamic",
        "category_tags": ["footwear", "apparel", "accessories"],
    },
    {
        "id": "hiking_nature",
        "label": "Hiking & Nature",
        "description": (
            "hiking and nature lifestyle photography, mountain trail or forest path setting, "
            "dramatic natural landscape, adventurous outdoor exploration energy"
        ),
        "lighting": "golden-hour warm light, long shadows",
        "camera":   "wide angle, landscape hero",
        "mood":     "adventurous, rugged",
        "category_tags": ["footwear", "apparel", "accessories"],
    },
    {
        "id": "beach_summer",
        "label": "Beach & Summer",
        "description": (
            "sunny beach and summer lifestyle, white-sand shoreline with turquoise ocean, "
            "bright natural sunlight, carefree summer energy, coastal vacation atmosphere"
        ),
        "lighting": "bright tropical sunlight, ocean sparkle",
        "camera":   "medium shot, slightly elevated",
        "mood":     "carefree, vibrant",
        "category_tags": ["footwear", "apparel", "accessories", "beauty"],
    },
    {
        "id": "travel_adventure",
        "label": "Travel & Adventure",
        "description": (
            "travel lifestyle photography, iconic destination backdrop — mountains, cobblestone streets "
            "or sun-drenched coastline, sense of adventure and exploration, wanderlust aesthetic"
        ),
        "lighting": "golden hour or mid-day destination light",
        "camera":   "wide establishing shot",
        "mood":     "wanderlust, aspirational",
        "category_tags": ["footwear", "apparel", "accessories", "electronics"],
    },
    {
        "id": "winter_snow",
        "label": "Winter & Snow",
        "description": (
            "winter lifestyle photography, snow-covered outdoor scene or cosy chalet interior, "
            "cool crisp light, festive or adventurous winter energy, frosty atmospheric mood"
        ),
        "lighting": "cool diffused winter light, snow reflection",
        "camera":   "medium to wide, landscape context",
        "mood":     "serene, festive",
        "category_tags": ["footwear", "apparel", "accessories"],
    },
    # ── Wellness & Fitness ────────────────────────────────────────────────────
    {
        "id": "sports_fitness",
        "label": "Sports & Fitness",
        "description": (
            "dynamic sports and fitness photography, professional gym or stadium environment, "
            "powerful athletic energy, motivational composition, dramatic sports lighting"
        ),
        "lighting": "overhead sports lighting, dramatic shadows",
        "camera":   "low angle, wide angle hero",
        "mood":     "powerful, motivational",
        "category_tags": ["footwear", "apparel"],
    },
    {
        "id": "gym_workout",
        "label": "Gym & Workout",
        "description": (
            "intense gym workout lifestyle photography, professional fitness facility, "
            "overhead industrial lighting on polished floors, raw athletic motivation and effort"
        ),
        "lighting": "industrial overhead, hard directional light",
        "camera":   "low angle, gritty perspective",
        "mood":     "intense, raw",
        "category_tags": ["footwear", "apparel"],
    },
    {
        "id": "running_marathon",
        "label": "Running & Marathon",
        "description": (
            "outdoor running and marathon lifestyle photography, open road or park trail setting, "
            "natural daylight with movement blur, endurance and determination energy"
        ),
        "lighting": "natural daylight, slight motion blur",
        "camera":   "panning shot, mid-action",
        "mood":     "determined, endurance",
        "category_tags": ["footwear", "apparel"],
    },
    {
        "id": "yoga_wellness",
        "label": "Yoga & Wellness",
        "description": (
            "serene yoga and wellness lifestyle photography, sunlit studio or peaceful outdoor space, "
            "soft natural light with neutral tones, mindful calm and balance aesthetic"
        ),
        "lighting": "soft natural window light or filtered outdoor",
        "camera":   "medium close-up, still and intentional",
        "mood":     "serene, mindful",
        "category_tags": ["apparel", "beauty", "skincare"],
    },
    # ── Home & Interiors ──────────────────────────────────────────────────────
    {
        "id": "home_comfort",
        "label": "Home & Comfort",
        "description": (
            "cosy home lifestyle photography, warm inviting living room or kitchen interior, "
            "soft ambient light, hygge comfort aesthetic, domestic everyday warmth"
        ),
        "lighting": "soft warm ambient, window side-light",
        "camera":   "medium eye-level, slightly tilted",
        "mood":     "warm, cosy",
        "category_tags": ["home", "skincare", "beauty", "electronics"],
    },
    {
        "id": "luxury_lifestyle",
        "label": "Luxury Lifestyle",
        "description": (
            "aspirational luxury lifestyle photography, penthouse terrace or designer interior setting, "
            "soft diffused light with premium feel, gold and neutral tones, affluent high-end aesthetic"
        ),
        "lighting": "soft diffused premium studio or window light",
        "camera":   "hero angle, slightly elevated",
        "mood":     "aspirational, premium",
        "category_tags": ["jewelry", "accessories", "beauty", "skincare", "apparel"],
    },
    # ── Social & Events ───────────────────────────────────────────────────────
    {
        "id": "festival_party",
        "label": "Festival & Party",
        "description": (
            "vibrant festival and party lifestyle photography, colourful outdoor event atmosphere, "
            "bokeh party lights, celebratory crowd energy, joyful and energetic composition"
        ),
        "lighting": "festival stage lights, bokeh",
        "camera":   "close-up candid, shallow depth",
        "mood":     "celebratory, energetic",
        "category_tags": ["footwear", "apparel", "accessories"],
    },
    {
        "id": "wedding_formal",
        "label": "Wedding & Formal",
        "description": (
            "elegant wedding and formal event photography, romantic floral décor and soft candlelight, "
            "sophisticated polished setting, tender and ceremonious atmosphere"
        ),
        "lighting": "soft candlelight and fairy lights",
        "camera":   "3/4 portrait angle, soft depth",
        "mood":     "elegant, romantic",
        "category_tags": ["jewelry", "apparel", "accessories", "beauty"],
    },
    {
        "id": "date_night",
        "label": "Date Night",
        "description": (
            "romantic date-night lifestyle photography, upscale restaurant or glowing city evening backdrop, "
            "warm candlelit amber tones, sophisticated and intimate atmosphere"
        ),
        "lighting": "warm candlelit amber",
        "camera":   "intimate medium shot",
        "mood":     "romantic, sophisticated",
        "category_tags": ["jewelry", "apparel", "accessories", "beauty"],
    },
    {
        "id": "brunch_social",
        "label": "Brunch & Social",
        "description": (
            "trendy brunch and social lifestyle photography, stylish café or rooftop terrace setting, "
            "bright natural light with lush greenery, social connection and food culture energy"
        ),
        "lighting": "bright natural midday, soft fill",
        "camera":   "flat lay or over-shoulder medium shot",
        "mood":     "social, bright",
        "category_tags": ["apparel", "accessories", "beauty", "skincare"],
    },
    {
        "id": "cultural_ethnic",
        "label": "Cultural & Heritage",
        "description": (
            "rich cultural lifestyle photography, vibrant traditional festival or cultural landmark setting, "
            "warm jewel tones, celebration of heritage and cultural identity"
        ),
        "lighting": "warm festive light, jewel tones",
        "camera":   "wide context or close-up detail",
        "mood":     "celebratory, heritage",
        "category_tags": ["apparel", "jewelry", "accessories"],
    },
    {
        "id": "vintage_retro",
        "label": "Vintage & Retro",
        "description": (
            "nostalgic vintage and retro lifestyle photography, 1970s–90s aesthetic styling, "
            "film-grain texture, faded warm colour grading, classic retro composition"
        ),
        "lighting": "warm film-graded tones",
        "camera":   "vintage medium-format square crop",
        "mood":     "nostalgic, retro",
        "category_tags": ["footwear", "apparel", "accessories"],
    },
    # ── Studio / Editorial (extra) ─────────────────────────────────────────────
    {
        "id": "studio_minimal",
        "label": "Studio Minimal",
        "description": (
            "clean minimal studio product photography, pure white seamless sweep background, "
            "soft box lighting, no distractions, pure e-commerce clarity"
        ),
        "lighting": "soft-box studio, neutral balanced",
        "camera":   "eye level, centered, filling 80% of frame",
        "mood":     "clean, minimal",
        "category_tags": [
            "footwear", "apparel", "accessories", "jewelry",
            "beauty", "skincare", "electronics", "home", "generic",
        ],
    },
    {
        "id": "editorial_hero",
        "label": "Editorial Hero",
        "description": (
            "high-fashion editorial hero shot, dramatic directional studio lighting, "
            "bold composition with intentional negative space, glossy magazine aesthetic"
        ),
        "lighting": "directional hard light, crisp shadows",
        "camera":   "low angle or bird's-eye hero",
        "mood":     "bold, editorial",
        "category_tags": ["footwear", "apparel", "accessories", "jewelry", "beauty"],
    },
    {
        "id": "office_business",
        "label": "Office & Business",
        "description": (
            "professional office and business lifestyle photography, clean modern open-plan workspace, "
            "neutral corporate tones, confident productive business atmosphere"
        ),
        "lighting": "cool office ambient, natural window fill",
        "camera":   "slightly elevated, desk or shelf context",
        "mood":     "professional, productive",
        "category_tags": ["electronics", "accessories", "apparel"],
    },
    {
        "id": "skincare_flat_lay",
        "label": "Skincare Flat Lay",
        "description": (
            "editorial skincare flat-lay photography, marble or linen surface, "
            "botanicals and ingredient props arranged artfully around the product, "
            "soft overhead natural light"
        ),
        "lighting": "soft overhead natural light, no harsh shadows",
        "camera":   "direct overhead, top-down flat lay",
        "mood":     "clean, botanical",
        "category_tags": ["skincare", "beauty"],
    },
    {
        "id": "jewelry_macro",
        "label": "Jewelry Macro",
        "description": (
            "luxury jewelry macro photography on dark velvet or gradient background, "
            "precision studio lighting capturing gemstone sparkle and metallic refraction, "
            "dramatic close-up detail"
        ),
        "lighting": "precision ring light, sparkle enhancement",
        "camera":   "macro close-up, shallow depth of field",
        "mood":     "luxury, dramatic",
        "category_tags": ["jewelry"],
    },
    {
        "id": "electronics_tech",
        "label": "Tech & Electronics",
        "description": (
            "premium tech product photography on dark or gradient background, "
            "precision studio lighting with sharp specular highlights, "
            "sleek modern presentation on reflective surface"
        ),
        "lighting": "precision studio, specular highlights",
        "camera":   "3/4 angled, slightly elevated",
        "mood":     "sleek, premium",
        "category_tags": ["electronics"],
    },
    {
        "id": "home_room",
        "label": "Home Room Context",
        "description": (
            "product styled within a fully decorated room scene, "
            "contemporary interior design with warm natural light, "
            "product as focal point within a coherent living space"
        ),
        "lighting": "warm room ambient, window side-light",
        "camera":   "wide angle, room context",
        "mood":     "warm, aspirational",
        "category_tags": ["home"],
    },
    {
        "id": "golden_hour",
        "label": "Golden Hour",
        "description": (
            "outdoor golden-hour magic light, long warm shadows, "
            "sun low on the horizon bathing scene in amber-gold tones, "
            "timeless romantic outdoor atmosphere"
        ),
        "lighting": "golden hour, low sun, long warm shadows",
        "camera":   "medium wide, slightly backlit",
        "mood":     "romantic, timeless",
        "category_tags": [
            "footwear", "apparel", "accessories", "jewelry", "beauty",
        ],
    },
    {
        "id": "rainy_moody",
        "label": "Rainy & Moody",
        "description": (
            "moody rainy atmosphere, wet reflective street surfaces, "
            "rain streaks on glass or pavement, dramatic overcast sky, "
            "atmospheric editorial lifestyle"
        ),
        "lighting": "overcast diffused, neon reflections on wet surfaces",
        "camera":   "medium shot, slight low angle",
        "mood":     "moody, cinematic",
        "category_tags": ["footwear", "apparel", "accessories"],
    },
    {
        "id": "diwali_festival",
        "label": "Diwali Festival",
        "description": (
            "vibrant Diwali celebration with diyas, rangoli patterns and warm golden festival light, "
            "festive and joyful atmosphere, rich warm gold and jewel-toned colour palette"
        ),
        "lighting": "warm diya candlelight, gold tones",
        "camera":   "medium shot, soft depth",
        "mood":     "festive, joyful",
        "category_tags": ["jewelry", "apparel", "accessories", "beauty"],
    },
    {
        "id": "christmas_winter",
        "label": "Christmas & Winter",
        "description": (
            "festive Christmas scene with decorated tree, warm fairy lights and snow-dusted props, "
            "cosy winter holiday atmosphere, warm bokeh and festive cheer"
        ),
        "lighting": "fairy lights, warm bokeh",
        "camera":   "medium close-up, shallow depth",
        "mood":     "festive, warm",
        "category_tags": [
            "footwear", "apparel", "accessories", "jewelry",
            "beauty", "skincare", "electronics", "home",
        ],
    },
]


class SceneLibrary:
    """
    Immutable catalog of scene definitions.

    Use get(scene_id) to retrieve a specific scene, or
    for_category(category_id) to get scenes relevant to a category.
    """

    def __init__(self) -> None:
        self._scenes: dict[str, SceneDefinition] = {}
        for entry in _SCENES:
            defn = SceneDefinition(**entry)
            self._scenes[defn.id] = defn

    def get(self, scene_id: str) -> Optional[SceneDefinition]:
        return self._scenes.get(scene_id)

    def all(self) -> list[SceneDefinition]:
        return list(self._scenes.values())

    def ids(self) -> list[str]:
        return list(self._scenes.keys())

    def for_category(self, category_id: str) -> list[SceneDefinition]:
        """Return scenes tagged for the given category, ordered by relevance."""
        exact   = [s for s in self._scenes.values() if category_id in s.category_tags]
        generic = [s for s in self._scenes.values()
                   if "generic" in s.category_tags and s not in exact]
        return exact + generic

    def label_map(self) -> dict[str, str]:
        """Map of scene_id → label for UI dropdowns."""
        return {s.id: s.label for s in self._scenes.values()}


_library: Optional[SceneLibrary] = None


def get_scene_library() -> SceneLibrary:
    global _library
    if _library is None:
        _library = SceneLibrary()
    return _library
