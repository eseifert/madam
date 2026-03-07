"""
Raw camera image processor using rawpy (LibRaw).

The optional ``raw`` dependency group must be installed::

    uv sync --extra raw
"""

from __future__ import annotations

import datetime
import io
from collections.abc import Mapping
from fractions import Fraction
from typing import IO, Any

import piexif

from madam.core import Asset, MetadataProcessor, OperatorError, Processor, UnsupportedFormatError, operator
from madam.mime import MimeType

_MIME_TYPE_TO_PIL_FORMAT: dict[str, str] = {
    'image/jpeg': 'JPEG',
    'image/png': 'PNG',
    'image/tiff': 'TIFF',
}


_TIFF_MAGIC = (b'II\x2a\x00', b'MM\x00\x2a')


def _rational_to_float(value: Any) -> float:
    """Convert a piexif rational (numerator, denominator) tuple to float."""
    num, den = value
    return float(Fraction(num, den)) if den else 0.0


class RawMetadataProcessor(MetadataProcessor):
    """
    Reads EXIF metadata from raw camera image files (DNG, CR2, NEF, etc.)
    using piexif.

    Raw files embed EXIF data in their TIFF structure.  This processor
    extracts camera make/model, shooting parameters (ISO, exposure, f-number,
    focal length), and capture timestamp, storing them under the ``'exif'``
    format key — the same schema used by
    :class:`~madam.exif.ExifMetadataProcessor` for JPEG/WebP.

    Because piexif does not support inserting EXIF into TIFF/DNG files,
    :meth:`combine` raises :class:`~madam.core.UnsupportedFormatError`.
    :meth:`strip` returns the file unchanged (EXIF is integral to the raw
    TIFF structure).

    .. versionadded:: 1.0
    """

    supported_mime_types: frozenset = frozenset({MimeType('image/x-raw')})

    def __init__(self, config: Mapping[str, Any] | None = None) -> None:
        super().__init__(config)

    @property
    def formats(self) -> frozenset:
        return frozenset({'exif'})

    # ------------------------------------------------------------------
    # Internal helper
    # ------------------------------------------------------------------

    @staticmethod
    def _extract(raw_bytes: bytes) -> dict[str, Any]:
        """Return EXIF camera parameters extracted from *raw_bytes* via piexif."""
        try:
            meta = piexif.load(raw_bytes)
        except Exception:
            return {}

        result: dict[str, Any] = {}

        ifd0 = meta.get('0th', {})
        make = ifd0.get(piexif.ImageIFD.Make)
        if make:
            result['camera.manufacturer'] = make.rstrip(b'\x00').decode('utf-8', errors='replace')
        model = ifd0.get(piexif.ImageIFD.Model)
        if model:
            result['camera.model'] = model.rstrip(b'\x00').decode('utf-8', errors='replace')

        exif_ifd = meta.get('Exif', {})

        iso = exif_ifd.get(piexif.ExifIFD.ISOSpeedRatings)
        if iso:
            result['iso_speed'] = float(iso)

        for tag, key in (
            (piexif.ExifIFD.ExposureTime, 'exposure_time'),
            (piexif.ExifIFD.FNumber, 'fnumber'),
            (piexif.ExifIFD.FocalLength, 'focal_length'),
        ):
            raw_val = exif_ifd.get(tag)
            if raw_val:
                val = _rational_to_float(raw_val)
                if val > 0:
                    result[key] = val

        dt_orig = exif_ifd.get(piexif.ExifIFD.DateTimeOriginal)
        if dt_orig:
            try:
                dt = datetime.datetime.strptime(dt_orig.decode('utf-8'), '%Y:%m:%d %H:%M:%S')
                result['created_at'] = dt.isoformat()
            except (ValueError, UnicodeDecodeError):
                pass

        return result

    # ------------------------------------------------------------------
    # MetadataProcessor interface
    # ------------------------------------------------------------------

    def read(self, file: IO) -> Mapping[str, Mapping]:
        """
        Extract EXIF metadata from a raw camera image file.

        :return: ``{'exif': {key: value, ...}}`` or ``{}`` if no EXIF data is
            found.
        :raises UnsupportedFormatError: if *file* is not a TIFF-based raw image.
        """
        header = file.read(4)
        file.seek(0)
        if header not in _TIFF_MAGIC:
            raise UnsupportedFormatError('Not a TIFF-based raw image')

        data = file.read()
        file.seek(0)
        exif_data = self._extract(data)
        return {'exif': exif_data} if exif_data else {}

    def strip(self, file: IO) -> IO:
        """
        Return the file unchanged.

        EXIF data is integral to the raw TIFF structure; removing it would
        corrupt the file for most raw processors.
        """
        data = file.read()
        file.seek(0)
        return io.BytesIO(data)

    def combine(self, file: IO, metadata: Mapping) -> IO:
        """
        Not supported — piexif cannot insert EXIF into TIFF/DNG files.

        :raises UnsupportedFormatError: always.
        """
        raise UnsupportedFormatError('Writing EXIF to raw camera files is not supported')


