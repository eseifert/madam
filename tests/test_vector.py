import io
from xml.etree import ElementTree as ET

import pytest

from madam.core import Asset
from madam.vector import XML_NS, SVGMetadataProcessor, SVGProcessor, UnsupportedFormatError, svg_length_to_px


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
        assert svg_length_to_px(None)  # noqa
    with pytest.raises(ValueError):
        assert svg_length_to_px('')


SVG_START = '<svg height="12px" version="1.1" width="24px" xmlns="http://www.w3.org/2000/svg">'
SVG_END = '</svg>'


def create_svg_asset(fragment=''):
    essence = io.BytesIO()
    essence.write(SVG_START.encode('utf-8'))
    essence.write(fragment.encode('utf-8'))
    essence.write(SVG_END.encode('utf-8'))
    essence.seek(0)
    return Asset(essence, mime_type='image/svg+xml')


class TestSVGProcessor:
    @pytest.fixture
    def processor(self):
        return SVGProcessor()

    def test_stores_configuration(self):
        config = dict(foo='bar')
        processor = SVGProcessor(config)

        assert processor.config['foo'] == 'bar'

    def test_read_fails_with_invalid_input(self, processor, unknown_asset):
        with pytest.raises(UnsupportedFormatError):
            processor.read(unknown_asset.essence)

    def test_read_fails_with_unknown_xml_data(self, processor, unknown_xml_asset):
        with pytest.raises(UnsupportedFormatError):
            processor.read(unknown_xml_asset.essence)

    def test_read_extracts_width_and_height_metadata(self, processor):
        with open('tests/resources/svg_with_metadata.svg', 'rb') as file:
            svg_vector_asset = processor.read(file)

        assert svg_vector_asset.width == 24
        assert svg_vector_asset.height == 12

    def test_shrink_fails_with_invalid_input(self, processor, unknown_asset):
        shrink_operator = processor.shrink()

        with pytest.raises(UnsupportedFormatError):
            shrink_operator(unknown_asset)

    def test_shrink_returns_valid_svg_xml(self, processor, svg_vector_asset):
        asset = svg_vector_asset
        shrink_operator = processor.shrink()

        shrunk_asset = shrink_operator(asset)

        tree = ET.parse(shrunk_asset.essence)
        root = tree.getroot()
        assert root.tag == '{http://www.w3.org/2000/svg}svg'

    def test_shrink_returns_smaller_or_equal_essence(self, processor, svg_vector_asset):
        asset = svg_vector_asset
        shrink_operator = processor.shrink()

        shrunk_asset = shrink_operator(asset)

        assert len(shrunk_asset.essence.read()) <= len(asset.essence.read())

    def test_shrink_strips_whitespace(self, processor):
        asset = create_svg_asset('\t<text> Hello MADAM! </text>\n\t<rect height="100%" width="100%" x="0" y="0" />\n')
        shrink_operator = processor.shrink()

        shrunk_asset = shrink_operator(asset)

        shrunk_fragment = shrunk_asset.essence.read().decode('utf-8')[len(SVG_START) : -len(SVG_END)]
        assert shrunk_fragment == '<text>Hello MADAM!</text><rect height="100%" width="100%" x="0" y="0" />'

    def test_shrink_removes_empty_texts(self, processor):
        asset = create_svg_asset('<text></text><text />')
        shrink_operator = processor.shrink()

        shrunk_asset = shrink_operator(asset)

        shrunk_fragment = shrunk_asset.essence.read().decode('utf-8')[len(SVG_START) : -len(SVG_END)]
        assert shrunk_fragment == ''

    def test_shrink_removes_circles_with_radius_zero(self, processor):
        asset = create_svg_asset('<circle r="0" />')
        shrink_operator = processor.shrink()

        shrunk_asset = shrink_operator(asset)

        shrunk_fragment = shrunk_asset.essence.read().decode('utf-8')[len(SVG_START) : -len(SVG_END)]
        assert shrunk_fragment == ''

    def test_shrink_removes_circles_with_radius_zero_float(self, processor):
        asset = create_svg_asset('<circle r="0.0" />')
        shrink_operator = processor.shrink()

        shrunk_asset = shrink_operator(asset)

        shrunk_fragment = shrunk_asset.essence.read().decode('utf-8')[len(SVG_START) : -len(SVG_END)]
        assert shrunk_fragment == ''

    def test_shrink_removes_ellipses_with_radius_zero(self, processor):
        asset = create_svg_asset('<ellipse rx="0" ry="1" /><ellipse rx="1" ry="0" />')
        shrink_operator = processor.shrink()

        shrunk_asset = shrink_operator(asset)

        shrunk_fragment = shrunk_asset.essence.read().decode('utf-8')[len(SVG_START) : -len(SVG_END)]
        assert shrunk_fragment == ''

    def test_shrink_removes_ellipses_with_radius_zero_float(self, processor):
        asset = create_svg_asset('<ellipse rx="0.0" ry="1" /><ellipse rx="1" ry="0.0" />')
        shrink_operator = processor.shrink()

        shrunk_asset = shrink_operator(asset)

        shrunk_fragment = shrunk_asset.essence.read().decode('utf-8')[len(SVG_START) : -len(SVG_END)]
        assert shrunk_fragment == ''

    def test_shrink_removes_rectangles_with_width_or_height_zero(self, processor):
        asset = create_svg_asset('<rect height="0" width="1" /><rect height="1" width="0" />')
        shrink_operator = processor.shrink()

        shrunk_asset = shrink_operator(asset)

        shrunk_fragment = shrunk_asset.essence.read().decode('utf-8')[len(SVG_START) : -len(SVG_END)]
        assert shrunk_fragment == ''

    def test_shrink_removes_rectangles_with_width_or_height_zero_float(self, processor):
        asset = create_svg_asset('<rect height="0.0" width="1" /><rect height="1" width="0.0" />')
        shrink_operator = processor.shrink()

        shrunk_asset = shrink_operator(asset)

        shrunk_fragment = shrunk_asset.essence.read().decode('utf-8')[len(SVG_START) : -len(SVG_END)]
        assert shrunk_fragment == ''

    def test_shrink_removes_patterns_with_width_or_height_zero(self, processor):
        asset = create_svg_asset(
            '<pattern height="10%" viewBox="0,0,10,10" width="0">'
            '<polygon points="0,0 2,5 0,10 5,8 10,10 8,5 10,0 5,2" />'
            '</pattern>'
        )
        shrink_operator = processor.shrink()

        shrunk_asset = shrink_operator(asset)

        shrunk_fragment = shrunk_asset.essence.read().decode('utf-8')[len(SVG_START) : -len(SVG_END)]
        assert shrunk_fragment == ''

    def test_shrink_removes_images_with_width_or_height_zero(self, processor):
        asset = create_svg_asset('<image height="0" width="1" /><image height="1" width="0" />')
        shrink_operator = processor.shrink()

        shrunk_asset = shrink_operator(asset)

        shrunk_fragment = shrunk_asset.essence.read().decode('utf-8')[len(SVG_START) : -len(SVG_END)]
        assert shrunk_fragment == ''

    def test_shrink_removes_zero_length_lines(self, processor):
        asset = create_svg_asset('<line x1="10" y1="20" x2="10" y2="20" /><line x1="0" y1="0" x2="0" y2="0" /><line />')
        shrink_operator = processor.shrink()

        shrunk_asset = shrink_operator(asset)

        shrunk_fragment = shrunk_asset.essence.read().decode('utf-8')[len(SVG_START) : -len(SVG_END)]
        assert shrunk_fragment == ''

    def test_shrink_keeps_nonzero_lines(self, processor):
        asset = create_svg_asset('<line x1="0" y1="0" x2="10" y2="20" />')
        shrink_operator = processor.shrink()

        shrunk_asset = shrink_operator(asset)

        shrunk_fragment = shrunk_asset.essence.read().decode('utf-8')[len(SVG_START) : -len(SVG_END)]
        assert shrunk_fragment != ''

    def test_shrink_removes_empty_paths(self, processor):
        asset = create_svg_asset('<path d="" /><path d=" " />')
        shrink_operator = processor.shrink()

        shrunk_asset = shrink_operator(asset)

        shrunk_fragment = shrunk_asset.essence.read().decode('utf-8')[len(SVG_START) : -len(SVG_END)]
        assert shrunk_fragment == ''

    def test_shrink_removes_empty_polygons(self, processor):
        asset = create_svg_asset('<polygon points="" /><polygon points=" " />')
        shrink_operator = processor.shrink()

        shrunk_asset = shrink_operator(asset)

        shrunk_fragment = shrunk_asset.essence.read().decode('utf-8')[len(SVG_START) : -len(SVG_END)]
        assert shrunk_fragment == ''

    def test_shrink_removes_empty_polylines(self, processor):
        asset = create_svg_asset('<polyline points="" /><polyline points=" " />')
        shrink_operator = processor.shrink()

        shrunk_asset = shrink_operator(asset)

        shrunk_fragment = shrunk_asset.essence.read().decode('utf-8')[len(SVG_START) : -len(SVG_END)]
        assert shrunk_fragment == ''

    def test_shrink_removes_hidden_elements(self, processor):
        asset = create_svg_asset(
            '<text visibility="hidden">Hidden</text>'
            '<text display="none">Invisible</text>'
            '<text opacity="0">Transparent</text>'
            '<text opacity="0.0">Transparent float</text>'
        )
        shrink_operator = processor.shrink()

        shrunk_asset = shrink_operator(asset)

        shrunk_fragment = shrunk_asset.essence.read().decode('utf-8')[len(SVG_START) : -len(SVG_END)]
        assert shrunk_fragment == ''

    def test_shrink_removes_empty_groups(self, processor):
        asset = create_svg_asset('<g> </g><g />')
        shrink_operator = processor.shrink()

        shrunk_asset = shrink_operator(asset)

        shrunk_fragment = shrunk_asset.essence.read().decode('utf-8')[len(SVG_START) : -len(SVG_END)]
        assert shrunk_fragment == ''

    def test_shrink_handles_deeply_nested_svg(self, processor):
        # Regression test: __remove_xml_whitespace was recursive and crashed on deep trees
        depth = 200
        inner = '<text> Hello </text>'
        for _ in range(depth):
            inner = f'<g>{inner}</g>'
        asset = create_svg_asset(inner)
        shrink_operator = processor.shrink()

        shrunk_asset = shrink_operator(asset)

        tree = ET.parse(shrunk_asset.essence)
        assert tree.getroot() is not None

    def test_shrink_removes_xml_comments(self, processor):
        asset = create_svg_asset('<!-- this is a comment --><rect height="100%" width="100%" />')
        shrink_operator = processor.shrink()

        shrunk_asset = shrink_operator(asset)

        content = shrunk_asset.essence.read().decode('utf-8')
        assert '<!--' not in content

    def test_shrink_removes_empty_defs(self, processor):
        asset = create_svg_asset('<defs></defs>')
        shrink_operator = processor.shrink()

        shrunk_asset = shrink_operator(asset)

        shrunk_fragment = shrunk_asset.essence.read().decode('utf-8')[len(SVG_START) : -len(SVG_END)]
        assert shrunk_fragment == ''


