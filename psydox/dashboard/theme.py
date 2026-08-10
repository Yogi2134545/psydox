"""Psydox dashboard theme system — CSS injection for Gen-Z premium look."""
from dataclasses import dataclass
import streamlit as st


@dataclass(frozen=True)
class Theme:
    name:            str
    bg_primary:      str
    bg_secondary:    str
    bg_card:         str
    accent_primary:  str
    accent_secondary: str
    text_primary:    str
    text_secondary:  str
    border:          str
    success:         str
    warning:         str
    danger:          str
    gradient:        str


_THEMES: dict[str, Theme] = {
    "midnight": Theme(
        name="Midnight",
        bg_primary="#0a0a0f",
        bg_secondary="#12121a",
        bg_card="#1a1a26",
        accent_primary="#7c3aed",
        accent_secondary="#06b6d4",
        text_primary="#f1f5f9",
        text_secondary="#94a3b8",
        border="#2e2e45",
        success="#10b981",
        warning="#f59e0b",
        danger="#ef4444",
        gradient="linear-gradient(135deg,#7c3aed 0%,#06b6d4 100%)",
    ),
    "neon_lime": Theme(
        name="Neon Lime",
        bg_primary="#050a00",
        bg_secondary="#0a1400",
        bg_card="#121f00",
        accent_primary="#84cc16",
        accent_secondary="#22d3ee",
        text_primary="#f7fee7",
        text_secondary="#a3e635",
        border="#1e3300",
        success="#4ade80",
        warning="#facc15",
        danger="#f87171",
        gradient="linear-gradient(135deg,#84cc16 0%,#22d3ee 100%)",
    ),
    "ice_blue": Theme(
        name="Ice Blue",
        bg_primary="#010a14",
        bg_secondary="#051524",
        bg_card="#0a2035",
        accent_primary="#38bdf8",
        accent_secondary="#818cf8",
        text_primary="#e0f2fe",
        text_secondary="#7dd3fc",
        border="#1e3a5f",
        success="#34d399",
        warning="#fb923c",
        danger="#f43f5e",
        gradient="linear-gradient(135deg,#38bdf8 0%,#818cf8 100%)",
    ),
    "rose_gold": Theme(
        name="Rose Gold",
        bg_primary="#0f0507",
        bg_secondary="#1a0a0e",
        bg_card="#261014",
        accent_primary="#fb7185",
        accent_secondary="#f9a8d4",
        text_primary="#fff1f2",
        text_secondary="#fda4af",
        border="#44202b",
        success="#86efac",
        warning="#fde047",
        danger="#ef4444",
        gradient="linear-gradient(135deg,#fb7185 0%,#f9a8d4 100%)",
    ),
}

_DEFAULT_THEME = "midnight"


class ThemeManager:
    def __init__(self):
        if "psydox_theme" not in st.session_state:
            st.session_state.psydox_theme = _DEFAULT_THEME

    @property
    def current(self) -> Theme:
        return _THEMES.get(st.session_state.get("psydox_theme", _DEFAULT_THEME), _THEMES[_DEFAULT_THEME])

    def set(self, name: str) -> None:
        if name in _THEMES:
            st.session_state.psydox_theme = name

    def all_themes(self) -> list[Theme]:
        return list(_THEMES.values())

    def inject_css(self) -> None:
        t = self.current
        st.markdown(f"""
<style>
:root {{
    --bg-primary:      {t.bg_primary};
    --bg-secondary:    {t.bg_secondary};
    --bg-card:         {t.bg_card};
    --accent-primary:  {t.accent_primary};
    --accent-secondary:{t.accent_secondary};
    --text-primary:    {t.text_primary};
    --text-secondary:  {t.text_secondary};
    --border:          {t.border};
    --success:         {t.success};
    --warning:         {t.warning};
    --danger:          {t.danger};
    --gradient:        {t.gradient};
}}
.stApp {{
    background: var(--bg-primary) !important;
    color: var(--text-primary) !important;
}}
section[data-testid="stSidebar"] {{
    background: var(--bg-secondary) !important;
    border-right: 1px solid var(--border) !important;
}}
.psydox-card {{
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 20px;
    margin-bottom: 16px;
    transition: border-color 0.2s;
}}
.psydox-card:hover {{ border-color: var(--accent-primary); }}
.psydox-metric {{
    text-align: center;
    padding: 16px;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 12px;
}}
.psydox-metric .value {{
    font-size: 2rem;
    font-weight: 700;
    background: var(--gradient);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
}}
.psydox-metric .label {{
    font-size: 0.8rem;
    color: var(--text-secondary);
    margin-top: 4px;
}}
.psydox-badge {{
    display: inline-block;
    padding: 2px 10px;
    border-radius: 999px;
    font-size: 0.72rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}}
.psydox-badge-ai    {{ background: color-mix(in srgb, var(--accent-primary) 20%, transparent); color: var(--accent-primary); }}
.psydox-badge-ok    {{ background: color-mix(in srgb, var(--success) 20%, transparent);         color: var(--success); }}
.psydox-badge-warn  {{ background: color-mix(in srgb, var(--warning) 20%, transparent);         color: var(--warning); }}
.psydox-badge-error {{ background: color-mix(in srgb, var(--danger) 20%, transparent);          color: var(--danger); }}
.psydox-feature-btn {{
    width: 100%;
    padding: 18px;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 14px;
    text-align: center;
    cursor: pointer;
    transition: all 0.2s;
}}
.psydox-feature-btn:hover {{
    border-color: var(--accent-primary);
    background: color-mix(in srgb, var(--accent-primary) 8%, var(--bg-card));
    transform: translateY(-2px);
}}
.psydox-feature-icon {{ font-size: 2rem; margin-bottom: 8px; }}
.psydox-feature-name {{ font-weight: 600; color: var(--text-primary); }}
.psydox-feature-desc {{ font-size: 0.78rem; color: var(--text-secondary); margin-top: 4px; }}
div[data-testid="stMetric"] {{
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 14px;
}}
.stButton>button {{
    background: var(--gradient);
    color: white;
    border: none;
    border-radius: 8px;
    font-weight: 600;
}}
.stButton>button:hover {{ opacity: 0.85; }}
</style>""", unsafe_allow_html=True)


@st.cache_resource
def get_theme_manager() -> ThemeManager:
    return ThemeManager()
