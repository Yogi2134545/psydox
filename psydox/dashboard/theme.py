"""Psydox dashboard theme system — 7 themes + custom accent support."""
from __future__ import annotations

from dataclasses import dataclass
import streamlit as st


@dataclass(frozen=True)
class Theme:
    key:             str
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
        key="midnight", name="Midnight",
        bg_primary="#0a0a0f", bg_secondary="#12121a", bg_card="#1a1a26",
        accent_primary="#7c3aed", accent_secondary="#06b6d4",
        text_primary="#f1f5f9", text_secondary="#94a3b8",
        border="#2e2e45", success="#10b981", warning="#f59e0b", danger="#ef4444",
        gradient="linear-gradient(135deg,#7c3aed 0%,#06b6d4 100%)",
    ),
    "neon_lime": Theme(
        key="neon_lime", name="Neon Lime",
        bg_primary="#050a00", bg_secondary="#0a1400", bg_card="#121f00",
        accent_primary="#84cc16", accent_secondary="#22d3ee",
        text_primary="#f7fee7", text_secondary="#a3e635",
        border="#1e3300", success="#4ade80", warning="#facc15", danger="#f87171",
        gradient="linear-gradient(135deg,#84cc16 0%,#22d3ee 100%)",
    ),
    "ice_blue": Theme(
        key="ice_blue", name="Ice Blue",
        bg_primary="#010a14", bg_secondary="#051524", bg_card="#0a2035",
        accent_primary="#38bdf8", accent_secondary="#818cf8",
        text_primary="#e0f2fe", text_secondary="#7dd3fc",
        border="#1e3a5f", success="#34d399", warning="#fb923c", danger="#f43f5e",
        gradient="linear-gradient(135deg,#38bdf8 0%,#818cf8 100%)",
    ),
    "rose_gold": Theme(
        key="rose_gold", name="Rose Gold",
        bg_primary="#0f0507", bg_secondary="#1a0a0e", bg_card="#261014",
        accent_primary="#fb7185", accent_secondary="#f9a8d4",
        text_primary="#fff1f2", text_secondary="#fda4af",
        border="#44202b", success="#86efac", warning="#fde047", danger="#ef4444",
        gradient="linear-gradient(135deg,#fb7185 0%,#f9a8d4 100%)",
    ),
    "lavender": Theme(
        key="lavender", name="Lavender",
        bg_primary="#0b080f", bg_secondary="#130e1a", bg_card="#1d1528",
        accent_primary="#a78bfa", accent_secondary="#c084fc",
        text_primary="#f5f3ff", text_secondary="#c4b5fd",
        border="#3b2d5c", success="#86efac", warning="#fde047", danger="#f87171",
        gradient="linear-gradient(135deg,#a78bfa 0%,#ec4899 100%)",
    ),
    "peach": Theme(
        key="peach", name="Peach",
        bg_primary="#100805", bg_secondary="#1a0f0a", bg_card="#261710",
        accent_primary="#fb923c", accent_secondary="#fbbf24",
        text_primary="#fff7ed", text_secondary="#fdba74",
        border="#4a2510", success="#86efac", warning="#fde047", danger="#f43f5e",
        gradient="linear-gradient(135deg,#fb923c 0%,#fbbf24 100%)",
    ),
    "graphite": Theme(
        key="graphite", name="Graphite",
        bg_primary="#0d0d0d", bg_secondary="#161616", bg_card="#1f1f1f",
        accent_primary="#d1d5db", accent_secondary="#9ca3af",
        text_primary="#f9fafb", text_secondary="#9ca3af",
        border="#2d2d2d", success="#4ade80", warning="#fbbf24", danger="#f87171",
        gradient="linear-gradient(135deg,#6b7280 0%,#d1d5db 100%)",
    ),
}

_DEFAULT_KEY = "midnight"


