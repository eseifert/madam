import io
from xml.etree import ElementTree as ET

import pytest

from madam.vector import svg_length_to_px, SVGMetadataProcessor, UnsupportedFormatError, XML_NS
from assets import svg_asset, unknown_asset


EXAMPLE_RDF = dict(rdf=
        dict(xml=
             '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"'
             ' xmlns:dc="http://purl.org/dc/elements/1.1/"'
             ' xmlns:opf="http://www.idpf.org/2007/opf">'
             '<rdf:Description rdf:about="svg_with_metadata.svg">'
             '<dc:format>image/svg+xml</dc:format><dc:type>Image</dc:type>'
             '<dc:description>Example SVG file with metadata</dc:description>'
             '</rdf:Description></rdf:RDF>'
        )
    )


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


class TestSVGMetadataProcessor:
    @pytest.fixture
    def processor(self):
        return SVGMetadataProcessor()

    def test_supports_rdf_metadata(self, processor):
        assert 'rdf' in processor.formats

    def test_read_returns_correct_metadata_dict_for_svg_with_rdf(self, processor):
        with open('tests/resources/svg_with_metadata.svg', 'rb') as file:
            metadata = processor.read(file)

        assert metadata['rdf']['xml']
        assert len(metadata) == 1

    def test_read_raises_error_when_file_format_is_unsupported(self, processor, unknown_asset):
        junk_data = unknown_asset.essence

        with pytest.raises(UnsupportedFormatError):
            processor.read(junk_data)

    def test_read_returns_empty_dict_when_svg_contains_no_metadata(self, processor, svg_asset):
        tree = ET.parse(svg_asset.essence)
        root = tree.getroot()
        metadata_elem = root.find('./svg:metadata', XML_NS)
        root.remove(metadata_elem)
        data_without_rdf = io.BytesIO()
        tree.write(data_without_rdf)
        data_without_rdf.seek(0)

        metadata = processor.read(data_without_rdf)

        assert not metadata['rdf']

    def test_strip_returns_essence_without_metadata(self, processor):
        with open('tests/resources/svg_with_metadata.svg', 'rb') as file:
            essence = file.read()
            file.seek(0)
            stripped_essence = processor.strip(file).read()

        assert essence != stripped_essence

    def test_strip_raises_error_when_file_format_is_unsupported(self, processor, unknown_asset):
        junk_data = unknown_asset.essence

        with pytest.raises(UnsupportedFormatError):
            processor.strip(junk_data)

    def test_combine_returns_svg_with_metadata(self, processor, svg_asset):
        essence = svg_asset.essence
        metadata = EXAMPLE_RDF

        essence_with_metadata = processor.combine(essence, metadata)

        tree = ET.parse(essence_with_metadata)
        root = tree.getroot()
        metadata_elem = root.find('./svg:metadata', XML_NS)
        assert metadata_elem is not None
        rdf_elem = metadata_elem.find('./rdf:RDF', XML_NS)
        assert rdf_elem is not None

    def test_combine_raises_error_when_no_rdf_dict_is_given(self, processor, svg_asset):
        metadata = {}

        with pytest.raises(ValueError):
            processor.combine(svg_asset.essence, metadata)

    def test_combine_fails_without_metadata_keys(self, processor, svg_asset):
        essence = svg_asset.essence
        metadata = dict(rdf=dict())

        with pytest.raises(ValueError):
            processor.combine(essence, metadata)

    def test_combine_raises_error_when_essence_format_is_unsupported(self, processor, unknown_asset):
        junk_data = unknown_asset.essence
        metadata = EXAMPLE_RDF

        with pytest.raises(UnsupportedFormatError):
            processor.combine(junk_data, metadata)
