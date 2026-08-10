"""Tests for Psydox Prompt Intelligence Engine."""
import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))


def test_structured_prompt_to_text():
    from psydox.ai_core.prompt_engine import StructuredPrompt
    p = StructuredPrompt(
        subject="white sneaker",
        environment="urban street",
        style="editorial",
        constraints=["keep brand logo visible"],
        negatives=["blurry", "distorted"],
    )
    text = p.to_text()
    assert "white sneaker" in text
    assert "urban street" in text
    assert "keep brand logo visible" in text


def test_structured_prompt_fingerprint_deterministic():
    from psydox.ai_core.prompt_engine import StructuredPrompt
    p = StructuredPrompt(subject="shoe", environment="beach")
    assert p.fingerprint() == p.fingerprint()


def test_two_different_prompts_have_different_fingerprints():
    from psydox.ai_core.prompt_engine import StructuredPrompt
    p1 = StructuredPrompt(subject="shoe", environment="beach")
    p2 = StructuredPrompt(subject="shoe", environment="forest")
    assert p1.fingerprint() != p2.fingerprint()


def test_prompt_engine_build_lifestyle():
    from psydox.ai_core.prompt_engine import PromptEngine, PromptContext
    ctx = PromptContext(product_desc="red hoodie", style="Casual Street Style")
    prompt = PromptEngine().build_lifestyle(ctx)
    text = prompt.to_text()
    assert len(text) > 20


def test_prompt_engine_build_background():
    from psydox.ai_core.prompt_engine import PromptEngine, PromptContext
    ctx = PromptContext(product_desc="blue sneaker", environment="studio")
    prompt = PromptEngine().build_background(ctx)
    text = prompt.to_text()
    assert "blue sneaker" in text or "studio" in text or len(text) > 10


def test_prompt_context_defaults():
    from psydox.ai_core.prompt_engine import PromptContext
    ctx = PromptContext()
    assert ctx.product_desc == ""
    assert ctx.style == ""