class TestSVGMetadataProcessor:
    VALID_RDF_METADATA = dict(
        rdf=dict(
            xml='<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"'
            ' xmlns:dc="http://purl.org/dc/elements/1.1/"'
            ' xmlns:opf="http://www.idpf.org/2007/opf">'
            '<rdf:Description rdf:about="svg_with_metadata.svg">'
            '<dc:format>image/svg+xml</dc:format><dc:type>Image</dc:type>'
            '<dc:description>Example SVG file with metadata</dc:description>'
            '</rdf:Description></rdf:RDF>'
        )
    )

    @pytest.fixture
    def processor(self):
        return SVGMetadataProcessor()

    def test_stores_configuration(self):
        config = dict(foo='bar')
        processor = SVGMetadataProcessor(config)

        assert processor.config['foo'] == 'bar'

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

    def test_read_fails_with_unknown_xml_data(self, processor, unknown_xml_asset):
        with pytest.raises(UnsupportedFormatError):
            processor.read(unknown_xml_asset.essence)

    def test_read_returns_empty_dict_when_svg_contains_no_metadata(self, processor, svg_vector_asset):
        essence_without_metadata = svg_vector_asset.essence

        metadata = processor.read(essence_without_metadata)

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

    def test_combine_returns_svg_with_metadata(self, processor, svg_vector_asset):
        essence = svg_vector_asset.essence
        metadata = self.VALID_RDF_METADATA

        essence_with_metadata = processor.combine(essence, metadata)

        tree = ET.parse(essence_with_metadata)
        root = tree.getroot()
        metadata_elem = root.find('./svg:metadata', XML_NS)
        assert metadata_elem is not None
        rdf_elem = metadata_elem.find('./rdf:RDF', XML_NS)
        assert rdf_elem is not None

    def test_combine_raises_error_when_no_rdf_dict_is_given(self, processor, svg_vector_asset):
        metadata = {}

        with pytest.raises(ValueError):
            processor.combine(svg_vector_asset.essence, metadata)

    def test_combine_fails_without_metadata_keys(self, processor, svg_vector_asset):
        essence = svg_vector_asset.essence
        metadata = dict(rdf=dict())

        with pytest.raises(ValueError):
            processor.combine(essence, metadata)

    def test_combine_raises_error_when_essence_format_is_unsupported(self, processor, unknown_asset):
        junk_data = unknown_asset.essence
        metadata = self.VALID_RDF_METADATA

        with pytest.raises(UnsupportedFormatError):
            processor.combine(junk_data, metadata)

    def test_combine_raises_error_when_metadata_format_is_unsupported(self, processor, svg_vector_asset):
        rdf = {'123abc': 'Test artist'}

        with pytest.raises(UnsupportedFormatError):
            processor.combine(svg_vector_asset.essence, rdf)  # noqa

    def test_combine_raises_error_when_metadata_contains_unsupported_keys(self, processor, svg_vector_asset):
        metadata = dict(rdf=dict(foo='bar'))

        with pytest.raises(ValueError):
            processor.combine(svg_vector_asset.essence, metadata)


