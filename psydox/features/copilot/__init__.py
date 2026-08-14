"""
Psydox Feature — Copilot (AI Studio) & Plans

Minimal scaffold that registers a "copilot" feature and provides a lightweight
plans manager (in-memory + DB/pluggable later). This is a safe, non-invasive
MVP: no runtime changes to behavior unless the AI studio UI requests this
feature's manifest or calls into the plans API.

Files added:
 - psydox/features/copilot/__init__.py
 - psydox/features/copilot/service.py
 - psydox/features/copilot/plans.py

The feature is discovered by the existing auto-discovery system.
"""

__version__ = "0.1.0"
