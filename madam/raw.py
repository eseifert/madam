"""
Raw camera image processor using rawpy (LibRaw).

The optional ``raw`` dependency group must be installed::

    uv sync --extra raw
"""

from __future__ import annotations

import io
from collections.abc import Mapping
from typing import IO, Any

from madam.core import Asset, OperatorError, Processor, operator

_MIME_TYPE_TO_PIL_FORMAT: dict[str, str] = {
    'image/jpeg': 'JPEG',
    'image/png': 'PNG',
    'image/tiff': 'TIFF',
}


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
        except rawpy.LibRawError:
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
        return Asset._from_bytes(raw_bytes, mime_type='image/x-raw', width=width, height=height)

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