SVG_SIMPLE = (
    b'<svg height="12px" version="1.1" width="24px" xmlns="http://www.w3.org/2000/svg">'
    b'<rect width="24px" height="12px"/>'
    b'</svg>'
)


class TestSVGContext:
    def test_svg_context_is_importable(self):
        from madam.vector import SVGContext  # noqa: F401

    def test_svg_context_holds_tree_and_processor(self):
        from xml.etree import ElementTree as ET

        from madam.vector import SVGContext

        proc = SVGProcessor()
        tree = ET.ElementTree(ET.fromstring('<svg xmlns="http://www.w3.org/2000/svg"/>'))
        ctx = SVGContext(proc, tree)

        assert ctx.tree is tree
        assert ctx.processor is proc

    def test_svg_context_is_processing_context_subclass(self):
        from madam.core import ProcessingContext
        from madam.vector import SVGContext

        assert issubclass(SVGContext, ProcessingContext)

    def test_svg_context_materialize_returns_svg_asset(self):
        import io

        from madam.vector import SVGContext

        proc = SVGProcessor()
        asset = proc.read(io.BytesIO(SVG_SIMPLE))
        ctx = SVGContext(proc, proc._parse_tree(asset.essence))

        result = ctx.materialize()

        assert result.mime_type == 'image/svg+xml'
        assert result.width == pytest.approx(24, abs=1e-5)
        assert result.height == pytest.approx(12, abs=1e-5)


