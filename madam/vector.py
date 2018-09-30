import io
from xml.etree import ElementTree as ET

from madam.core import Asset, MetadataProcessor, Processor, UnsupportedFormatError, operator


_INCH_TO_MM = 1 / 25.4
_PX_PER_INCH = 90
_PT_PER_INCH = 1 / 72
_FONT_SIZE_PT = 12
_X_HEIGHT = 0.7


def svg_length_to_px(length):
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
        return value * _PX_PER_INCH * _FONT_SIZE_PT * _PT_PER_INCH
    elif unit == 'ex':
        return value * _PX_PER_INCH * _X_HEIGHT * _FONT_SIZE_PT * _PT_PER_INCH
    elif unit == 'px':
        return value
    elif unit == 'in':
        return value * _PX_PER_INCH
    elif unit == 'cm':
        return value * _PX_PER_INCH * _INCH_TO_MM * 10
    elif unit == 'mm':
        return value * _PX_PER_INCH * _INCH_TO_MM
    elif unit == 'pt':
        return value * _PX_PER_INCH * _PT_PER_INCH
    elif unit == 'pc':
        return value * _PX_PER_INCH * _PT_PER_INCH * 12
    elif unit == '%':
        return value


XML_NS = dict(
    svg='http://www.w3.org/2000/svg',
    rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#',
    dc='http://purl.org/dc/elements/1.1/',
)


def _register_xml_namespaces():
    for prefix, uri in XML_NS.items():
        if prefix == 'svg':
            prefix = ''
        ET.register_namespace(prefix, uri)


def _parse_svg(file):
    _register_xml_namespaces()
    try:
        tree = ET.parse(file)
    except ET.ParseError as e:
        raise UnsupportedFormatError('Error while parsing XML in line %d, column %d' % e.position)
    root = tree.getroot()
    if root.tag not in ('{%s}svg' % XML_NS['svg'], 'svg'):
        raise UnsupportedFormatError('XML file is not an SVG file.')
    return tree, root


def _write_svg(tree):
    file = io.BytesIO()
    tree.write(file, xml_declaration=True, encoding='utf-8')
    file.seek(0)
    return file


class SVGProcessor(Processor):
    """
    Represents a processor that handles *Scalable Vector Graphics* (SVG) data.
    """
    def __init__(self):
        """
        Initializes a new `SVGProcessor`.
        """
        super().__init__()

    def can_read(self, file):
        try:
            _parse_svg(file)
            return True
        except UnsupportedFormatError:
            return False

    def read(self, file):
        _, root = _parse_svg(file)

        metadata = dict(mime_type='image/svg+xml')
        if 'width' in root.keys():
            metadata['width'] = svg_length_to_px(root.get('width'))
        if 'height' in root.keys():
            metadata['height'] = svg_length_to_px(root.get('height'))

        file.seek(0)
        return Asset(essence=file, **metadata)

    @operator
    def shrink(self, asset):
        """
        Shrinks the size of an SVG asset.

        :param asset: Media asset to be shrunk
        :type asset: Asset
        :return: Shrunk vector asset
        """
        tree, root = _parse_svg(asset.essence)

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
    def __init__(self):
        """
        Initializes a new `SVGMetadataProcessor`.
        """
        super().__init__()

    @property
    def formats(self):
        return {'rdf'}

    def read(self, file):
        _, root = _parse_svg(file)
        metadata_elem = root.find('./svg:metadata', XML_NS)
        if metadata_elem is None or len(metadata_elem) == 0:
            return {'rdf': {}}
        return {'rdf': {'xml': ET.tostring(metadata_elem[0], encoding='unicode')}}

    def strip(self, file):
        tree, root = _parse_svg(file)
        metadata_elem = root.find('./svg:metadata', XML_NS)

        if metadata_elem is not None:
            root.remove(metadata_elem)

        result = _write_svg(tree)
        return result

    def combine(self, file, metadata):
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
