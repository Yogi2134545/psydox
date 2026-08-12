"""Nano Banana AI Studio — Streamlit UI renderer."""
import io
import time
import base64
import datetime
import streamlit as st
from PIL import Image

from .settings import (
    BACKGROUND_OPTIONS,
    LIFESTYLE_OPTIONS,
    MODEL_OPTIONS,
    STYLE_PRESETS,
    EXPORT_FORMATS,
    ENHANCEMENT_OPTIONS,
    LIGHTING_OPTIONS,
    SHADOW_OPTIONS,
    SCENE_OPTIONS,
    GOOGLE_API_KEY,
)
from .engine import NanoBananaEngine
from .history import HistoryManager
from .export import Exporter
from .prompt_builder import build_from_preset


# ── Session state helpers ─────────────────────────────────────────────────────

def _init_nb_state():
    defaults = {
        "nb_uploaded_image": None,
        "nb_result": None,
        "nb_result_prompt": "",
        "nb_result_mode": "",
        "nb_api_calls": 0,
        "nb_gen_time": 0.0,
        "nb_errors": 0,
        "nb_batch_result": None,
        "nb_copied_prompt": "",
        "nb_angle_results": [],
        "nb_angle_count": 1,
        "nb_packshot_results": [],
        "nb_packshot_ref_bytes": None,
        "nb_packshot_product_desc": "",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def _get_image() -> Image.Image:
    return st.session_state.get("nb_uploaded_image")


def _set_result(img: Image.Image, prompt: str, mode: str):
    st.session_state.nb_result = img
    st.session_state.nb_result_prompt = prompt
    st.session_state.nb_result_mode = mode


def _img_to_b64(img: Image.Image, fmt="JPEG", quality=85) -> str:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format=fmt, quality=quality)
    return base64.b64encode(buf.getvalue()).decode()


def _show_before_after(original: Image.Image, result: Image.Image, labels=("Original", "Result")):
    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"**{labels[0]}**")
        st.image(original, use_container_width=True)
        st.caption(f"{original.width}×{original.height}px")
    with col2:
        st.markdown(f"**{labels[1]}**")
        st.image(result, use_container_width=True)
        st.caption(f"{result.width}×{result.height}px")


# ── Output Ratio ─────────────────────────────────────────────────────────────
_RATIO_OPTIONS = {
    "Original":           None,
    "1:1  (1080×1080)":   (1080, 1080),
    "4:5  (1080×1350)":   (1080, 1350),
    "3:4  (810×1080)":    (810,  1080),
    "9:16 (1080×1920)":   (1080, 1920),
    "16:9 (1920×1080)":   (1920, 1080),
    "2:3  (720×1080)":    (720,  1080),
    "3:2  (1080×720)":    (1080, 720),
    "Custom W×H":         "custom",
}