class RawImageProcessor(Processor):
    """
    Represents a processor that handles raw camera image formats (DNG, CR2,
    NEF, ARW, and any other format supported by LibRaw).

    Reading and decoding require the `rawpy <https://letmaik.github.io/rawpy/>`_
    package, which is a Python binding for LibRaw.  Pillow is used to encode the
    decoded image into the requested output format.

    Install the optional ``raw`` extra to get both dependencies::

        pip install madam[raw]

    .. versionadded:: 0.24
    """

    def __init__(self, config: Mapping[str, Any] | None = None) -> None:
        """
        Initializes a new ``RawImageProcessor``.

        :param config: Mapping with settings.
        """
        super().__init__(config)

    @property
    def supported_mime_types(self) -> frozenset:
        return frozenset({'image/x-raw'})

    def can_read(self, file: IO) -> bool:
        try:
            import rawpy
        except ImportError:
            return False
        data = file.read()
        file.seek(0)
        try:
            with rawpy.imread(io.BytesIO(data)):
                return True
        except rawpy.LibRawError:  # type: ignore[attr-defined]
            return False

    def read(self, file: IO) -> Asset:
        """
        Reads a raw camera image file and returns an :class:`~madam.core.Asset`.

        The essence contains the original raw bytes unchanged.  The ``width``
        and ``height`` metadata attributes reflect the full sensor dimensions
        before demosaicing.

        :param file: Readable binary file-like object containing raw image data
        :type file: IO
        :return: Asset with ``mime_type='image/x-raw'``, ``width``, and ``height``
        :rtype: Asset
        """
        try:
            import rawpy
        except ImportError as e:
            raise OperatorError('rawpy is required for reading raw images; install the raw extra') from e
        raw_bytes = file.read()
        with rawpy.imread(io.BytesIO(raw_bytes)) as raw:
            width = raw.sizes.width
            height = raw.sizes.height

        extra: dict[str, Any] = {}
        try:
            meta_by_format = RawMetadataProcessor().read(io.BytesIO(raw_bytes))
            extra.update(meta_by_format)
        except UnsupportedFormatError:
            pass

        return Asset._from_bytes(raw_bytes, mime_type='image/x-raw', width=width, height=height, **extra)

    @operator
    def decode(self, asset: Asset, mime_type: str = 'image/png') -> Asset:
        """
        Demosaics a raw camera image and returns the result as a standard
        raster image asset.

        Demosaicing is performed with LibRaw using automatic white balance.
        The result is encoded into the format specified by *mime_type*.

        :param asset: Raw image asset to demosaic
        :type asset: Asset
        :param mime_type: MIME type of the output image (``'image/png'``,
            ``'image/jpeg'``, or ``'image/tiff'``)
        :type mime_type: str
        :return: Decoded raster image asset
        :rtype: Asset
        :raises OperatorError: if *mime_type* is not supported
        """
        try:
            import rawpy
        except ImportError as e:
            raise OperatorError('rawpy is required for decoding raw images; install the raw extra') from e
        import PIL.Image

        pil_format = _MIME_TYPE_TO_PIL_FORMAT.get(mime_type)
        if pil_format is None:
            raise OperatorError(f'Unsupported MIME type for raw decode: {mime_type!r}')

        with rawpy.imread(io.BytesIO(asset.essence.read())) as raw:
            rgb_array = raw.postprocess(use_camera_wb=True, no_auto_bright=False)

        pil_image = PIL.Image.fromarray(rgb_array)
        width, height = pil_image.size

        buf = io.BytesIO()
        pil_image.save(buf, format=pil_format)
        buf.seek(0)

        return Asset(essence=buf, mime_type=mime_type, width=width, height=height)
