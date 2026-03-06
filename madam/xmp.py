"""
XMP metadata processor for JPEG images.

Reads and writes XMP metadata embedded in the JPEG APP1 block using the
standard library ``xml.etree.ElementTree``.  No additional dependencies
beyond Pillow are required.

Only JPEG is currently supported.  XMP is also present in PNG (iTXt chunk)
and TIFF (tag 700), but those formats are not handled by this module.
"""

from __future__ import annotations

import io
import struct
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Mapping
from typing import IO, Any

from madam.core import MetadataProcessor, UnsupportedFormatError

# XMP namespace URI prefix that identifies an XMP APP1 segment in JPEG.
_XMP_HEADER = b'http://ns.adobe.com/xap/1.0/\x00'

# XML namespace URIs used in XMP packets.
_NS = {
    'x': 'adobe:ns:meta/',
    'rdf': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#',
    'dc': 'http://purl.org/dc/elements/1.1/',
    'xmp': 'http://ns.adobe.com/xap/1.0/',
    'xmpRights': 'http://ns.adobe.com/xap/1.0/rights/',
}

# Register namespaces so ET serializes them with their canonical prefixes.
for _prefix, _uri in _NS.items():
    ET.register_namespace(_prefix, _uri)


def _q(prefix: str, local: str) -> str:
    """Return a Clark-notation tag name for *prefix:local*."""
    return f'{{{_NS[prefix]}}}{local}'


def _find_xmp_in_jpeg(data: bytes) -> bytes | None:
    """Return the raw XMP packet bytes from a JPEG, or ``None`` if absent."""
    pos = 0
    length = len(data)
    while pos < length:
        if data[pos] != 0xFF:
            break
        marker_byte = data[pos + 1]
        if marker_byte in (0xD8, 0xD9, 0x01) or 0xD0 <= marker_byte <= 0xD7:
            pos += 2
            continue
        seg_len = struct.unpack('>H', data[pos + 2 : pos + 4])[0]
        seg_data = data[pos + 4 : pos + 2 + seg_len]
        if marker_byte == 0xE1 and seg_data.startswith(_XMP_HEADER):
            return seg_data[len(_XMP_HEADER) :]
        pos += 2 + seg_len
    return None


def _extract_lang_alt(desc: ET.Element, ns_prefix: str, local: str) -> str | None:
    """Return the x-default (or first) text from an RDF lang Alt structure."""
    elem = desc.find(f'{_q(ns_prefix, local)}/{_q("rdf", "Alt")}/{_q("rdf", "li")}')
    if elem is not None:
        return elem.text
    return None


def _extract_seq(desc: ET.Element, ns_prefix: str, local: str) -> list[str] | None:
    """Return items from an RDF Seq or Bag structure as a list of strings."""
    container = desc.find(f'{_q(ns_prefix, local)}/{_q("rdf", "Seq")}')
    if container is None:
        container = desc.find(f'{_q(ns_prefix, local)}/{_q("rdf", "Bag")}')
    if container is None:
        return None
    return [li.text or '' for li in container.findall(_q('rdf', 'li'))]


def _extract_simple(desc: ET.Element, ns_prefix: str, local: str) -> str | None:
    """Return text of a simple (non-structured) XMP property."""
    elem = desc.find(_q(ns_prefix, local))
    if elem is not None:
        return elem.text
    return None


