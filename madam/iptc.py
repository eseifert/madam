"""
IPTC/IIM metadata processor for JPEG images.

Reads and writes IPTC Application Record (record 2) fields embedded in
the JPEG APP13/Photoshop 3.0 block.  No additional dependencies beyond
Pillow are required.
"""

from __future__ import annotations

import io
import struct
from collections.abc import Iterable, Mapping
from typing import IO, Any

import PIL.Image
import PIL.IptcImagePlugin

from madam.core import MetadataProcessor, UnsupportedFormatError

# Mapping from IPTC Application Record dataset numbers to friendly names.
# Only dataset numbers that map to a single value are listed here; the
# special case of keywords (repeatable) is handled separately.
_DATASET_TO_KEY: dict[int, str] = {
    5: 'object_name',
    15: 'category',
    40: 'instructions',
    80: 'author',
    85: 'author_title',
    90: 'city',
    92: 'sublocation',
    95: 'state',
    100: 'country_code',
    101: 'country',
    105: 'headline',
    110: 'credit',
    115: 'source',
    116: 'copyright',
    120: 'caption',
}

# Repeatable fields: stored as lists of strings.
_REPEATABLE_DATASETS: frozenset[int] = frozenset({25})  # keywords

_KEY_TO_DATASET: dict[str, int] = {v: k for k, v in _DATASET_TO_KEY.items()}
_KEY_TO_DATASET['keywords'] = 25


def _make_iptc_record(dataset: int, data: str | bytes) -> bytes:
    """Return a single IPTC IIM record for Application Record 2."""
    if isinstance(data, str):
        data = data.encode('latin-1', errors='replace')
    return bytes([0x1C, 2, dataset]) + struct.pack('>H', len(data)) + data


def _make_8bim(resource_type: int, data: bytes) -> bytes:
    """Wrap *data* in a Photoshop 8BIM resource block."""
    name = b'\x00\x00'  # empty Pascal string with even-alignment padding
    block = b'8BIM' + struct.pack('>H', resource_type) + name + struct.pack('>I', len(data)) + data
    if len(data) % 2 == 1:
        block += b'\x00'  # pad to even boundary
    return block


def _build_app13(iptc_records: bytes) -> bytes:
    """Wrap IPTC IIM records in a JPEG APP13 marker."""
    photoshop = b'Photoshop 3.0\x00' + _make_8bim(0x0404, iptc_records)
    length = 2 + len(photoshop)
    return b'\xff\xed' + struct.pack('>H', length) + photoshop


def _iter_jpeg_markers(data: bytes):
    """
    Yield ``(marker_bytes, payload_bytes)`` tuples for each marker in *data*.

    *marker_bytes* is the 2-byte marker code (e.g. ``b'\\xff\\xd8'``).
    *payload_bytes* is the raw segment data without the marker or length field,
    or ``None`` for stand-alone markers (SOI, EOI, RST*).
    """
    pos = 0
    length = len(data)
    while pos < length:
        if data[pos] != 0xFF:
            break
        marker = data[pos : pos + 2]
        marker_byte = data[pos + 1]
        pos += 2
        # Stand-alone markers: SOI (D8), EOI (D9), RST0-RST7 (D0-D7), TEM (01)
        if marker_byte in (0xD8, 0xD9, 0x01) or 0xD0 <= marker_byte <= 0xD7:
            yield marker, None
        else:
            seg_length = struct.unpack('>H', data[pos : pos + 2])[0]
            payload = data[pos + 2 : pos + seg_length]
            yield marker, payload
            pos += seg_length