class TestSVGDeferredExecution:
    def test_shrink_twice_parses_svg_only_once(self):
        """Two shrink operators in a Pipeline must parse the SVG only once."""
        import io

        from madam.core import Pipeline

        proc = SVGProcessor()
        asset = proc.read(io.BytesIO(SVG_SIMPLE))

        shrink1 = proc.shrink()
        shrink2 = proc.shrink()
        pipeline = Pipeline()
        pipeline.add(shrink1)
        pipeline.add(shrink2)

        parse_calls = []
        original_parse = proc._parse_tree

        def counting_parse(file):
            parse_calls.append(1)
            return original_parse(file)

        proc._parse_tree = counting_parse

        try:
            result = list(pipeline.process(asset))
        finally:
            proc._parse_tree = original_parse

        assert len(parse_calls) == 1, f'Expected 1 parse call, got {len(parse_calls)}'
        assert result[0].mime_type == 'image/svg+xml'


def test_svg_length_to_px_raises_for_unknown_unit():
    with pytest.raises(ValueError):
        svg_length_to_px('42vw')


def test_is_zero_length_line_returns_false_for_invalid_lengths():
    from madam.vector import _is_zero_length_line

    elem = ET.Element('line')
    elem.set('x1', 'invalid')
    # Must not raise; returns False when conversion fails.
    assert _is_zero_length_line(elem) is False


