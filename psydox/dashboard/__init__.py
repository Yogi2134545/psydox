from .theme import ThemeManager, get_theme_manager
from .preferences import DashboardPreferences, get_preferences
from .widgets import (
    render_hero, render_stats_row, render_quick_create,
    render_recent_jobs, render_recent_projects, render_ai_usage,
    WIDGET_REGISTRY,
)
from .page import render_dashboard

__all__ = [
    "ThemeManager", "get_theme_manager",
    "DashboardPreferences", "get_preferences",
    "render_hero", "render_stats_row", "render_quick_create",
    "render_recent_jobs", "render_recent_projects", "render_ai_usage",
    "WIDGET_REGISTRY", "render_dashboard",
]