class IPTCMetadataProcessor(MetadataProcessor):
    """
    Reads and writes IPTC/IIM metadata embedded in JPEG files.

    IPTC data is stored in the JPEG APP13 (Photoshop 3.0) block.  Only
    JPEG is supported; attempts to read non-JPEG data raise
    :class:`~madam.core.UnsupportedFormatError`.

    Supported metadata keys under the ``'iptc'`` namespace:

    * ``object_name`` — Object Name (dataset 5)
    * ``category`` — Category (dataset 15)
    * ``keywords`` — Keywords, list of strings (dataset 25, repeatable)
    * ``instructions`` — Special Instructions (dataset 40)
    * ``author`` — By-line / Author (dataset 80)
    * ``author_title`` — By-line Title (dataset 85)
    * ``city`` — City (dataset 90)
    * ``sublocation`` — Sublocation (dataset 92)
    * ``state`` — Province/State (dataset 95)
    * ``country_code`` — Country Code (dataset 100)
    * ``country`` — Country (dataset 101)
    * ``headline`` — Headline (dataset 105)
    * ``credit`` — Credit (dataset 110)
    * ``source`` — Source (dataset 115)
    * ``copyright`` — Copyright Notice (dataset 116)
    * ``caption`` — Caption/Abstract (dataset 120)

    .. versionadded:: 0.24
    """

    def __init__(self, config: Mapping[str, Any] | None = None) -> None:
        """
        Initializes a new ``IPTCMetadataProcessor``.

        :param config: Mapping with settings.
        """
        super().__init__(config)

    @property
    def formats(self) -> Iterable[str]:
        return {'iptc'}

    def read(self, file: IO) -> Mapping[str, Mapping]:
        """
        Reads IPTC metadata from a JPEG file.

        :param file: Readable binary file-like object containing JPEG data.
        :type file: IO
        :return: Mapping with a single ``'iptc'`` key whose value is a dict of
                 decoded metadata fields.  Returns an empty mapping when the
                 file contains no IPTC data.
        :rtype: Mapping[str, Mapping]
        :raises UnsupportedFormatError: if the data is not a JPEG file.
        """
        data = file.read()
        if not data.startswith(b'\xff\xd8'):
            raise UnsupportedFormatError('IPTC metadata is only supported for JPEG files.')

        try:
            with PIL.Image.open(io.BytesIO(data)) as image:
                raw = PIL.IptcImagePlugin.getiptcinfo(image)
        except Exception as exc:
            raise UnsupportedFormatError(f'Could not read IPTC data: {exc}') from exc

        if not raw:
            return {}

        iptc: dict[str, Any] = {}
        for (record, dataset), value in raw.items():
            if record != 2:
                continue
            if dataset in _REPEATABLE_DATASETS:
                # Convert list or single bytes to a list of strings.
                if isinstance(value, list):
                    iptc['keywords'] = [v.decode('latin-1') for v in value]
                else:
                    iptc['keywords'] = [value.decode('latin-1')]
            elif dataset in _DATASET_TO_KEY:
                key = _DATASET_TO_KEY[dataset]
                iptc[key] = value.decode('latin-1')

        if not iptc:
            return {}
        return {'iptc': iptc}

    def strip(self, file: IO) -> IO:
        """
        Returns a copy of the JPEG file with all IPTC (APP13) data removed.

        :param file: Readable binary file-like object containing JPEG data.
        :type file: IO
        :return: File-like object with IPTC data removed.
        :rtype: IO
        :raises UnsupportedFormatError: if the data is not a JPEG file.
        """
        data = file.read()
        if not data.startswith(b'\xff\xd8'):
            raise UnsupportedFormatError('IPTC strip is only supported for JPEG files.')

        result = io.BytesIO()
        pos = 0
        length = len(data)

        while pos < length:
            if data[pos] != 0xFF:
                # Raw entropy-coded data — copy to end
                result.write(data[pos:])
                break
            marker_byte = data[pos + 1]
            marker = data[pos : pos + 2]

            if marker_byte in (0xD8, 0xD9, 0x01) or 0xD0 <= marker_byte <= 0xD7:
                # Stand-alone marker
                result.write(marker)
                pos += 2
            else:
                seg_length = struct.unpack('>H', data[pos + 2 : pos + 4])[0]
                seg_end = pos + 2 + seg_length
                if marker == b'\xff\xed':
                    # APP13 — skip the entire segment
                    pos = seg_end
                else:
                    result.write(data[pos:seg_end])
                    pos = seg_end

        result.seek(0)
        return result

    def combine(self, file: IO, metadata: Mapping[str, Mapping]) -> IO:
        """
        Returns a copy of the JPEG file with IPTC metadata embedded.

        Existing IPTC data is replaced.  Only the ``'iptc'`` key of
        *metadata* is used; other keys are ignored.

        :param file: Readable binary file-like object containing JPEG data.
        :type file: IO
        :param metadata: Mapping with an ``'iptc'`` key whose value is a dict
                         of IPTC field names and values.
        :type metadata: Mapping
        :return: File-like object with IPTC data embedded.
        :rtype: IO
        :raises UnsupportedFormatError: if *metadata* contains an unknown
                                         IPTC format key.
        """
        for fmt in metadata:
            if fmt not in self.formats:
                raise UnsupportedFormatError(f'Metadata format {fmt!r} is not supported.')

        # Strip any existing IPTC first.
        stripped = self.strip(file)
        stripped.seek(0)
        jpeg_data = stripped.read()

        iptc_fields = metadata.get('iptc', {})
        if not iptc_fields:
            result = io.BytesIO(jpeg_data)
            result.seek(0)
            return result

        # Build IPTC IIM records.
        iptc_bytes = b''
        for key, value in iptc_fields.items():
            dataset = _KEY_TO_DATASET.get(key)
            if dataset is None:
                continue
            if key == 'keywords':
                kw_list = [value] if isinstance(value, str) else list(value)
                for kw in kw_list:
                    iptc_bytes += _make_iptc_record(dataset, kw)
            else:
                iptc_bytes += _make_iptc_record(dataset, str(value))

        app13 = _build_app13(iptc_bytes)

        # Insert APP13 immediately after the SOI marker (first 2 bytes).
        result = io.BytesIO(jpeg_data[:2] + app13 + jpeg_data[2:])
        result.seek(0)
        return result
