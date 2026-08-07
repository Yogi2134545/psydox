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

                if n_angles == 1:
                    result_img = engine.bg_gen.replace_background(img, bg_opt, "", "")
                    out_ib = io.BytesIO()
                    result_img.convert("RGB").save(out_ib, format="JPEG", quality=90)
                    zout.writestr(f"{stem}_result.jpg", out_ib.getvalue())
                    success += 1
                    done += 1
                else:
                    base_prompt = f"Product photo with {bg_opt} background"
                    angle_results = engine.client.generate_angles(base_prompt, ref_bytes, count=n_angles)
                    for ai, ab in enumerate(angle_results):
                        if ab is not None:
                            zout.writestr(f"{stem}_angle{ai + 1}.jpg", ab)
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
                    import requests as _req
                    r = _req.get(url_input.strip(), timeout=15,
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
        st.info(
            f"Will generate **{angle_count} angle variations** — front, side, 3/4, back, top, "
            "close-up, low, elevated — and offer a ZIP download."
        )

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
        if st.button("🎨 Replace Background", key="nb_bg_btn", type="primary"):
            img = _get_image()
            if not img:
                st.warning("Please upload a product image first.")
            else:
                n = st.session_state.nb_angle_count
                with st.spinner(f"Generating {n} background variation(s)..."):
                    t0 = time.time()
                    try:
                        if n == 1:
                            result = engine.bg_gen.replace_background(
                                img, bg_choice, custom_bg, product_desc_bg
                            )
                            elapsed = time.time() - t0
                            st.session_state.nb_api_calls += 1
                            st.session_state.nb_gen_time += elapsed
                            prompt = f"Background: {bg_choice}"
                            _set_result(result, prompt, "background")
                            history.add("Background", img, result, prompt)
                            st.session_state.nb_angle_results = []
                            st.success(f"Done in {elapsed:.1f}s")
                            _show_before_after(img, result)
                        else:
                            # Multi-angle: generate N variations
                            buf = io.BytesIO()
                            img.convert("RGB").save(buf, format="JPEG", quality=90)
                            ref_bytes = buf.getvalue()
                            base_prompt = (
                                f"Product photo with {bg_choice} background"
                                + (f", {product_desc_bg}" if product_desc_bg else "")
                                + (f", {custom_bg}" if custom_bg else "")
                            )
                            results = engine.client.generate_angles(
                                base_prompt, ref_bytes, count=n
                            )
                            elapsed = time.time() - t0
                            st.session_state.nb_api_calls += n
                            st.session_state.nb_gen_time += elapsed
                            st.session_state.nb_angle_results = results
                            good = sum(1 for r in results if r is not None)
                            st.success(f"Generated {good}/{n} angles in {elapsed:.1f}s")
                    except Exception as e:
                        st.session_state.nb_errors += 1
                        st.error(f"Error: {e}")

        # Show results
        if st.session_state.nb_angle_results:
            results = st.session_state.nb_angle_results
            _show_angle_grid(results)
            zip_data = _build_angles_zip(results, "bg")
            st.download_button(
                f"⬇ Download All {len(results)} Angles (ZIP)",
                data=zip_data,
                file_name="psydox_angles.zip",
                mime="application/zip",
                use_container_width=True,
                key="nb_bg_zip_dl",
            )
        elif st.session_state.nb_result and st.session_state.nb_result_mode == "background":
            _show_before_after(_get_image(), st.session_state.nb_result)

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
                        elapsed = time.time() - t0
                        st.session_state.nb_api_calls += 1
                        st.session_state.nb_gen_time += elapsed
                        prompt = f"Lifestyle: {lifestyle_style}"
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
                        elapsed = time.time() - t0
                        st.session_state.nb_api_calls += 1
                        st.session_state.nb_gen_time += elapsed
                        prompt = f"Model: {gender}, {age_group}, {ethnicity}, {clothing_style}"
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
                            if not GOOGLE_API_KEY:
                                st.warning("API key not set — AI finish skipped.")
                            else:
                                result = engine.editor.apply_ai_finish(result, ai_finish)
                                st.session_state.nb_api_calls += 1
                        elapsed = time.time() - t0
                        st.session_state.nb_gen_time += elapsed
                        prompt = f"Edit: brightness={brightness}, contrast={contrast}, ai_finish={ai_finish}"
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
                        elapsed = time.time() - t0
                        st.session_state.nb_api_calls += 1
                        st.session_state.nb_gen_time += elapsed
                        prompt = f"Enhance: {', '.join(enhancements)}"
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
                        elapsed = time.time() - t0
                        st.session_state.nb_api_calls += 1
                        st.session_state.nb_gen_time += elapsed
                        prompt = f"Scene: {scene_type}"
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
                        elapsed = time.time() - t0
                        st.session_state.nb_api_calls += 1
                        st.session_state.nb_gen_time += elapsed
                        prompt = f"Lighting: {lighting_type}"
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
                        elapsed = time.time() - t0
                        st.session_state.nb_api_calls += 1
                        st.session_state.nb_gen_time += elapsed
                        prompt = f"Shadow: {shadow_type}"
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
                import tempfile, pathlib, zipfile as _zf

                config = {"mode": batch_mode, "angles": batch_angles}
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
                            results = engine.process_batch(excel_path, config, _progress)
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
        st.markdown("### 📊 Session Dashboard")
        api_calls = st.session_state.nb_api_calls
        gen_time  = st.session_state.nb_gen_time
        errors    = st.session_state.nb_errors
        hist_count = history.count()

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Images Generated", hist_count)
        c2.metric("API Calls", api_calls)
        c3.metric("Total Gen Time", f"{gen_time:.1f}s")
        c4.metric("Avg per Image", f"{gen_time/max(api_calls,1):.1f}s")
        c5.metric("Errors", errors)

        # Estimated cost (rough: ~$0.04 per API call for Imagen)
        est_cost = api_calls * 0.04
        st.metric("Estimated API Cost", f"${est_cost:.2f}")

        st.markdown("---")
        st.markdown("**API Configuration**")
        if GOOGLE_API_KEY:
            st.success(f"GOOGLE_API_KEY: configured ({GOOGLE_API_KEY[:8]}...)")
        else:
            st.error("GOOGLE_API_KEY: not configured")

        hist = history.get_all()
        if hist:
            st.markdown("**Generation History**")
            import pandas as pd
            df = pd.DataFrame([
                {
                    "ID": h["id"],
                    "Type": h["job_type"],
                    "Prompt": h["prompt"][:60],
                    "Engine": h["engine"],
                    "Time": h["timestamp"],
                    "Status": h["status"],
                }
                for h in hist
            ])
            st.dataframe(df, use_container_width=True)