class ThemeManager:

    def current_key(self) -> str:
        return st.session_state.get("psydox_theme", _DEFAULT_KEY)

    @property
    def current(self) -> Theme:
        key = self.current_key()
        return _THEMES.get(key, _THEMES[_DEFAULT_KEY])

    def set(self, key: str) -> None:
        normalized = key.lower().replace(" ", "_")
        if normalized in _THEMES:
            st.session_state.psydox_theme = normalized

    def all_themes(self) -> list[Theme]:
        return list(_THEMES.values())

    def inject_css(self, accent_override: str = "") -> None:
        t = self.current
        accent = accent_override if accent_override else t.accent_primary
        st.markdown(f"""
<style>
:root {{
  --bg-primary:       {t.bg_primary};
  --bg-secondary:     {t.bg_secondary};
  --bg-card:          {t.bg_card};
  --accent-primary:   {accent};
  --accent-secondary: {t.accent_secondary};
  --text-primary:     {t.text_primary};
  --text-secondary:   {t.text_secondary};
  --border:           {t.border};
  --success:          {t.success};
  --warning:          {t.warning};
  --danger:           {t.danger};
  --gradient:         {t.gradient};
}}
.stApp {{ background: var(--bg-primary) !important; color: var(--text-primary) !important; }}
section[data-testid="stSidebar"] {{
  background: var(--bg-secondary) !important;
  border-right: 1px solid var(--border) !important;
}}
/* Cards */
.psx-card {{
  background: var(--bg-card); border: 1px solid var(--border); border-radius: 14px;
  padding: 20px; margin-bottom: 16px; transition: border-color 0.2s;
}}
.psx-card:hover {{ border-color: var(--accent-primary); }}
/* Metrics */
div[data-testid="stMetric"] {{
  background: var(--bg-card) !important; border: 1px solid var(--border) !important;
  border-radius: 12px !important; padding: 14px !important;
}}
div[data-testid="stMetricValue"] {{ color: var(--text-primary) !important; }}
div[data-testid="stMetricLabel"] {{ color: var(--text-secondary) !important; }}
/* Buttons */
.stButton > button {{
  background: var(--gradient) !important; color: white !important;
  border: none !important; border-radius: 8px !important; font-weight: 600 !important;
}}
.stButton > button:hover {{ opacity: 0.85 !important; transform: translateY(-1px); }}
/* Feature cards */
.psx-feat {{
  background: var(--bg-card); border: 1px solid var(--border); border-radius: 14px;
  padding: 18px; text-align: center; transition: all 0.2s; cursor: pointer;
}}
.psx-feat:hover {{
  border-color: var(--accent-primary);
  background: color-mix(in srgb, var(--accent-primary) 10%, var(--bg-card));
  transform: translateY(-3px);
  box-shadow: 0 8px 24px color-mix(in srgb, var(--accent-primary) 25%, transparent);
}}
.psx-feat-icon {{ font-size: 2.2rem; margin-bottom: 8px; }}
.psx-feat-name {{ font-weight: 700; color: var(--text-primary); font-size: 0.95rem; }}
.psx-feat-desc {{ font-size: 0.76rem; color: var(--text-secondary); margin-top: 4px; }}
/* Gradient text */
.psx-gradient-text {{
  background: var(--gradient);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  background-clip: text; font-weight: 800;
}}
/* Badges */
.psx-badge {{
  display: inline-block; padding: 2px 10px; border-radius: 999px;
  font-size: 0.72rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em;
}}
.psx-ai    {{ background: color-mix(in srgb,var(--accent-primary) 20%,transparent); color:var(--accent-primary); }}
.psx-ok    {{ background: color-mix(in srgb,var(--success) 20%,transparent); color:var(--success); }}
.psx-warn  {{ background: color-mix(in srgb,var(--warning) 20%,transparent); color:var(--warning); }}
.psx-error {{ background: color-mix(in srgb,var(--danger) 20%,transparent); color:var(--danger); }}
/* Selectbox / text inputs */
.stSelectbox > div > div, .stTextInput > div > div > input {{
  background: var(--bg-card) !important; color: var(--text-primary) !important;
  border-color: var(--border) !important;
}}
/* Expander */
.streamlit-expanderHeader {{ background: var(--bg-card) !important; border-radius: 8px !important; }}
/* Tabs */
.stTabs [data-baseweb="tab-list"] {{ background: var(--bg-secondary); border-radius: 8px; padding: 4px; }}
.stTabs [data-baseweb="tab"] {{ background: transparent; color: var(--text-secondary); }}
.stTabs [aria-selected="true"] {{
  background: var(--accent-primary) !important; color: white !important;
  border-radius: 6px;
}}
</style>""", unsafe_allow_html=True)


@st.cache_resource
def get_theme_manager() -> ThemeManager:
    return ThemeManager()
