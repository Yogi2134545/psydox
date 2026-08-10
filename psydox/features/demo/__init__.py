"""
Demo Feature — proves the plugin architecture works.
Register this → appears automatically in the dashboard.
Disable via: ENABLE_DEMO_FEATURE=false
Remove registration call → disappears cleanly.
"""
from .service import DemoFeature
__all__ = ["DemoFeature"]
