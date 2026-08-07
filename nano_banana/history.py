"""Nano Banana — session history manager."""
import io
import base64
import datetime
import uuid
import streamlit as st
from PIL import Image


_STATE_KEY = "nb_history"


def _thumb_b64(image: Image.Image, size=(120, 120)) -> str:
    """Convert image to base64 thumbnail string."""
    try:
        thumb = image.copy()
        thumb.thumbnail(size, Image.LANCZOS)
        buf = io.BytesIO()
        thumb.save(buf, format="JPEG", quality=70)
        return base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return ""


class HistoryManager:
    def _state(self):
        if _STATE_KEY not in st.session_state:
            st.session_state[_STATE_KEY] = []
        return st.session_state[_STATE_KEY]

    def add(
        self,
        job_type: str,
        original: Image.Image,
        result: Image.Image,
        prompt: str,
        engine: str = "Gemini",
    ) -> dict:
        entry = {
            "id": str(uuid.uuid4())[:8],
            "job_type": job_type,
            "original_thumb": _thumb_b64(original),
            "result_thumb": _thumb_b64(result),
            "prompt": prompt[:200],
            "engine": engine,
            "timestamp": datetime.datetime.now().strftime("%H:%M:%S"),
            "status": "success",
        }
        self._state().append(entry)
        return entry

    def get_all(self) -> list:
        return list(self._state())

    def clear(self):
        st.session_state[_STATE_KEY] = []

    def count(self) -> int:
        return len(self._state())
