"""
Psydox Dashboard Preferences

Per-user dashboard customization.  Persisted to SQLite, with st.session_state
as the working cache.

Settings:
  theme           — theme key
  layout          — "compact" | "comfortable"
  accent          — hex accent override or ""
  hidden_widgets  — list of widget IDs to hide
  widget_order    — ordered list of widget IDs
  pinned_features — list of feature IDs pinned to Quick Create
  pinned_projects — list of project IDs pinned to top
  time_greeting   — show good morning / afternoon / evening
"""
from __future__ import annotations

import json
import logging
import time
from typing import Optional

import streamlit as st

_log = logging.getLogger("psydox.dashboard.preferences")

_DEFAULTS: dict = {
    "theme":           "midnight",
    "layout":          "comfortable",
    "accent":          "",
    "hidden_widgets":  [],
    "widget_order":    ["metrics", "quick_create", "recent_projects", "recent_jobs", "activity"],
    "pinned_features": [],
    "pinned_projects": [],
    "time_greeting":   True,
}


class DashboardPreferences:

    def __init__(self, user_email: str):
        self._email = user_email
        self._prefs: dict = dict(_DEFAULTS)
        self._loaded = False

    def load(self) -> "DashboardPreferences":
        if self._loaded:
            return self
        # Try session state cache
        key = f"_dash_prefs_{self._email}"
        if key in st.session_state:
            self._prefs.update(st.session_state[key])
            self._loaded = True
            return self
        # Try DB
        try:
            from psydox.storage.database import get_db
            row = get_db().execute(
                "SELECT prefs FROM dashboard_prefs WHERE user_email=?", (self._email,)
            ).fetchone()
            if row:
                saved = json.loads(row[0])
                self._prefs.update(saved)
                st.session_state[key] = dict(self._prefs)
        except Exception as exc:
            _log.debug("DashboardPreferences load failed: %s", exc)
        self._loaded = True
        return self

    def save(self) -> None:
        key = f"_dash_prefs_{self._email}"
        st.session_state[key] = dict(self._prefs)
        try:
            from psydox.storage.database import get_db
            db = get_db()
            db.execute(
                "INSERT OR REPLACE INTO dashboard_prefs (user_email, prefs, updated_at) VALUES (?,?,?)",
                (self._email, json.dumps(self._prefs), time.time()),
            )
            db.commit()
        except Exception as exc:
            _log.debug("DashboardPreferences save failed: %s", exc)

    def get(self, key: str, default=None):
        return self._prefs.get(key, _DEFAULTS.get(key, default))

    def set(self, key: str, value) -> None:
        self._prefs[key] = value

    def theme(self) -> str:
        return self._prefs.get("theme", "midnight")

    def layout(self) -> str:
        return self._prefs.get("layout", "comfortable")

    def is_widget_visible(self, widget_id: str) -> bool:
        return widget_id not in self._prefs.get("hidden_widgets", [])

    def toggle_widget(self, widget_id: str) -> None:
        hidden = list(self._prefs.get("hidden_widgets", []))
        if widget_id in hidden:
            hidden.remove(widget_id)
        else:
            hidden.append(widget_id)
        self._prefs["hidden_widgets"] = hidden

    def widget_order(self) -> list[str]:
        return self._prefs.get("widget_order", _DEFAULTS["widget_order"])

    def pin_feature(self, feature_id: str) -> None:
        pins = list(self._prefs.get("pinned_features", []))
        if feature_id not in pins:
            pins.append(feature_id)
        self._prefs["pinned_features"] = pins

    def unpin_feature(self, feature_id: str) -> None:
        pins = [f for f in self._prefs.get("pinned_features", []) if f != feature_id]
        self._prefs["pinned_features"] = pins

    def pinned_features(self) -> list[str]:
        return self._prefs.get("pinned_features", [])

    def to_dict(self) -> dict:
        return dict(self._prefs)


def get_preferences(user_email: str) -> DashboardPreferences:
    return DashboardPreferences(user_email).load()
