"""Tests for ОКВЭД code normalization + rule-based fallback from segments."""
from __future__ import annotations

import pytest

from app.services.prompt_enhancer import (
    _normalize_okved,
    _okved_from_segments,
    _OKVED_CODE_RE,
)


class TestCodeValidation:
    @pytest.mark.parametrize("code", ["01", "01.4", "01.47", "99", "46.12"])
    def test_valid_codes(self, code: str) -> None:
        assert _OKVED_CODE_RE.match(code), f"should accept {code}"

    @pytest.mark.parametrize(
        "code",
        ["1", "1.1", "01.", "01.4.7", "ABC", "", "  01", "01.477"],
    )
    def test_invalid_codes(self, code: str) -> None:
        assert not _OKVED_CODE_RE.match(code), f"should reject {code!r}"


class TestNormalize:
    def test_drops_invalid_codes(self) -> None:
        raw = [
            {"code": "01.47", "label": "Птицеводство", "confidence": 0.9},
            {"code": "bad", "label": "nope", "confidence": 0.5},
            {"code": "01", "confidence": 0.7},
        ]
        out = _normalize_okved(raw)
        codes = [e["code"] for e in out]
        assert codes == ["01.47", "01"]  # sorted by confidence desc

    def test_clamps_confidence(self) -> None:
        raw = [
            {"code": "01", "confidence": 5.0},    # > 1
            {"code": "02", "confidence": -0.3},   # < 0
            {"code": "03", "confidence": "foo"},  # bad type
        ]
        out = _normalize_okved(raw)
        confidences = {e["code"]: e["confidence"] for e in out}
        assert confidences["01"] == 1.0
        assert confidences["02"] == 0.0
        assert confidences["03"] == 0.5   # default

    def test_dedupes_codes(self) -> None:
        raw = [
            {"code": "01.47", "confidence": 0.7},
            {"code": "01.47", "confidence": 0.9},
        ]
        assert len(_normalize_okved(raw)) == 1

    def test_caps_at_6(self) -> None:
        raw = [{"code": f"{i:02d}", "confidence": 0.5} for i in range(1, 15)]
        assert len(_normalize_okved(raw)) == 6

    def test_empty_or_malformed(self) -> None:
        assert _normalize_okved([]) == []
        assert _normalize_okved([None, "string", 42]) == []  # type: ignore[list-item]


class TestFromSegments:
    def test_feed_additives_segments(self) -> None:
        segments = ["птицефабрика", "свиноферма", "животноводческая ферма"]
        out = _okved_from_segments(segments)
        codes = {e["code"] for e in out}
        # should cover at least poultry + pigs
        assert "01.47" in codes
        assert "01.46" in codes

    def test_horeca_segments(self) -> None:
        segments = ["ресторан", "кафе", "отель"]
        out = _okved_from_segments(segments)
        codes = {e["code"] for e in out}
        assert "56.10" in codes or "55.10" in codes

    def test_empty_segments(self) -> None:
        assert _okved_from_segments([]) == []

    def test_unknown_segments_return_empty(self) -> None:
        """Highly specific niches the fallback map doesn't know about
        return empty rather than garbage — upstream will call LLM again
        or just show '— не определено'."""
        out = _okved_from_segments(["нейроинтерфейсы", "квантовые вычисления"])
        assert out == []

    def test_sorted_by_confidence_desc(self) -> None:
        segments = ["молочная ферма", "фермер", "кфх"]
        out = _okved_from_segments(segments)
        confidences = [e["confidence"] for e in out]
        assert confidences == sorted(confidences, reverse=True)
