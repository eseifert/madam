from __future__ import annotations

import io
from collections.abc import Callable, Iterable, Mapping
from typing import IO, Any
from xml.etree import ElementTree as ET

from madam.core import Asset, MetadataProcessor, ProcessingContext, Processor, UnsupportedFormatError, operator

_MM_TO_INCH = 1 / 25.4
_PX_PER_INCH = 90
_INCH_PER_PT = 1 / 72
_FONT_SIZE_PT = 12
_X_HEIGHT = 0.7


def svg_length_to_px(length: str | None) -> float:
    if length is None:
        raise ValueError()

    unit_len = 2
    if length.endswith('%'):
        unit_len = 1
    try:
        value = float(length)
        unit = 'px'
    except ValueError:
        value = float(length[:-unit_len])
        unit = length[-unit_len:]

    if unit == 'em':
        return value * _PX_PER_INCH * _FONT_SIZE_PT * _INCH_PER_PT
    elif unit == 'ex':
        return value * _PX_PER_INCH * _X_HEIGHT * _FONT_SIZE_PT * _INCH_PER_PT
    elif unit == 'px':
        return value
    elif unit == 'in':
        return value * _PX_PER_INCH
    elif unit == 'cm':
        return value * _PX_PER_INCH * _MM_TO_INCH * 10
    elif unit == 'mm':
        return value * _PX_PER_INCH * _MM_TO_INCH
    elif unit == 'pt':
        return value * _PX_PER_INCH * _INCH_PER_PT
    elif unit == 'pc':
        return value * _PX_PER_INCH * _INCH_PER_PT * 12
    elif unit == '%':
        return value
    raise ValueError()


def _is_zero_length_line(elem: ET.Element) -> bool:
    """Return True if a <line> element has zero length (both endpoints are identical)."""
    try:
        x1 = svg_length_to_px(elem.get('x1', '0'))
        y1 = svg_length_to_px(elem.get('y1', '0'))
        x2 = svg_length_to_px(elem.get('x2', '0'))
        y2 = svg_length_to_px(elem.get('y2', '0'))
    except ValueError:
        return False
    return x1 == x2 and y1 == y2


def _attr_is_zero(value: str | None) -> bool:
    """Return True if the attribute value represents a zero quantity."""
    if value is None:
        return False
    try:
        return svg_length_to_px(value) == 0.0
    except ValueError:
        return False


XML_NS = dict(
    dc='http://purl.org/dc/elements/1.1/',
    rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#',
    svg='http://www.w3.org/2000/svg',
    xlink='http://www.w3.org/1999/xlink',
)


def _register_xml_namespaces() -> None:
    for prefix, uri in XML_NS.items():
        if prefix == 'svg':
            prefix = ''
        ET.register_namespace(prefix, uri)


def _parse_svg(file: IO) -> tuple[ET.ElementTree[ET.Element], ET.Element]:
    _register_xml_namespaces()
    try:
        tree = ET.parse(file)
    except ET.ParseError as e:
        raise UnsupportedFormatError(f'Error while parsing XML in line {e.position[0]:d}, column {e.position[1]:d}')
    root = tree.getroot()
    if root.tag not in ('{%s}svg' % XML_NS['svg'], 'svg'):
        raise UnsupportedFormatError('XML file is not an SVG file.')
    return tree, root


def _write_svg(tree: ET.ElementTree[ET.Element]) -> IO:
    file = io.BytesIO()
    tree.write(file, xml_declaration=False, encoding='utf-8')
    file.seek(0)
    return file


def _remove_xml_whitespace(elem: ET.Element) -> None:
    for node in elem.iter():
        if node.text:
            node.text = node.text.strip()
        if node.tail:
            node.tail = node.tail.strip()


def _remove_elements(root: ET.Element, qname: str, keep_func: Callable[[ET.Element], bool]) -> None:
    parents = root.findall(f'.//{qname}/..', XML_NS)
    for parent in parents:
        for elem in parent.findall(f'./{qname}', XML_NS):
            if not keep_func(elem):
                parent.remove(elem)