def test_attr_is_zero_returns_false_for_invalid_value():
    from madam.vector import _attr_is_zero

    assert _attr_is_zero('invalid_unit_xyz') is False


class TestSVGDeferredFallback:
    """execute_run fallback: operator without a _transform_* method."""

    def test_execute_run_with_unknown_operator_uses_fallback(self):
        import functools


        proc = SVGProcessor()
        asset = proc.read(io.BytesIO(SVG_SIMPLE))

        # Build a step whose func.__name__ has no matching _transform_* on SVGProcessor.
        # The step returns an Asset, triggering the re-parse branch (line 267).
        def identity_asset(proc_instance: SVGProcessor, a: Asset) -> Asset:
            return a

        step = functools.partial(identity_asset, proc)
        step._processor = proc  # type: ignore[attr-defined]

        result_ctx = proc.execute_run([step], asset)
        assert result_ctx.materialize().mime_type == 'image/svg+xml'

    def test_execute_run_fallback_step_returning_svg_context(self):
        import functools

        from madam.vector import SVGContext

        proc = SVGProcessor()
        asset = proc.read(io.BytesIO(SVG_SIMPLE))

        # Step returns an SVGContext (not an Asset), triggering line 265.
        def identity_ctx(proc_instance: SVGProcessor, a: Asset) -> SVGContext:
            tree = proc._parse_tree(a.essence)
            return SVGContext(proc, tree)

        step = functools.partial(identity_ctx, proc)
        step._processor = proc  # type: ignore[attr-defined]

        result_ctx = proc.execute_run([step], asset)
        assert result_ctx.materialize().mime_type == 'image/svg+xml'

    def test_execute_run_accepts_svg_context_as_input(self):
        from madam.vector import SVGContext

        proc = SVGProcessor()
        asset = proc.read(io.BytesIO(SVG_SIMPLE))

        # First call: asset → SVGContext
        ctx = proc.execute_run([], asset)
        assert isinstance(ctx, SVGContext)

        # Second call: SVGContext → SVGContext (hits line 250)
        ctx2 = proc.execute_run([], ctx)
        assert isinstance(ctx2, SVGContext)
        assert ctx2.materialize().mime_type == 'image/svg+xml'
