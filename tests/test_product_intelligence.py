"""Tests for ProductIntelligenceEngine and AttributeValue."""
import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))

import os
os.environ["DEBUG_MODE"] = "true"   # use mock provider


def test_attribute_value_reliable():
    from psydox.product.intelligence import AttributeValue
    av = AttributeValue(value="shirt", confidence=0.9)
    assert av.is_reliable()


def test_attribute_value_unreliable_below_threshold():
    from psydox.product.intelligence import AttributeValue
    av = AttributeValue(value="guess", confidence=0.1)
    assert not av.is_reliable()


def test_attribute_value_to_dict():
    from psydox.product.intelligence import AttributeValue
    av = AttributeValue(value="red", confidence=0.85, source="vision")
    d  = av.to_dict()
    assert d["value"] == "red"
    assert d["confidence"] == 0.85
    assert d["source"] == "vision"


def test_product_attributes_empty_not_useful():
    from psydox.product.intelligence import ProductAttributes
    pa = ProductAttributes()
    assert not pa.is_useful()


def test_product_attributes_to_dict_keys():
    from psydox.product.intelligence import ProductAttributes
    pa = ProductAttributes()
    d = pa.to_dict()
    assert "category" in d
    assert "primary_color" in d
    assert "overall_confidence" in d


def test_product_attributes_prompt_clause_empty_when_no_data():
    from psydox.product.intelligence import ProductAttributes
    pa = ProductAttributes()
    assert pa.to_prompt_clause() == ""


def test_product_attributes_prompt_clause_with_data():
    from psydox.product.intelligence import ProductAttributes, AttributeValue
    pa = ProductAttributes(
        category=AttributeValue("sneaker", 0.9),
        primary_color=AttributeValue("white", 0.85),
        overall_confidence=0.8,
    )
    clause = pa.to_prompt_clause()
    assert "sneaker" in clause
    assert "white" in clause


def test_intelligence_engine_returns_on_empty_input():
    from psydox.product.intelligence import ProductIntelligenceEngine
    attrs = ProductIntelligenceEngine().analyze(b"")
    assert attrs is not None
    assert attrs.analysis_source == "unavailable"


def test_intelligence_engine_parse_valid_json():
    from psydox.product.intelligence import ProductIntelligenceEngine
    engine = ProductIntelligenceEngine()
    data = {
        "category": {"value": "shirt", "confidence": 0.92},
        "primary_color": {"value": "blue", "confidence": 0.87},
        "overall_confidence": 0.88,
        "raw_description": "A blue cotton shirt.",
    }
    attrs = engine._parse(data)
    assert attrs.category is not None
    assert attrs.category.value == "shirt"
    assert attrs.primary_color.value == "blue"
    assert attrs.overall_confidence == 0.88


def test_intelligence_engine_parse_suppresses_low_confidence():
    from psydox.product.intelligence import ProductIntelligenceEngine
    engine = ProductIntelligenceEngine()
    data = {
        "category": {"value": "shirt", "confidence": 0.05},  # below threshold
        "overall_confidence": 0.05,
    }
    attrs = engine._parse(data)
    assert attrs.category is None