def _shrink_svg(root: ET.Element) -> None:
    """Apply all shrink transforms to an SVG root element in place."""
    # Minify XML
    _remove_xml_whitespace(root)
    # Remove empty texts
    _remove_elements(root, 'svg:text', lambda e: bool(e.text and e.text.strip() or list(e)))
    # Remove all empty circles with radius 0
    _remove_elements(root, 'svg:circle', lambda e: bool(list(e)) or not _attr_is_zero(e.get('r')))
    # Remove all empty ellipses with x-axis or y-axis radius 0
    _remove_elements(
        root, 'svg:ellipse',
        lambda e: bool(list(e)) or not (_attr_is_zero(e.get('rx')) or _attr_is_zero(e.get('ry')))
    )
    # Remove all empty rectangles with width or height 0
    _remove_elements(
        root, 'svg:rect',
        lambda e: bool(list(e)) or not (_attr_is_zero(e.get('width')) or _attr_is_zero(e.get('height')))
    )
    # Remove all patterns with width or height 0
    _remove_elements(
        root, 'svg:pattern',
        lambda e: not (_attr_is_zero(e.get('width')) or _attr_is_zero(e.get('height')))
    )
    # Remove all images with width or height 0
    _remove_elements(
        root, 'svg:image',
        lambda e: not (_attr_is_zero(e.get('width')) or _attr_is_zero(e.get('height')))
    )
    # Remove all paths without coordinates
    _remove_elements(root, 'svg:path', lambda e: bool(e.get('d', '').strip()))
    # Remove all polygons without points
    _remove_elements(root, 'svg:polygon', lambda e: bool(e.get('points', '').strip()))
    # Remove all polylines without points
    _remove_elements(root, 'svg:polyline', lambda e: bool(e.get('points', '').strip()))
    # Remove all zero-length lines
    _remove_elements(root, 'svg:line', lambda e: bool(list(e)) or not _is_zero_length_line(e))
    # Remove all invisible or hidden elements
    _remove_elements(
        root,
        '*',
        lambda e: e.get('display') != 'none'
        and e.get('visibility') != 'hidden'
        and not _attr_is_zero(e.get('opacity')),
    )
    # Remove empty groups
    _remove_elements(root, 'svg:g', lambda e: bool(list(e)))
    # Remove empty defs
    _remove_elements(root, 'svg:defs', lambda e: bool(list(e)))


class SVGContext(ProcessingContext):
    """
    Deferred in-memory state for an SVG processing run.

    Holds a live :class:`xml.etree.ElementTree.ElementTree` so that
    consecutive SVG operators can transform the document without
    intermediate serialise/parse cycles.  Call :meth:`materialize` to
    produce the final encoded :class:`~madam.core.Asset`.

    Instances are created by :class:`SVGProcessor` and passed to
    :meth:`~madam.core.Processor.execute_run`.  Custom operator
    implementations can traverse or mutate :attr:`tree` in place before
    the result is serialised.

    :ivar tree: The live element tree being transformed.  Operators may
        modify its nodes in place or replace child elements.  The root
        element must remain a valid ``<svg>`` element.
    :vartype tree: xml.etree.ElementTree.ElementTree

    .. versionadded:: 1.0
    """

    def __init__(self, processor: 'SVGProcessor', tree: ET.ElementTree[ET.Element]) -> None:
        self._proc = processor
        self.tree = tree

    @property
    def processor(self) -> 'SVGProcessor':
        return self._proc

    def materialize(self) -> Asset:
        essence = _write_svg(self.tree)
        return self._proc.read(essence)