def _build_xmp_packet(fields: Mapping[str, Any]) -> bytes:
    """Serialize *fields* into a minimal XMP packet (bytes)."""
    x_ns = _NS['x']
    rdf_ns = _NS['rdf']
    dc_ns = _NS['dc']
    xmp_ns = _NS['xmp']

    xmpmeta = ET.Element(f'{{{x_ns}}}xmpmeta')
    rdf_root = ET.SubElement(xmpmeta, f'{{{rdf_ns}}}RDF')
    desc = ET.SubElement(rdf_root, f'{{{rdf_ns}}}Description')
    desc.set(f'{{{rdf_ns}}}about', '')

    for key, value in fields.items():
        if key == 'title':
            el = ET.SubElement(desc, f'{{{dc_ns}}}title')
            alt = ET.SubElement(el, f'{{{rdf_ns}}}Alt')
            li = ET.SubElement(alt, f'{{{rdf_ns}}}li')
            li.set('{http://www.w3.org/XML/1998/namespace}lang', 'x-default')
            li.text = str(value)
        elif key == 'description':
            el = ET.SubElement(desc, f'{{{dc_ns}}}description')
            alt = ET.SubElement(el, f'{{{rdf_ns}}}Alt')
            li = ET.SubElement(alt, f'{{{rdf_ns}}}li')
            li.set('{http://www.w3.org/XML/1998/namespace}lang', 'x-default')
            li.text = str(value)
        elif key == 'subject':
            el = ET.SubElement(desc, f'{{{dc_ns}}}subject')
            bag = ET.SubElement(el, f'{{{rdf_ns}}}Bag')
            items = [value] if isinstance(value, str) else list(value)
            for item in items:
                li = ET.SubElement(bag, f'{{{rdf_ns}}}li')
                li.text = str(item)
        elif key == 'rights':
            el = ET.SubElement(desc, f'{{{dc_ns}}}rights')
            alt = ET.SubElement(el, f'{{{rdf_ns}}}Alt')
            li = ET.SubElement(alt, f'{{{rdf_ns}}}li')
            li.set('{http://www.w3.org/XML/1998/namespace}lang', 'x-default')
            li.text = str(value)
        elif key == 'creator':
            el = ET.SubElement(desc, f'{{{dc_ns}}}creator')
            seq = ET.SubElement(el, f'{{{rdf_ns}}}Seq')
            li = ET.SubElement(seq, f'{{{rdf_ns}}}li')
            li.text = str(value)
        elif key == 'create_date':
            el = ET.SubElement(desc, f'{{{xmp_ns}}}CreateDate')
            el.text = str(value)
        elif key == 'modify_date':
            el = ET.SubElement(desc, f'{{{xmp_ns}}}ModifyDate')
            el.text = str(value)

    xml_bytes = ET.tostring(xmpmeta, encoding='unicode', xml_declaration=False).encode('utf-8')
    packet = b'<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?>\n' + xml_bytes + b'\n<?xpacket end="w"?>'
    return packet


