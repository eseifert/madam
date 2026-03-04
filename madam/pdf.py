"""
PDF processor using pypdf (metadata) and pdf2image (rasterization).

The optional ``pdf`` dependency group must be installed::

    uv sync --extra pdf
"""

from __future__ import annotations

import io
from collections.abc import Mapping
from typing import IO, Any

from madam.core import Asset, OperatorError, Processor, operator

_MIME_TYPE_TO_PIL_FORMAT: dict[str, str] = {
    'image/jpeg': 'JPEG',
    'image/png': 'PNG',
}


class PDFProcessor(Processor):
    """
    Represents a processor that handles *Portable Document Format* (PDF) files.

    Reading requires `pypdf <https://pypdf.readthedocs.io/>`_.  Rasterization
    additionally requires `pdf2image <https://github.com/Belval/pdf2image>`_
    and a system-wide installation of *poppler*.
    """

    def __init__(self, config: Mapping[str, Any] | None = None) -> None:
        """
        Initializes a new ``PDFProcessor``.

        :param config: Mapping with settings.
        """
        super().__init__(config)

    def can_read(self, file: IO) -> bool:
        header = file.read(4)
        file.seek(0)
        return header == b'%PDF'

    def read(self, file: IO) -> Asset:
        """
        Reads a PDF file and returns an :class:`~madam.core.Asset`.

        The returned asset carries a ``page_count`` metadata attribute with the
        number of pages in the document.

        :param file: Readable binary file-like object containing PDF data
        :type file: IO
        :return: Asset with ``mime_type='application/pdf'`` and ``page_count``
        :rtype: Asset
        """
        try:
            import pypdf
        except ImportError as e:
            raise OperatorError('pypdf is required for reading PDFs; install the pdf extra') from e
        pdf_bytes = file.read()
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        page_count = len(reader.pages)
        return Asset._from_bytes(pdf_bytes, mime_type='application/pdf', page_count=page_count)

    @operator
    def rasterize(self, asset: Asset, page: int = 0, dpi: int = 72, mime_type: str = 'image/jpeg') -> Asset:
        """
        Converts one page of a PDF asset into a raster image.

        Requires the ``pdf2image`` package and a system *poppler* installation.

        :param asset: PDF asset to rasterize
        :type asset: Asset
        :param page: Zero-based page index
        :type page: int
        :param dpi: Output resolution in dots per inch
        :type dpi: int
        :param mime_type: MIME type of the output image (``'image/jpeg'`` or ``'image/png'``)
        :type mime_type: str
        :return: Raster image asset
        :rtype: Asset
        :raises OperatorError: if *page* is out of range or rasterization fails
        """
        try:
            import pdf2image
        except ImportError as e:
            raise OperatorError('pdf2image is required for rasterization; install the pdf extra') from e

        page_count = asset.page_count
        if page < 0 or page >= page_count:
            raise OperatorError(f'Page index {page} is out of range for a PDF with {page_count} pages')

        pil_format = _MIME_TYPE_TO_PIL_FORMAT.get(mime_type)
        if pil_format is None:
            raise OperatorError(f'Unsupported MIME type for rasterization: {mime_type!r}')

        # pdf2image uses 1-based page numbers
        images = pdf2image.convert_from_bytes(
            asset.essence.read(),
            dpi=dpi,
            first_page=page + 1,
            last_page=page + 1,
        )
        if not images:
            raise OperatorError(f'Rasterization produced no output for page {page}')

        pil_image = images[0]
        width, height = pil_image.size

        buf = io.BytesIO()
        pil_image.save(buf, format=pil_format)
        buf.seek(0)

        return Asset(essence=buf, mime_type=mime_type, width=width, height=height)