class SVGProcessor(Processor):
    """
    Represents a processor that handles *Scalable Vector Graphics* (SVG) data.
    """

    @property
    def supported_mime_types(self) -> frozenset:
        from madam.mime import MimeType
        return frozenset({MimeType('image/svg+xml')})

    def __init__(self, config: Mapping[str, Any] | None = None) -> None:
        """
        Initializes a new `SVGProcessor`.

        :param config: Mapping with settings.
        """
        super().__init__(config)

    def can_read(self, file: IO) -> bool:
        try:
            _parse_svg(file)
            return True
        except UnsupportedFormatError:
            return False

    def _parse_tree(self, file: IO) -> ET.ElementTree[ET.Element]:
        """Parse *file* into an :class:`ET.ElementTree` (one parse per deferred run)."""
        tree, _ = _parse_svg(file)
        return tree

    def execute_run(self, steps: list[Callable], asset_or_context: 'Asset | SVGContext') -> 'Asset | SVGContext':  # type: ignore[override]
        """
        Apply a group of consecutive SVG operators in a single parse/serialise cycle.

        The input :class:`~madam.core.Asset` (or incoming :class:`SVGContext` from
        a prior run) is parsed once.  Each step's XML transform is applied in
        memory via a ``_transform_*`` method.  The result is returned as an
        :class:`SVGContext` for the pipeline to serialise at the processor
        boundary or pipeline end.
        """
        if isinstance(asset_or_context, SVGContext):
            tree = asset_or_context.tree
        else:
            tree = self._parse_tree(asset_or_context.essence)

        for step in steps:
            op_name = getattr(getattr(step, 'func', None), '__name__', None)
            transform = getattr(self, f'_transform_{op_name}', None) if op_name else None
            if transform is not None:
                tree = transform(tree, **step.keywords)  # type: ignore[attr-defined]
            else:
                # Fallback: materialise current context, apply step, re-parse.
                tmp_ctx = SVGContext(self, tree)
                tmp_asset = tmp_ctx.materialize()
                result = step(tmp_asset)
                if isinstance(result, SVGContext):
                    tree = result.tree
                else:
                    tree = self._parse_tree(result.essence)

        return SVGContext(self, tree)

    def _transform_shrink(
        self,
        tree: ET.ElementTree[ET.Element],
    ) -> ET.ElementTree[ET.Element]:
        """Apply shrink transforms directly to the ElementTree (no parse/serialise)."""
        _shrink_svg(tree.getroot())
        return tree

    def read(self, file: IO) -> Asset:
        _, root = _parse_svg(file)

        metadata: dict[str, Any] = dict(mime_type='image/svg+xml')
        if 'width' in root.keys():
            metadata['width'] = svg_length_to_px(root.get('width'))
        if 'height' in root.keys():
            metadata['height'] = svg_length_to_px(root.get('height'))

        file.seek(0)
        return Asset(essence=file, **metadata)

    @operator
    def shrink(self, asset: Asset) -> Asset:
        """
        Shrinks the size of an SVG asset.

        :param asset: Media asset to be shrunk
        :type asset: Asset
        :return: Shrunk vector asset
        :rtype: Asset
        """
        tree, root = _parse_svg(asset.essence)
        _shrink_svg(root)
        essence = _write_svg(tree)

        metadata = dict(mime_type='image/svg+xml')
        for metadata_key in ('width', 'height'):
            if metadata_key in asset.metadata:
                metadata[metadata_key] = asset.metadata[metadata_key]

        return Asset(essence=essence, **metadata)


class SVGMetadataProcessor(MetadataProcessor):
    """
    Represents a metadata processor that handles Scalable Vector Graphics (SVG)
    data.

    It is assumed that the SVG XML uses UTF-8 encoding.
    """

    def __init__(self, config: Mapping[str, Any] | None = None) -> None:
        """
        Initializes a new `SVGMetadataProcessor`.

        :param config: Mapping with settings.
        """
        super().__init__(config)

    @property
    def formats(self) -> Iterable[str]:
        return {'rdf'}

    def read(self, file: IO) -> Mapping[str, Mapping]:
        _, root = _parse_svg(file)
        metadata_elem = root.find('./svg:metadata', XML_NS)
        if metadata_elem is None or len(metadata_elem) == 0:
            return {'rdf': {}}
        return {'rdf': {'xml': ET.tostring(metadata_elem[0], encoding='unicode')}}

    def strip(self, file: IO) -> IO:
        tree, root = _parse_svg(file)
        metadata_elem = root.find('./svg:metadata', XML_NS)

        if metadata_elem is not None:
            root.remove(metadata_elem)

        result = _write_svg(tree)
        return result

    def combine(self, file: IO, metadata: Mapping[str, Mapping]) -> IO:
        if not metadata:
            raise ValueError('No metadata provided.')
        if 'rdf' not in metadata:
            raise UnsupportedFormatError('No RDF metadata found.')
        rdf = metadata['rdf']
        if 'xml' not in rdf:
            raise ValueError('XML string missing from RDF metadata.')

        tree, root = _parse_svg(file)
        metadata_elem = root.find('./svg:metadata', XML_NS)

        if metadata_elem is None:
            metadata_elem = ET.SubElement(root, '{%(svg)s}metadata' % XML_NS)
        metadata_elem.append(ET.fromstring(rdf['xml']))

        result = _write_svg(tree)
        return result