class XMPMetadataProcessor(MetadataProcessor):
    """
    Reads and writes XMP metadata embedded in JPEG files.

    XMP data is stored in the JPEG APP1 block identified by the namespace
    URI ``http://ns.adobe.com/xap/1.0/``.  Only JPEG is supported; attempts
    to read non-JPEG data raise :class:`~madam.core.UnsupportedFormatError`.

    Supported metadata keys under the ``'xmp'`` namespace:

    * ``title`` — dc:title (x-default language alternative)
    * ``description`` — dc:description (x-default language alternative)
    * ``subject`` — dc:subject, list of strings (RDF Bag)
    * ``rights`` — dc:rights (x-default language alternative)
    * ``creator`` — dc:creator, first item of RDF Seq
    * ``create_date`` — xmp:CreateDate (ISO 8601 string)
    * ``modify_date`` — xmp:ModifyDate (ISO 8601 string)

    .. versionadded:: 0.24
    """

    def __init__(self, config: Mapping[str, Any] | None = None) -> None:
        """
        Initializes a new ``XMPMetadataProcessor``.

        :param config: Mapping with settings.
        """
        super().__init__(config)

    @property
    def formats(self) -> Iterable[str]:
        return {'xmp'}

    def read(self, file: IO) -> Mapping[str, Mapping]:
        """
        Reads XMP metadata from a JPEG file.

        :param file: Readable binary file-like object containing JPEG data.
        :type file: IO
        :return: Mapping with a single ``'xmp'`` key whose value is a dict of
                 decoded metadata fields.  Returns an empty mapping when the
                 file contains no XMP data.
        :rtype: Mapping[str, Mapping]
        :raises UnsupportedFormatError: if the data is not a JPEG file.
        """
        data = file.read()
        if not data.startswith(b'\xff\xd8'):
            raise UnsupportedFormatError('XMP metadata is only supported for JPEG files.')

        xmp_packet = _find_xmp_in_jpeg(data)
        if xmp_packet is None:
            return {}

        try:
            root = ET.fromstring(xmp_packet)
        except ET.ParseError as exc:
            raise UnsupportedFormatError(f'Could not parse XMP packet: {exc}') from exc

        # Locate the rdf:Description element (may be nested).
        desc = root.find(f'.//{_q("rdf", "Description")}')
        if desc is None:
            return {}

        xmp: dict[str, Any] = {}

        title = _extract_lang_alt(desc, 'dc', 'title')
        if title is not None:
            xmp['title'] = title

        description = _extract_lang_alt(desc, 'dc', 'description')
        if description is not None:
            xmp['description'] = description

        subject = _extract_seq(desc, 'dc', 'subject')
        if subject is not None:
            xmp['subject'] = subject

        rights = _extract_lang_alt(desc, 'dc', 'rights')
        if rights is not None:
            xmp['rights'] = rights

        creator_seq = _extract_seq(desc, 'dc', 'creator')
        if creator_seq:
            xmp['creator'] = creator_seq[0]

        create_date = _extract_simple(desc, 'xmp', 'CreateDate')
        if create_date is not None:
            xmp['create_date'] = create_date

        modify_date = _extract_simple(desc, 'xmp', 'ModifyDate')
        if modify_date is not None:
            xmp['modify_date'] = modify_date

        if not xmp:
            return {}
        return {'xmp': xmp}

    def strip(self, file: IO) -> IO:
        """
        Returns a copy of the JPEG file with all XMP (APP1 XMP) data removed.

        :param file: Readable binary file-like object containing JPEG data.
        :type file: IO
        :return: File-like object with XMP data removed.
        :rtype: IO
        :raises UnsupportedFormatError: if the data is not a JPEG file.
        """
        data = file.read()
        if not data.startswith(b'\xff\xd8'):
            raise UnsupportedFormatError('XMP strip is only supported for JPEG files.')

        result = io.BytesIO()
        pos = 0
        length = len(data)

        while pos < length:
            if data[pos] != 0xFF:
                result.write(data[pos:])
                break
            marker_byte = data[pos + 1]
            marker = data[pos : pos + 2]

            if marker_byte in (0xD8, 0xD9, 0x01) or 0xD0 <= marker_byte <= 0xD7:
                result.write(marker)
                pos += 2
            else:
                seg_len = struct.unpack('>H', data[pos + 2 : pos + 4])[0]
                seg_end = pos + 2 + seg_len
                seg_data = data[pos + 4 : seg_end]
                if marker_byte == 0xE1 and seg_data.startswith(_XMP_HEADER):
                    # XMP APP1 — skip
                    pos = seg_end
                else:
                    result.write(data[pos:seg_end])
                    pos = seg_end

        result.seek(0)
        return result

    def combine(self, file: IO, metadata: Mapping[str, Mapping]) -> IO:
        """
        Returns a copy of the JPEG file with XMP metadata embedded.

        Existing XMP data is replaced.  Only the ``'xmp'`` key of *metadata*
        is used; other keys are ignored.

        :param file: Readable binary file-like object containing JPEG data.
        :type file: IO
        :param metadata: Mapping with an ``'xmp'`` key whose value is a dict
                         of XMP field names and values.
        :type metadata: Mapping
        :return: File-like object with XMP data embedded.
        :rtype: IO
        :raises UnsupportedFormatError: if *metadata* contains an unknown
                                         XMP format key.
        """
        for fmt in metadata:
            if fmt not in self.formats:
                raise UnsupportedFormatError(f'Metadata format {fmt!r} is not supported.')

        stripped = self.strip(file)
        stripped.seek(0)
        jpeg_data = stripped.read()

        xmp_fields = metadata.get('xmp', {})
        if not xmp_fields:
            result = io.BytesIO(jpeg_data)
            result.seek(0)
            return result

        xmp_packet = _build_xmp_packet(xmp_fields)
        app1_data = _XMP_HEADER + xmp_packet
        app1_length = 2 + len(app1_data)
        app1 = b'\xff\xe1' + struct.pack('>H', app1_length) + app1_data

        # Insert XMP APP1 after the SOI marker.
        result = io.BytesIO(jpeg_data[:2] + app1 + jpeg_data[2:])
        result.seek(0)
        return result
