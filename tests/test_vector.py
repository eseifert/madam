import pytest

from madam.vector import svg_length_to_px, SVGMetdataProcessor


def test_svg_length_to_px_works_for_valid_values():
    assert svg_length_to_px('42') == pytest.approx(42, abs=1e-5)
    assert svg_length_to_px('1em') == pytest.approx(15, abs=1e-5)
    assert svg_length_to_px('1ex') == pytest.approx(10.5, abs=1e-5)
    assert svg_length_to_px('42px') == pytest.approx(42, abs=1e-5)
    assert svg_length_to_px('1in') == pytest.approx(90, abs=1e-5)
    assert svg_length_to_px('2.54cm') == pytest.approx(90, abs=1e-5)
    assert svg_length_to_px('25.4mm') == pytest.approx(90, abs=1e-5)
    assert svg_length_to_px('12pt') == pytest.approx(15, abs=1e-5)
    assert svg_length_to_px('12pc') == pytest.approx(180, abs=1e-5)
    assert svg_length_to_px('42%') == pytest.approx(42, abs=1e-5)


def test_svg_length_to_px_fails_for_invalid_values():
    with pytest.raises(ValueError):
        assert svg_length_to_px(None)
    with pytest.raises(ValueError):
        assert svg_length_to_px('')


class TestSVGMetdataProcessor:
    @pytest.fixture
    def svg_metadata_processor(self):
        return SVGMetdataProcessor()