def _apply_ratio(src, target_wh) -> bytes:
    """Fit-inside + white-pad src (PIL.Image or bytes) to target_wh. Returns JPEG bytes."""
    try:
        from PIL import Image as _PIL
        img = (_PIL.open(io.BytesIO(src)) if isinstance(src, bytes) else src).convert("RGB")
        if target_wh:
            tw, th = target_wh
            img.thumbnail((tw, th), _PIL.LANCZOS)
            canvas = _PIL.new("RGB", (tw, th), (255, 255, 255))
            canvas.paste(img, ((tw - img.width) // 2, (th - img.height) // 2))
            img = canvas
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=92)
        return buf.getvalue()
    except Exception:
        if isinstance(src, bytes):
            return src
        try:
            buf = io.BytesIO()
            src.convert("RGB").save(buf, "JPEG", quality=92)
            return buf.getvalue()
        except Exception:
            return b""


def _ratio_to_pil(src, target_wh) -> Image.Image:
    """Apply ratio and return PIL Image."""
    data = _apply_ratio(src, target_wh)
    return Image.open(io.BytesIO(data)).convert("RGB")


def _ratio_prompt_suffix(ratio_label: str, target_wh) -> str:
    """Prompt suffix for the selected ratio."""
    if not target_wh:
        return ""
    tw, th = target_wh
    short = ratio_label.split("(")[0].strip()
    return (
        f"\nAspect Ratio: {short}. "
        f"Resolution: {tw}×{th}. "
        "Maintain composition without cropping the product."
    )


def _show_packshot_gallery(results: list, engine, product_desc: str, ref_bytes: bytes, key_prefix: str):
    """Render a packshot gallery with per-image download + regenerate, plus ZIP/sheet/PDF export."""
    from .api_client import ANGLE_VIEWS as _AV, _build_angle_prompt as _bap
    good_n  = sum(1 for r in results if r.get("bytes"))
    total_n = len(results)

    if not results:
        return

    orig = _get_image()
    if orig:
        _c = st.columns([1, 4])
        with _c[0]:
            st.markdown("**Original**")
            st.image(orig, use_container_width=True)

    st.markdown("**Generated Angles**")
    st.markdown("---")

    cols_per_row = 3
    for _rs in range(0, total_n, cols_per_row):
        _row = results[_rs:_rs + cols_per_row]
        _rc  = st.columns(cols_per_row)
        for _ci, _item in enumerate(_row):
            _idx = _rs + _ci
            with _rc[_ci]:
                st.markdown(f"**{_item['name']}**")
                if _item.get("bytes"):
                    st.image(_item["bytes"], use_container_width=True)
                    st.download_button(
                        f"⬇ {_item['label']}.jpg",
                        data=_item["bytes"],
                        file_name=f"{_item['key']}.jpg",
                        mime="image/jpeg",
                        key=f"{key_prefix}_dl_{_item['key']}",
                        use_container_width=True,
                    )
                else:
                    st.error("Failed")
                    if _item.get("error"):
                        st.caption(_item["error"][:120])
                if ref_bytes and st.button("🔄 Retry", key=f"{key_prefix}_regen_{_item['key']}",
                                           use_container_width=True):
                    with st.spinner(f"Regenerating {_item['name']}…"):
                        try:
                            _ad = next((a for a in _AV if a["key"] == _item["key"]), None)
                            if _ad:
                                _nb = engine.client.generate_image(_bap(product_desc, _ad), ref_bytes)
                                results[_idx]["bytes"] = _nb
                                results[_idx]["error"] = None
                                st.session_state.nb_packshot_results = results
                        except Exception as _re:
                            results[_idx]["error"] = str(_re)
                            st.session_state.nb_packshot_results = results
                    st.rerun()

    st.markdown("---")
    if good_n > 0:
        st.markdown("#### ⬇ Export")
        _ec1, _ec2, _ec3 = st.columns(3)
        with _ec1:
            _zip = _build_packshot_zip(results)
            st.download_button(
                f"📦 ZIP ({good_n} images)",
                data=_zip, file_name="psydox_packshot.zip",
                mime="application/zip", use_container_width=True,
                key=f"{key_prefix}_zip",
            )
            st.caption("Contains: " + ", ".join(r["key"] + ".jpg" for r in results if r.get("bytes")))
        with _ec2:
            _sh = _build_contact_sheet(results)
            if _sh:
                st.download_button(
                    "🖼 Contact Sheet",
                    data=_sh, file_name="psydox_contact_sheet.jpg",
                    mime="image/jpeg", use_container_width=True,
                    key=f"{key_prefix}_sheet",
                )
                st.image(_sh, caption="Contact Sheet", use_container_width=True)
        with _ec3:
            try:
                from PIL import Image as _PPIL
                _pi = [_PPIL.open(io.BytesIO(r["bytes"])).convert("RGB") for r in results if r.get("bytes")]
                if _pi:
                    _pb = io.BytesIO()
                    _pi[0].save(_pb, format="PDF", save_all=True, append_images=_pi[1:])
                    st.download_button(
                        "📄 PDF",
                        data=_pb.getvalue(), file_name="psydox_packshot.pdf",
                        mime="application/pdf", use_container_width=True,
                        key=f"{key_prefix}_pdf",
                    )
            except Exception:
                pass


def _show_angle_grid(results: list, labels: list = None):
    """Show multiple angle results in a 2-column grid with individual download buttons."""
    if not results:
        return
    cols_per_row = 2
    for i in range(0, len(results), cols_per_row):
        row_results = results[i:i + cols_per_row]
        cols = st.columns(cols_per_row)
        for j, item in enumerate(row_results):
            with cols[j]:
                idx = i + j + 1
                label = (labels[idx - 1] if labels and idx - 1 < len(labels)
                         else f"Angle {idx}")
                st.markdown(f"**{label}**")
                if item is None:
                    st.error("Generation failed")
                else:
                    if isinstance(item, bytes):
                        st.image(item, use_container_width=True)
                        st.download_button(
                            f"⬇ Download",
                            data=item,
                            file_name=f"angle_{idx}.jpg",
                            mime="image/jpeg",
                            key=f"nb_dl_angle_{id(results)}_{idx}",
                        )
                    else:
                        buf = io.BytesIO()
                        item.convert("RGB").save(buf, format="JPEG", quality=90)
                        st.image(item, use_container_width=True)
                        st.download_button(
                            f"⬇ Download",
                            data=buf.getvalue(),
                            file_name=f"angle_{idx}.jpg",
                            mime="image/jpeg",
                            key=f"nb_dl_angle_{id(results)}_{idx}",
                        )


def _build_angles_zip(results: list, prefix: str = "angle") -> bytes:
    """Pack multiple image bytes/PIL Images into a ZIP and return bytes."""
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, item in enumerate(results):
            if item is None:
                continue
            if isinstance(item, bytes):
                img_bytes = item
            else:
                ib = io.BytesIO()
                item.convert("RGB").save(ib, format="JPEG", quality=90)
                img_bytes = ib.getvalue()
            zf.writestr(f"{prefix}_{i + 1}.jpg", img_bytes)
    return buf.getvalue()


# ── Packshot helpers ─────────────────────────────────────────────────────────

def _show_packshot_grid(results: list, original_img=None):
    """
    Display a grid of AI-generated packshot angles.
    results: list of {"name", "label", "key", "bytes"|None, "error"|None}
    """
    if not results:
        st.warning("[DBG-9b] _show_packshot_grid called with EMPTY results list")
        return

    st.caption(f"[DBG-9b] _show_packshot_grid: rendering {len(results)} items")

    if original_img:
        st.markdown("**Original**")
        st.image(original_img, width=160)
        st.markdown("**Generated Angles**")

    cols_per_row = 2
    for i in range(0, len(results), cols_per_row):
        row = results[i:i + cols_per_row]
        cols = st.columns(cols_per_row)
        for j, item in enumerate(row):
            with cols[j]:
                st.markdown(f"**{item['name']}**")
                if item.get("bytes"):
                    st.image(item["bytes"], use_container_width=True)
                    st.download_button(
                        f"⬇ {item['label']}",
                        data=item["bytes"],
                        file_name=f"packshot_{item['key']}.jpg",
                        mime="image/jpeg",
                        key=f"nb_dl_ps_{item['key']}_{id(results)}",
                    )
                else:
                    err = item.get("error", "Generation failed")
                    st.error(f"Failed: {err[:120]}")


def _build_packshot_zip(results: list) -> bytes:
    """Pack all successful packshot angles into a single ZIP."""
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in results:
            if item.get("bytes"):
                zf.writestr(f"packshot_{item['key']}.jpg", item["bytes"])
    return buf.getvalue()


def _build_contact_sheet(results: list, cols: int = 3) -> bytes:
    """Composite all successful angles into one contact-sheet JPEG."""
    from PIL import Image as _PIL, ImageDraw

    THUMB = 400
    MARGIN = 20
    LABEL_H = 32

    good = [r for r in results if r.get("bytes")]
    if not good:
        return b""

    rows = (len(good) + cols - 1) // cols
    w = cols * (THUMB + MARGIN) + MARGIN
    h = rows * (THUMB + LABEL_H + MARGIN) + MARGIN
    sheet = _PIL.new("RGB", (w, h), (255, 255, 255))
    draw = ImageDraw.Draw(sheet)

    for idx, item in enumerate(good):
        col = idx % cols
        row = idx // cols
        x = MARGIN + col * (THUMB + MARGIN)
        y = MARGIN + row * (THUMB + LABEL_H + MARGIN)
        try:
            thumb = _PIL.open(io.BytesIO(item["bytes"])).convert("RGB")
            thumb.thumbnail((THUMB, THUMB), _PIL.LANCZOS)
            ox = x + (THUMB - thumb.width) // 2
            sheet.paste(thumb, (ox, y))
        except Exception:
            pass
        draw.text((x, y + THUMB + 4), item["name"], fill=(60, 60, 60))

    out = io.BytesIO()
    sheet.save(out, format="JPEG", quality=90)
    return out.getvalue()


# ── API key warning ───────────────────────────────────────────────────────────

def _api_warning():
    st.warning(
        "GOOGLE_API_KEY is not configured. "
        "Set the environment variable to enable AI features. "
        "PIL-based edits (Editor tab) still work without an API key.",
        icon="⚠️",
    )


# ── ZIP batch helper ──────────────────────────────────────────────────────────

def _process_zip_batch(zip_bytes: bytes, config: dict, engine, progress_cb=None) -> dict:
    """Extract images from a ZIP, run AI generation on each, return results dict with zip_bytes."""
    import zipfile as _zf

    IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
    out_buf = io.BytesIO()
    success = failed = skipped = 0
    entries = []

    with _zf.ZipFile(io.BytesIO(zip_bytes)) as zin:
        names = [n for n in zin.namelist()
                 if not n.startswith("__MACOSX")
                 and any(n.lower().endswith(ext) for ext in IMG_EXTS)]

    total = len(names) * config.get("angles", 1)

    with _zf.ZipFile(out_buf, "w", _zf.ZIP_DEFLATED) as zout:
        done = 0
        for name in names:
            with _zf.ZipFile(io.BytesIO(zip_bytes)) as zin:
                img_bytes = zin.read(name)
            stem = name.rsplit(".", 1)[0].replace("/", "_")
            n_angles = config.get("angles", 1)

            try:
                img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
                ref_buf = io.BytesIO()
                img.convert("RGB").save(ref_buf, format="JPEG", quality=90)
                ref_bytes = ref_buf.getvalue()

                mode = config.get("mode", "background")
                bg_opt = config.get("background_option", "White")

                _batch_ratio = config.get("ratio_wh")
                if n_angles == 1:
                    result_img = engine.bg_gen.replace_background(img, bg_opt, "", "")
                    out_ib = io.BytesIO()
                    result_img.convert("RGB").save(out_ib, format="JPEG", quality=90)
                    final_bytes = _apply_ratio(out_ib.getvalue(), _batch_ratio)
                    zout.writestr(f"{stem}_result.jpg", final_bytes)
                    success += 1
                    done += 1
                else:
                    base_prompt = f"Product photo with {bg_opt} background"
                    angle_results = engine.client.generate_angles(base_prompt, ref_bytes, count=n_angles)
                    for ai, ab in enumerate(angle_results):
                        if ab is not None:
                            zout.writestr(f"{stem}_angle{ai + 1}.jpg", _apply_ratio(ab, _batch_ratio))
                            success += 1
                        else:
                            failed += 1
                        done += 1
            except Exception:
                failed += n_angles
                done += n_angles
            finally:
                if progress_cb:
                    progress_cb(done, total)

    return {
        "total": len(names),
        "success": success,
        "failed": failed,
        "skipped": skipped,
        "zip_bytes": out_buf.getvalue(),
    }


# ── Main render function ──────────────────────────────────────────────────────

def render_nano_banana():
    _init_nb_state()

    engine = NanoBananaEngine()
    history = HistoryManager()
    exporter = Exporter()

    st.markdown("---")
    st.markdown(
        "<div style='background:linear-gradient(135deg,#1a1a2e,#16213e);"
        "padding:16px 24px;border-radius:12px;margin-bottom:16px'>"
        "<span style='font-size:28px'>⚡</span> "
        "<span style='color:#ff6600;font-size:22px;font-weight:bold'>Psydox AI Studio</span>"
        "</div>",
        unsafe_allow_html=True,
    )

    if not GOOGLE_API_KEY:
        _api_warning()

    # ── Image upload ──────────────────────────────────────────────────────────
    # ── Image input (always visible) ─────────────────────────────────────────
    st.markdown("### 📥 Input Image")
    col_up, col_url = st.columns([1, 1])

    with col_up:
        up = st.file_uploader(
            "Upload from device",
            type=["png", "jpg", "jpeg", "webp"],
            key="nb_file_uploader",
            label_visibility="visible",
        )
        if up:
            img = Image.open(up).convert("RGB")
            st.session_state.nb_uploaded_image = img

    with col_url:
        url_input = st.text_input(
            "Or paste image URL",
            key="nb_url_input",
            placeholder="https://example.com/image.jpg",
        )
        if st.button("Load URL", key="nb_url_load"):
            if url_input.strip():
                try:
                    from .validators import validate_url, URLValidationError
                    import requests as _req
                    try:
                        safe_url = validate_url(url_input.strip())
                    except URLValidationError as _ve:
                        st.error(f"URL not allowed: {_ve}")
                        safe_url = None
                    if safe_url:
                        r = _req.get(safe_url, timeout=15,
                                     headers={"User-Agent": "Mozilla/5.0"})
                        r.raise_for_status()
                        img = Image.open(io.BytesIO(r.content)).convert("RGB")
                        st.session_state.nb_uploaded_image = img
                        st.success("Image loaded from URL")
                except Exception as e:
                    st.error(f"Failed to load URL: {e}")

    if st.session_state.nb_uploaded_image:
        img_disp = st.session_state.nb_uploaded_image
        c1, c2, c3 = st.columns([1, 2, 1])
        with c2:
            st.image(img_disp, use_container_width=True,
                     caption=f"{img_disp.width}×{img_disp.height}px")
        if st.button("🗑️ Clear image", key="nb_clear_img"):
            st.session_state.nb_uploaded_image = None
            st.rerun()
    else:
        st.info("Upload an image or paste a URL to get started.")

    # ── Angle count selector ──────────────────────────────────────────────────
    st.markdown("#### 🔄 How many angles / variations to generate?")
    angle_count = st.slider(
        "Angles per image",
        min_value=1, max_value=8, value=1, step=1,
        key="nb_angle_slider",
        help="1 = single result. 2–8 = generate multiple angle variations.",
    )
    st.session_state.nb_angle_count = angle_count
    if angle_count > 1:
        from .api_client import ANGLE_VIEWS as _AV
        _labels = " · ".join(a["label"] for a in _AV[:angle_count])
        st.info(
            f"Will generate **{angle_count} packshot angles** via AI: {_labels}. "
            "Each angle is an independent generation job. "
            "ZIP + contact sheet download included."
        )

    # ── Output Ratio selector ─────────────────────────────────────────────────
    st.markdown("#### 📐 Output Ratio")
    _ro_c1, _ro_c2 = st.columns([3, 2])
    with _ro_c1:
        ratio_label = st.selectbox(
            "Output Ratio",
            list(_RATIO_OPTIONS.keys()),
            key="nb_ratio_label",
            label_visibility="collapsed",
            help="Applied to every generated image across all features.",
        )
    ratio_wh = _RATIO_OPTIONS.get(ratio_label)
    if ratio_wh == "custom":
        with _ro_c2:
            _cw_col, _ch_col = st.columns(2)
            _cw = _cw_col.number_input("W px", 100, 4320, 1080, key="nb_ratio_cw", label_visibility="collapsed")
            _ch = _ch_col.number_input("H px", 100, 5400, 1350, key="nb_ratio_ch", label_visibility="collapsed")
        ratio_wh = (int(_cw), int(_ch))
    elif ratio_wh:
        with _ro_c2:
            tw, th = ratio_wh
            st.info(f"**{tw}×{th}px**", icon="📐")

    st.markdown("---")

    # ── Tabs ──────────────────────────────────────────────────────────────────
    tabs = st.tabs([
        "🎨 Background",
        "🌟 Lifestyle",
        "👤 Model",
        "✏️ Editor",
        "✨ Enhance",
        "🏠 Scene",
        "💡 Lighting",
        "🌑 Shadows",
        "📝 Prompts",
        "📦 Batch",
        "↔️ Compare",
        "📜 History",
        "📤 Export",
        "📊 Dashboard",
    ])

    # ── Tab 1: Background Replacement ────────────────────────────────────────
    with tabs[0]:
        st.markdown("### 🎨 Background Replacement")
        bg_keys = list(BACKGROUND_OPTIONS.keys())
        bg_choice = st.selectbox("Background Style", bg_keys, key="nb_bg_choice")
        custom_bg = ""
        if bg_choice == "Custom Prompt":
            custom_bg = st.text_area("Custom Background Prompt", key="nb_bg_custom")
        product_desc_bg = st.text_input("Product Description (optional)", key="nb_pd_bg",
                                         placeholder="e.g. Nike Air Max sneaker")


        # Read directly from slider widget key so n is always current
        n = int(st.session_state.get("nb_angle_slider", 1))
        btn_label = ("🎨 Replace Background" if n == 1
                     else f"📸 Generate {n} Packshot Angles")
        if st.button(btn_label, key="nb_bg_btn", type="primary"):
            img = _get_image()
            if not img:
                st.warning("Please upload a product image first.")
            else:
                t0 = time.time()
                if n == 1:
                    # ── Single background replacement ──────────────────────
                    with st.spinner("Replacing background…"):
                        try:
                            result = engine.bg_gen.replace_background(
                                img, bg_choice, custom_bg, product_desc_bg
                            )
                            result = _ratio_to_pil(result, ratio_wh)
                            elapsed = time.time() - t0
                            st.session_state.nb_api_calls += 1
                            st.session_state.nb_gen_time += elapsed
                            prompt = (f"Background: {bg_choice}"
                                      + _ratio_prompt_suffix(ratio_label, ratio_wh))
                            _set_result(result, prompt, "background")
                            history.add("Background", img, result, prompt)
                            st.session_state.nb_packshot_results = []
                            st.success(f"Done in {elapsed:.1f}s")
                            _show_before_after(img, result)
                        except Exception as e:
                            st.session_state.nb_errors += 1
                            st.error(f"Error: {e}")
                else:
                    # ── Multi-angle packshot ────────────────────────────────
                    buf = io.BytesIO()
                    img.convert("RGB").save(buf, format="JPEG", quality=90)
                    ref_bytes = buf.getvalue()
                    st.session_state.nb_packshot_results = []
                    st.session_state.nb_packshot_ref_bytes = ref_bytes
                    st.session_state.nb_packshot_product_desc = product_desc_bg

                    from .api_client import ANGLE_VIEWS, _build_angle_prompt
                    selected_angles = ANGLE_VIEWS[:n]
                    prog = st.progress(0.0, text=f"Generating angle 1/{n}…")
                    raw_results = []

                    for _ai, _angle in enumerate(selected_angles):
                        prog.progress(float(_ai) / n,
                                      text=f"Generating {_angle['name']} ({_ai+1}/{n})…")
                        _prompt = _build_angle_prompt(product_desc_bg, _angle)
                        if ratio_wh:
                            _prompt += _ratio_prompt_suffix(ratio_label, ratio_wh)
                        try:
                            _img_bytes = engine.client.generate_image(_prompt, ref_bytes)
                            _img_bytes = _apply_ratio(_img_bytes, ratio_wh)
                            raw_results.append({
                                "name": _angle["name"], "label": _angle["label"],
                                "key": _angle["key"], "bytes": _img_bytes, "error": None,
                            })
                        except Exception as _e:
                            raw_results.append({
                                "name": _angle["name"], "label": _angle["label"],
                                "key": _angle["key"], "bytes": None, "error": str(_e),
                            })

                    elapsed = time.time() - t0
                    good = sum(1 for r in raw_results if r.get("bytes"))
                    prog.progress(1.0, text=f"✅ Done: {good}/{n} in {elapsed:.1f}s")

                    for r in raw_results:
                        st.session_state.nb_packshot_results.append(r)
                        if r.get("bytes"):
                            try:
                                from PIL import Image as _PIL
                                history.add(
                                    f"Packshot: {r['name']}",
                                    img, _PIL.open(io.BytesIO(r["bytes"])).convert("RGB"),
                                    f"{r['name']} — {product_desc_bg}"
                                    + _ratio_prompt_suffix(ratio_label, ratio_wh),
                                    "Gemini",
                                )
                            except Exception:
                                pass
                            st.session_state.nb_api_calls += 1
                        else:
                            st.session_state.nb_errors += 1
                    st.session_state.nb_gen_time += elapsed

                    _ratio_tag = (f"  ·  {ratio_label}" if ratio_wh else "")
                    st.success(f"✅ Generated {good}/{n} packshot angles in {elapsed:.1f}s")
                    st.session_state._nb_inline_rendered = True
                    st.markdown(f"### 📸 Generated Angles — {good}/{n}{_ratio_tag}")
                    _show_packshot_gallery(
                        st.session_state.nb_packshot_results,
                        engine, product_desc_bg, ref_bytes, "nb_inline",
                    )

        # ── Show single-BG result ─────────────────────────────────────────
        if st.session_state.nb_result and st.session_state.nb_result_mode == "background":
            if not st.session_state.nb_packshot_results:
                _show_before_after(_get_image(), st.session_state.nb_result)

        # ── Persistent packshot gallery (reruns after button-click run) ───
        _just_rendered = st.session_state.pop("_nb_inline_rendered", False)
        ps_results = st.session_state.nb_packshot_results
        if ps_results and not _just_rendered:
            good_n  = sum(1 for r in ps_results if r.get("bytes"))
            total_n = len(ps_results)
            _ratio_tag = (f"  ·  {ratio_label}" if ratio_wh else "")
            st.markdown(f"### 📸 Generated Angles — {good_n}/{total_n}{_ratio_tag}")
            _show_packshot_gallery(
                ps_results, engine,
                st.session_state.nb_packshot_product_desc,
                st.session_state.nb_packshot_ref_bytes,
                "nb_ps",
            )

    # ── Tab 2: Lifestyle ──────────────────────────────────────────────────────
    with tabs[1]:
        st.markdown("### 🌟 Lifestyle Scene Generator")
        lifestyle_style = st.selectbox("Lifestyle Style", LIFESTYLE_OPTIONS, key="nb_ls_style")
        custom_ls = st.text_area("Custom prompt (optional)", key="nb_ls_custom",
                                  placeholder="Leave blank to use the style preset")
        product_desc_ls = st.text_input("Product Description", key="nb_pd_ls",
                                         placeholder="e.g. Adidas running shoe")
        if st.button("🌟 Generate Lifestyle Scene", key="nb_ls_btn", type="primary"):
            img = _get_image()
            if not img:
                st.warning("Please upload a product image first.")
            elif not GOOGLE_API_KEY:
                _api_warning()
            else:
                with st.spinner("Generating lifestyle scene..."):
                    t0 = time.time()
                    try:
                        result = engine.lifestyle_gen.generate(
                            img, lifestyle_style, custom_ls, product_desc_ls
                        )
                        result = _ratio_to_pil(result, ratio_wh)
                        elapsed = time.time() - t0
                        st.session_state.nb_api_calls += 1
                        st.session_state.nb_gen_time += elapsed
                        prompt = (f"Lifestyle: {lifestyle_style}"
                                  + _ratio_prompt_suffix(ratio_label, ratio_wh))
                        _set_result(result, prompt, "lifestyle")
                        history.add("Lifestyle", img, result, prompt)
                        st.success(f"Done in {elapsed:.1f}s")
                        _show_before_after(img, result)
                    except Exception as e:
                        st.session_state.nb_errors += 1
                        st.error(f"Error: {e}")
        elif st.session_state.nb_result and st.session_state.nb_result_mode == "lifestyle":
            _show_before_after(_get_image(), st.session_state.nb_result)

    # ── Tab 3: AI Model ───────────────────────────────────────────────────────
    with tabs[2]:
        st.markdown("### 👤 AI Model Generator")
        col_a, col_b = st.columns(2)
        with col_a:
            gender = st.radio("Gender", MODEL_OPTIONS["gender"], key="nb_m_gender", horizontal=True)
            ethnicity = st.selectbox("Ethnicity", MODEL_OPTIONS["ethnicity"], key="nb_m_eth")
        with col_b:
            age_group = st.selectbox("Age Group", MODEL_OPTIONS["age"], key="nb_m_age")
            clothing_style = st.selectbox("Style", MODEL_OPTIONS["style"], key="nb_m_style")
        product_desc_m = st.text_input("Product Description", key="nb_pd_m",
                                        placeholder="e.g. Red Nike hoodie")
        if st.button("👤 Generate Model", key="nb_m_btn", type="primary"):
            img = _get_image()
            if not img:
                st.warning("Please upload a product image first.")
            elif not GOOGLE_API_KEY:
                _api_warning()
            else:
                with st.spinner("Generating AI model..."):
                    t0 = time.time()
                    try:
                        result = engine.model_gen.generate(
                            img, gender, age_group, ethnicity, clothing_style, product_desc_m
                        )
                        result = _ratio_to_pil(result, ratio_wh)
                        elapsed = time.time() - t0
                        st.session_state.nb_api_calls += 1
                        st.session_state.nb_gen_time += elapsed
                        prompt = (f"Model: {gender}, {age_group}, {ethnicity}, {clothing_style}"
                                  + _ratio_prompt_suffix(ratio_label, ratio_wh))
                        _set_result(result, prompt, "model")
                        history.add("Model", img, result, prompt)
                        st.success(f"Done in {elapsed:.1f}s")
                        _show_before_after(img, result)
                    except Exception as e:
                        st.session_state.nb_errors += 1
                        st.error(f"Error: {e}")
        elif st.session_state.nb_result and st.session_state.nb_result_mode == "model":
            _show_before_after(_get_image(), st.session_state.nb_result)

    # ── Tab 4: Editor ─────────────────────────────────────────────────────────
    with tabs[3]:
        st.markdown("### ✏️ AI Photo Editor")
        col_sliders, col_preview = st.columns([1, 1])

        with col_sliders:
            st.markdown("**Exposure**")
            brightness = st.slider("Brightness", -100, 100, 0, key="nb_e_brightness")
            contrast   = st.slider("Contrast",   -100, 100, 0, key="nb_e_contrast")
            exposure   = st.slider("Exposure",   -100, 100, 0, key="nb_e_exposure")
            highlights = st.slider("Highlights", -100, 100, 0, key="nb_e_highlights")
            shadows    = st.slider("Shadows",    -100, 100, 0, key="nb_e_shadows")
            whites     = st.slider("Whites",     -100, 100, 0, key="nb_e_whites")
            blacks     = st.slider("Blacks",     -100, 100, 0, key="nb_e_blacks")

            st.markdown("**Color**")
            temperature    = st.slider("Temperature",    -100, 100, 0, key="nb_e_temp")
            tint           = st.slider("Tint",           -100, 100, 0, key="nb_e_tint")
            vibrance       = st.slider("Vibrance",       -100, 100, 0, key="nb_e_vibrance")
            saturation     = st.slider("Saturation",     -100, 100, 0, key="nb_e_saturation")

            st.markdown("**Detail**")
            sharpness        = st.slider("Sharpness",        -100, 100, 0, key="nb_e_sharp")
            clarity          = st.slider("Clarity",          -100, 100, 0, key="nb_e_clarity")
            texture          = st.slider("Texture",          -100, 100, 0, key="nb_e_texture")
            noise_reduction  = st.slider("Noise Reduction",  -100, 100, 0, key="nb_e_noise")

            st.markdown("**AI Finish**")
            ai_finish = st.selectbox(
                "AI Finish Preset",
                ["None", "Luxury", "Marketplace", "Studio", "Natural", "Commercial"],
                key="nb_e_finish",
            )

        with col_preview:
            st.markdown("**Preview**")
            edit_img = _get_image()
            if edit_img:
                settings = dict(
                    brightness=brightness, contrast=contrast, exposure=exposure,
                    highlights=highlights, shadows=shadows, whites=whites, blacks=blacks,
                    temperature=temperature, tint=tint, vibrance=vibrance,
                    saturation=saturation, sharpness=sharpness, clarity=clarity,
                    texture=texture, noise_reduction=noise_reduction,
                )
                preview = engine.editor.adjust(edit_img, settings)
                st.image(preview, use_container_width=True)
            else:
                st.info("Upload an image to see preview")

        if st.button("✏️ Apply Edits", key="nb_edit_btn", type="primary"):
            img = _get_image()
            if not img:
                st.warning("Please upload a product image first.")
            else:
                settings = dict(
                    brightness=brightness, contrast=contrast, exposure=exposure,
                    highlights=highlights, shadows=shadows, whites=whites, blacks=blacks,
                    temperature=temperature, tint=tint, vibrance=vibrance,
                    saturation=saturation, sharpness=sharpness, clarity=clarity,
                    texture=texture, noise_reduction=noise_reduction,
                )
                with st.spinner("Applying edits..."):
                    t0 = time.time()
                    try:
                        result = engine.editor.adjust(img, settings)
                        if ai_finish != "None":
                            result = engine.editor.apply_ai_finish(result, ai_finish)
                        result = _ratio_to_pil(result, ratio_wh)
                        elapsed = time.time() - t0
                        st.session_state.nb_gen_time += elapsed
                        prompt = (f"Edit: brightness={brightness}, contrast={contrast}, ai_finish={ai_finish}"
                                  + _ratio_prompt_suffix(ratio_label, ratio_wh))
                        _set_result(result, prompt, "edit")
                        history.add("Edit", img, result, prompt)
                        st.success(f"Done in {elapsed:.1f}s")
                        _show_before_after(img, result)
                    except Exception as e:
                        st.session_state.nb_errors += 1
                        st.error(f"Error: {e}")

    # ── Tab 5: Enhance ────────────────────────────────────────────────────────
    with tabs[4]:
        st.markdown("### ✨ Product Enhancement")
        enhancements = st.multiselect(
            "Select Enhancements",
            ENHANCEMENT_OPTIONS,
            default=["Improve Colors"],
            key="nb_enh_list",
        )
        product_desc_enh = st.text_input("Product Description", key="nb_pd_enh",
                                          placeholder="e.g. leather handbag")
        if st.button("✨ Enhance Product", key="nb_enh_btn", type="primary"):
            img = _get_image()
            if not img:
                st.warning("Please upload a product image first.")
            elif not GOOGLE_API_KEY:
                _api_warning()
            elif not enhancements:
                st.warning("Select at least one enhancement.")
            else:
                with st.spinner("Enhancing product..."):
                    t0 = time.time()
                    try:
                        result = engine.enhancer.enhance(img, enhancements, product_desc_enh)
                        result = _ratio_to_pil(result, ratio_wh)
                        elapsed = time.time() - t0
                        st.session_state.nb_api_calls += 1
                        st.session_state.nb_gen_time += elapsed
                        prompt = (f"Enhance: {', '.join(enhancements)}"
                                  + _ratio_prompt_suffix(ratio_label, ratio_wh))
                        _set_result(result, prompt, "enhance")
                        history.add("Enhance", img, result, prompt)
                        st.success(f"Done in {elapsed:.1f}s")
                        _show_before_after(img, result)
                    except Exception as e:
                        st.session_state.nb_errors += 1
                        st.error(f"Error: {e}")
        elif st.session_state.nb_result and st.session_state.nb_result_mode == "enhance":
            _show_before_after(_get_image(), st.session_state.nb_result)

    # ── Tab 6: Scene ──────────────────────────────────────────────────────────
    with tabs[5]:
        st.markdown("### 🏠 Scene Generator")
        scene_type = st.selectbox("Scene Type", SCENE_OPTIONS, key="nb_scene_type")
        product_desc_sc = st.text_input("Product Description", key="nb_pd_sc")
        if st.button("🏠 Generate Scene", key="nb_scene_btn", type="primary"):
            img = _get_image()
            if not img:
                st.warning("Please upload a product image first.")
            elif not GOOGLE_API_KEY:
                _api_warning()
            else:
                with st.spinner("Generating scene..."):
                    t0 = time.time()
                    try:
                        result = engine.process_single(img, {
                            "mode": "scene",
                            "scene_type": scene_type,
                            "product_desc": product_desc_sc,
                        })
                        result = _ratio_to_pil(result, ratio_wh)
                        elapsed = time.time() - t0
                        st.session_state.nb_api_calls += 1
                        st.session_state.nb_gen_time += elapsed
                        prompt = (f"Scene: {scene_type}"
                                  + _ratio_prompt_suffix(ratio_label, ratio_wh))
                        _set_result(result, prompt, "scene")
                        history.add("Scene", img, result, prompt)
                        st.success(f"Done in {elapsed:.1f}s")
                        _show_before_after(img, result)
                    except Exception as e:
                        st.session_state.nb_errors += 1
                        st.error(f"Error: {e}")
        elif st.session_state.nb_result and st.session_state.nb_result_mode == "scene":
            _show_before_after(_get_image(), st.session_state.nb_result)

    # ── Tab 7: Lighting ───────────────────────────────────────────────────────
    with tabs[6]:
        st.markdown("### 💡 Lighting Studio")
        lighting_type = st.selectbox("Lighting Type", LIGHTING_OPTIONS, key="nb_light_type")
        product_desc_lt = st.text_input("Product Description", key="nb_pd_lt")
        if st.button("💡 Apply Lighting", key="nb_light_btn", type="primary"):
            img = _get_image()
            if not img:
                st.warning("Please upload a product image first.")
            elif not GOOGLE_API_KEY:
                _api_warning()
            else:
                with st.spinner("Applying lighting..."):
                    t0 = time.time()
                    try:
                        result = engine.process_single(img, {
                            "mode": "lighting",
                            "lighting_type": lighting_type,
                            "product_desc": product_desc_lt,
                        })
                        result = _ratio_to_pil(result, ratio_wh)
                        elapsed = time.time() - t0
                        st.session_state.nb_api_calls += 1
                        st.session_state.nb_gen_time += elapsed
                        prompt = (f"Lighting: {lighting_type}"
                                  + _ratio_prompt_suffix(ratio_label, ratio_wh))
                        _set_result(result, prompt, "lighting")
                        history.add("Lighting", img, result, prompt)
                        st.success(f"Done in {elapsed:.1f}s")
                        _show_before_after(img, result)
                    except Exception as e:
                        st.session_state.nb_errors += 1
                        st.error(f"Error: {e}")
        elif st.session_state.nb_result and st.session_state.nb_result_mode == "lighting":
            _show_before_after(_get_image(), st.session_state.nb_result)

    # ── Tab 8: Shadows ────────────────────────────────────────────────────────
    with tabs[7]:
        st.markdown("### 🌑 Shadow Studio")
        shadow_type = st.selectbox("Shadow Type", SHADOW_OPTIONS, key="nb_shadow_type")
        if st.button("🌑 Generate Shadow", key="nb_shadow_btn", type="primary"):
            img = _get_image()
            if not img:
                st.warning("Please upload a product image first.")
            elif not GOOGLE_API_KEY:
                _api_warning()
            else:
                with st.spinner("Generating shadow..."):
                    t0 = time.time()
                    try:
                        result = engine.process_single(img, {
                            "mode": "shadow",
                            "shadow_type": shadow_type,
                        })
                        result = _ratio_to_pil(result, ratio_wh)
                        elapsed = time.time() - t0
                        st.session_state.nb_api_calls += 1
                        st.session_state.nb_gen_time += elapsed
                        prompt = (f"Shadow: {shadow_type}"
                                  + _ratio_prompt_suffix(ratio_label, ratio_wh))
                        _set_result(result, prompt, "shadow")
                        history.add("Shadow", img, result, prompt)
                        st.success(f"Done in {elapsed:.1f}s")
                        _show_before_after(img, result)
                    except Exception as e:
                        st.session_state.nb_errors += 1
                        st.error(f"Error: {e}")
        elif st.session_state.nb_result and st.session_state.nb_result_mode == "shadow":
            _show_before_after(_get_image(), st.session_state.nb_result)

    # ── Tab 9: Prompt Builder ─────────────────────────────────────────────────
    with tabs[8]:
        st.markdown("### 📝 Prompt Builder")
        preset = st.selectbox("Style Preset", list(STYLE_PRESETS.keys()), key="nb_pb_preset")
        product_desc_pb = st.text_input("Product Description", key="nb_pd_pb",
                                         placeholder="e.g. Nike Air Force 1 white sneaker")
        custom_add = st.text_area("Additional instructions", key="nb_pb_custom",
                                   placeholder="e.g. add bokeh background, warm tones")

        built = build_from_preset(preset, product_desc_pb)
        if custom_add:
            built += f" {custom_add}"
        if ratio_wh:
            built += _ratio_prompt_suffix(ratio_label, ratio_wh)

        st.markdown("**Built Prompt:**")
        st.code(built, language=None)

        if st.button("📋 Use This Prompt", key="nb_pb_use"):
            st.session_state.nb_copied_prompt = built
            st.success("Prompt stored! Use it in any AI tab's custom prompt field.")

        if st.session_state.nb_copied_prompt:
            st.info(f"Stored prompt: {st.session_state.nb_copied_prompt[:120]}...")

    # ── Tab 10: Batch Processing ──────────────────────────────────────────────
    with tabs[9]:
        st.markdown("### 📦 Batch Processing")

        # Input type selector
        batch_input_type = st.radio(
            "Input type",
            ["Excel file (image URLs)", "ZIP file (images)"],
            key="nb_batch_input_type",
            horizontal=True,
        )

        if batch_input_type == "Excel file (image URLs)":
            batch_excel = st.file_uploader(
                "Upload Excel file (STYLE_CODE, IMAGE1..IMAGE12 columns with URLs)",
                type=["xlsx", "xls"],
                key="nb_batch_excel",
            )
            batch_zip_file = None
        else:
            batch_zip_file = st.file_uploader(
                "Upload ZIP file containing images (JPG/PNG)",
                type=["zip"],
                key="nb_batch_zip",
            )
            batch_excel = None

        batch_mode = st.selectbox(
            "Processing Mode",
            ["background", "lifestyle", "enhance", "edit", "scene"],
            key="nb_batch_mode",
        )
        if batch_mode == "background":
            batch_bg = st.selectbox("Background", list(BACKGROUND_OPTIONS.keys()), key="nb_batch_bg")
        else:
            batch_bg = "White"

        batch_angles = st.slider(
            "Angles per image",
            min_value=1, max_value=8, value=1,
            key="nb_batch_angles",
            help="How many angle variations to generate for each input image",
        )
        if batch_angles > 1:
            st.info(f"Will generate {batch_angles} angle variations per image → output ZIP will have (images × {batch_angles}) files.")

        have_input = batch_excel is not None or batch_zip_file is not None

        if st.button("▶ Run Batch", key="nb_batch_btn", type="primary"):
            if not have_input:
                st.warning("Please upload an input file.")
            elif not GOOGLE_API_KEY and batch_mode != "edit":
                _api_warning()
            else:
                import tempfile, pathlib, zipfile as _zf, os as _os

                config = {"mode": batch_mode, "angles": batch_angles, "ratio_wh": ratio_wh}
                if batch_mode == "background":
                    config["background_option"] = batch_bg

                progress_bar = st.progress(0)
                status_text = st.empty()

                def _progress(done, total):
                    pct = done / total if total > 0 else 0
                    progress_bar.progress(pct)
                    status_text.text(f"Processing {done}/{total}...")

                with st.spinner("Running batch..."):
                    try:
                        if batch_excel is not None:
                            with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tf:
                                tf.write(batch_excel.getvalue())
                                excel_path = tf.name
                            try:
                                results = engine.process_batch(excel_path, config, _progress)
                            finally:
                                _os.unlink(excel_path)
                        else:
                            # ZIP input: extract images and process each
                            results = _process_zip_batch(
                                batch_zip_file.getvalue(), config, engine, _progress
                            )
                        st.session_state.nb_batch_result = results
                        st.success(
                            f"Batch complete! "
                            f"✓ {results.get('success', 0)} | "
                            f"✗ {results.get('failed', 0)} | "
                            f"⚠ {results.get('skipped', 0)}"
                        )
                    except Exception as e:
                        st.error(f"Batch error: {e}")

        if st.session_state.nb_batch_result:
            r = st.session_state.nb_batch_result
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Total", r.get("total", 0))
            c2.metric("Success", r.get("success", 0))
            c3.metric("Failed", r.get("failed", 0))
            c4.metric("Skipped", r.get("skipped", 0))

            if r.get("zip_bytes"):
                mb = len(r["zip_bytes"]) / 1024 / 1024
                st.download_button(
                    f"⬇ Download Batch ZIP ({mb:.1f} MB)",
                    data=r["zip_bytes"],
                    file_name="nb_batch_output.zip",
                    mime="application/zip",
                    use_container_width=True,
                )

    # ── Tab 11: Compare ───────────────────────────────────────────────────────
    with tabs[10]:
        st.markdown("### ↔️ Before / After Compare")
        img = _get_image()
        result = st.session_state.nb_result
        if img and result:
            _show_before_after(img, result,
                               labels=(
                                   "Original",
                                   f"Result ({st.session_state.nb_result_mode})"
                               ))
        else:
            st.info("Generate a result in any tab to compare here.")

        hist = history.get_all()
        if len(hist) > 1:
            st.markdown("**History Compare**")
            ids = [f"[{h['id']}] {h['job_type']} @ {h['timestamp']}" for h in hist]
            sel = st.selectbox("Select history entry", ids, key="nb_cmp_sel")

    # ── Tab 12: History ───────────────────────────────────────────────────────
    with tabs[11]:
        st.markdown("### 📜 Session History")
        hist = history.get_all()
        if not hist:
            st.info("No history yet. Generate images to see them here.")
        else:
            if st.button("🗑️ Clear History", key="nb_hist_clear"):
                history.clear()
                st.rerun()
            for entry in reversed(hist):
                with st.container():
                    hc1, hc2, hc3 = st.columns([1, 1, 3])
                    with hc1:
                        if entry["original_thumb"]:
                            st.image(
                                base64.b64decode(entry["original_thumb"]),
                                caption="Original",
                                width=100,
                            )
                    with hc2:
                        if entry["result_thumb"]:
                            st.image(
                                base64.b64decode(entry["result_thumb"]),
                                caption="Result",
                                width=100,
                            )
                    with hc3:
                        st.markdown(
                            f"**{entry['job_type']}** — `{entry['id']}`  \n"
                            f"🕐 {entry['timestamp']} | {entry['engine']}  \n"
                            f"*{entry['prompt'][:100]}*"
                        )
                    st.markdown("---")

    # ── Tab 13: Export ────────────────────────────────────────────────────────
    with tabs[12]:
        st.markdown("### 📤 Export")
        result = st.session_state.nb_result
        if not result:
            st.info("Generate a result first.")
        else:
            exp_fmt = st.selectbox("Format", EXPORT_FORMATS, key="nb_exp_fmt")
            exp_quality = st.slider("Quality", 50, 100, 90, key="nb_exp_quality")

            img_bytes = exporter.to_bytes(result, exp_fmt, exp_quality)
            ext = exp_fmt.lower().replace("jpeg", "jpg")
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            fname = f"nb_{st.session_state.nb_result_mode}_{ts}.{ext}"

            st.download_button(
                f"⬇ Download {exp_fmt} ({len(img_bytes)/1024:.0f} KB)",
                data=img_bytes,
                file_name=fname,
                mime=f"image/{exp_fmt.lower()}",
                use_container_width=True,
            )
            st.image(result, caption=f"Current result ({result.width}×{result.height}px)",
                     use_container_width=True)

    # ── Tab 14: Dashboard ─────────────────────────────────────────────────────
    with tabs[13]:
        from .diagnostics import (
            run_startup_diagnostics,
            run_full_connection_test,
            run_production_checklist,
            run_production_validation,
            get_error_log,
        )
        import streamlit as _st  # alias for clarity inside nested calls
        _user_email = st.session_state.get("user_email", "").lower()

        st.markdown("### 📊 Session Dashboard")

        # ── Section 1: Session metrics ────────────────────────────────────────
        api_calls  = st.session_state.nb_api_calls
        gen_time   = st.session_state.nb_gen_time
        errors     = st.session_state.nb_errors
        hist_count = history.count()

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Images Generated", hist_count)
        c2.metric("API Calls", api_calls)
        c3.metric("Total Gen Time", f"{gen_time:.1f}s")
        c4.metric("Avg per Image", f"{gen_time/max(api_calls,1):.1f}s")
        c5.metric("Errors", errors)

        st.markdown("---")

        # ── Section 2: Startup Diagnostics ───────────────────────────────────
        st.markdown("### 🔬 Startup Diagnostics")

        if st.button("🔄 Refresh Diagnostics", key="nb_diag_refresh"):
            if "nb_startup_diag" in st.session_state:
                del st.session_state["nb_startup_diag"]

        if "nb_startup_diag" not in st.session_state:
            with st.spinner("Running startup diagnostics..."):
                st.session_state["nb_startup_diag"] = run_startup_diagnostics(GOOGLE_API_KEY)

        diag = st.session_state["nb_startup_diag"]

        import pandas as pd

        diag_rows = []
        versions = diag.get("versions", {})
        for pkg, ver in versions.items():
            diag_rows.append({"Item": pkg, "Value": ver})
        diag_rows.append({"Item": "Internet", "Value": "✅ Reachable" if diag.get("internet") else "❌ Unreachable"})
        gapi = diag.get("google_api", {})
        diag_rows.append({"Item": "Google API", "Value": "✅ Reachable" if gapi.get("reachable") else f"❌ {gapi.get('error', 'Unreachable')}"})
        diag_rows.append({"Item": "Model count", "Value": str(gapi.get("model_count", 0))})
        diag_rows.append({"Item": "Image models discovered", "Value": ", ".join(diag.get("image_models", [])) or "none"})
        diag_rows.append({"Item": "Selected model", "Value": diag.get("selected_model") or "none"})
        diag_rows.append({"Item": "Image gen supported", "Value": "✅ Yes" if diag.get("image_gen_supported") else "❌ No"})
        diag_rows.append({"Item": "Image edit supported", "Value": "✅ Yes" if diag.get("image_edit_supported") else "❌ No"})
        diag_rows.append({"Item": "API key", "Value": diag.get("api_key_masked", "NOT SET")})
        diag_rows.append({"Item": "Auth method", "Value": diag.get("auth_method", "")})
        diag_rows.append({"Item": "Last checked", "Value": diag.get("timestamp", "")})

        st.dataframe(pd.DataFrame(diag_rows), use_container_width=True, hide_index=True)

        if diag.get("all_models"):
            with st.expander(f"All accessible models ({len(diag['all_models'])})"):
                for m in sorted(diag["all_models"]):
                    st.text(m)

        st.markdown("---")

        # ── Section 3: Test Connection ────────────────────────────────────────
        st.markdown("### 🔌 Test Connection")
        if st.button("▶ Run Full Connection Test (8 steps)", key="nb_test_conn", type="primary"):
            with st.spinner("Running 8-step connection test — may take 20–30 seconds..."):
                conn_steps = run_full_connection_test(engine.client)
            st.session_state["nb_conn_steps"] = conn_steps

        if "nb_conn_steps" in st.session_state:
            for s in st.session_state["nb_conn_steps"]:
                ok = s["ok"]
                icon = "✅" if ok else "❌"
                st.markdown(f"{icon} **{s['step']}** — {s['detail']}")

        st.markdown("---")

        # ── Section 4: Production Checklist ──────────────────────────────────
        st.markdown("### ✔️ Production Checklist")
        if st.button("▶ Run Production Checklist", key="nb_btn_prod_checklist"):
            with st.spinner("Running production checks..."):
                checklist = run_production_checklist(engine, GOOGLE_API_KEY)
            st.session_state["nb_prod_checklist_result"] = checklist

        if "nb_prod_checklist_result" in st.session_state:
            cl = st.session_state["nb_prod_checklist_result"]
            for key, result in cl.items():
                label = key.replace("_", " ").title()
                ok = result.get("ok")
                if ok is True:
                    icon = "✅"
                elif ok is False:
                    icon = "❌"
                else:
                    icon = "⚠️"
                if key == "security_audit":
                    issues = result.get("issues", [])
                    detail = "No issues found" if ok else f"{len(issues)} potential issue(s)"
                    st.markdown(f"{icon} **{label}** — {detail}")
                    if issues:
                        with st.expander("Security issues"):
                            for iss in issues:
                                st.code(iss)
                else:
                    detail = result.get("detail", "")
                    st.markdown(f"{icon} **{label}** — {detail}")

        st.markdown("---")

        # ── Section 5: Performance Metrics ───────────────────────────────────
        st.markdown("### ⚡ Performance Metrics")
        perf = engine.client.get_perf_metrics()
        pc1, pc2, pc3, pc4, pc5 = st.columns(5)
        pc1.metric("API Requests", perf["requests"])
        pc2.metric("Errors", perf["errors"])
        pc3.metric("Error Rate", f"{perf['error_rate']}%")
        pc4.metric("Avg Time", f"{perf['avg_time']}s")
        pc5.metric("Total Time", f"{perf['total_time']}s")

        st.markdown("---")

        # ── Section 6: Error Log ──────────────────────────────────────────────
        st.markdown("### 🪵 Error Log")
        error_log = get_error_log()
        log_entries = error_log.get_all()

        if st.button("🗑️ Clear Error Log", key="nb_clear_errlog"):
            error_log.clear()
            st.rerun()

        if not log_entries:
            st.info("No errors logged in this session.")
        else:
            st.markdown(f"**{len(log_entries)} error(s) recorded**")
            for entry in reversed(log_entries[-50:]):
                with st.expander(
                    f"[{entry['timestamp'][:19]}] {entry['operation']} — {entry['error_msg'][:80]}"
                ):
                    ec1, ec2 = st.columns(2)
                    ec1.markdown(f"**Model:** `{entry['model']}`")
                    ec2.markdown(f"**Status:** `{entry['response_status']}`")
                    st.markdown(f"**Error:** {entry['error_msg']}")
                    if entry.get("fix_suggestion"):
                        st.info(f"**Fix suggestion:** {entry['fix_suggestion']}")
                    if entry.get("response_body"):
                        st.code(entry["response_body"][:400], language=None)

        st.markdown("---")

        # ── Section 7: Generation History (unchanged) ─────────────────────────
        st.markdown("**Generation History**")
        hist = history.get_all()
        if hist:
            df = pd.DataFrame([
                {"ID": h["id"], "Type": h["job_type"], "Prompt": h["prompt"][:60],
                 "Engine": h["engine"], "Time": h["timestamp"], "Status": h["status"]}
                for h in hist
            ])
            st.dataframe(df, use_container_width=True)
        else:
            st.info("No generation history yet.")

        st.markdown("---")

        # ── Section 8: Production Validation (admin only) ─────────────────────
        def _can_production_validation() -> bool:
            try:
                import yaml as _yaml
                from pathlib import Path as _Path
                from .auth import get_role, can
                _f = _Path(__file__).parent.parent / "users.yaml"
                _u = (_yaml.safe_load(_f.read_text()) or {}).get(_user_email, {})
                return can(get_role(_u), "production_validation")
            except Exception:
                return False

        if _can_production_validation():
            st.markdown("### 🚀 Production Validation")
            st.caption(
                "Runs 15 real runtime tests against the live Railway environment. "
                "This section is only visible to the admin account."
            )

            col_run, col_clear = st.columns([3, 1])
            with col_run:
                run_pv = st.button(
                    "▶ Run Production Validation (15 steps)",
                    key="nb_run_prod_validation",
                    type="primary",
                    use_container_width=True,
                )
            with col_clear:
                if st.button("🗑️ Clear", key="nb_clear_prod_validation",
                             use_container_width=True):
                    if "nb_prod_validation" in st.session_state:
                        del st.session_state["nb_prod_validation"]
                    st.rerun()

            if run_pv:
                with st.spinner(
                    "Running production validation — making real API calls. "
                    "This may take 30–90 seconds..."
                ):
                    st.session_state["nb_prod_validation"] = run_production_validation(
                        engine, GOOGLE_API_KEY
                    )

            if "nb_prod_validation" in st.session_state:
                pv = st.session_state["nb_prod_validation"]
                env  = pv.get("env_info", {})
                v_list = pv.get("verified", [])
                f_list = pv.get("failed", [])
                n_list = pv.get("not_verified", [])

                # ── Environment info ──────────────────────────────────────────
                with st.expander("🔍 Environment info", expanded=False):
                    env_rows = []
                    for key_name in ("python", "google-genai", "google-generativeai",
                                     "Pillow", "rembg", "os",
                                     "api_key_masked", "api_key_format",
                                     "auth_method", "auth_status", "model_count",
                                     "selected_model", "endpoint", "sdk_ok"):
                        if key_name in env:
                            env_rows.append({"Item": key_name,
                                             "Value": str(env[key_name])})
                    if env_rows:
                        st.dataframe(pd.DataFrame(env_rows),
                                     use_container_width=True, hide_index=True)
                    im = env.get("image_models", [])
                    if im:
                        st.markdown(f"**Image-capable models ({len(im)}):** "
                                    f"`{', '.join(im)}`")
                    all_m = env.get("all_models", [])
                    if all_m:
                        st.markdown(f"**All accessible models ({len(all_m)}):**")
                        st.code("\n".join(sorted(all_m)), language=None)

                # ── Summary counts ────────────────────────────────────────────
                sv, sf, sn = len(v_list), len(f_list), len(n_list)
                sc1, sc2, sc3, sc4 = st.columns(4)
                sc1.metric("✅ Verified", sv)
                sc2.metric("❌ Failed", sf)
                sc3.metric("⚠️ Not Verified", sn)
                sc4.metric("⏱ Elapsed", f"{pv.get('elapsed', 0):.1f}s")

                # ── Generated test image ──────────────────────────────────────
                img_bytes = pv.get("test_image_bytes")
                bg_bytes  = pv.get("bg_image_bytes")
                if img_bytes or bg_bytes:
                    st.markdown("**Test images from validation run:**")
                    img_cols = st.columns(2)
                    if img_bytes:
                        with img_cols[0]:
                            st.markdown("*Generated (Text-to-Image)*")
                            st.image(img_bytes, use_container_width=True)
                    if bg_bytes:
                        with img_cols[1]:
                            st.markdown("*Background Replacement test*")
                            st.image(bg_bytes, use_container_width=True)

                # ── VERIFIED ──────────────────────────────────────────────────
                st.markdown("#### ✅ VERIFIED")
                if v_list:
                    for item in v_list:
                        with st.expander(f"✅ {item['name']}", expanded=False):
                            st.markdown(item["detail"])
                else:
                    st.warning("No items verified.")

                # ── FAILED ───────────────────────────────────────────────────
                st.markdown("#### ❌ FAILED")
                if f_list:
                    for item in f_list:
                        with st.expander(f"❌ {item['name']}", expanded=True):
                            st.error(item["detail"])
                            if item.get("google_response"):
                                st.markdown("**Google API response:**")
                                st.code(item["google_response"], language="json")
                else:
                    st.success("No failures.")

                # ── NOT VERIFIED ──────────────────────────────────────────────
                st.markdown("#### ⚠️ NOT VERIFIED")
                if n_list:
                    for item in n_list:
                        st.markdown(
                            f"⚠️ **{item['name']}** — {item['reason']}"
                        )
                else:
                    st.success("All items verified or failed with a result.")
