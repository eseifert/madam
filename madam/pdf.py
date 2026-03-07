"""
PDF processor using pypdf (metadata) and pdf2image (rasterization).

The optional ``pdf`` dependency group must be installed::

    uv sync --extra pdf
"""

from __future__ import annotations

import io
from collections.abc import Iterable, Mapping
from typing import IO, Any

import PIL.Image

from madam.core import Asset, MetadataProcessor, OperatorError, Processor, UnsupportedFormatError, operator
from madam.mime import MimeType

_MIME_TYPE_TO_PIL_FORMAT: dict[str, str] = {
    'image/jpeg': 'JPEG',
    'image/png': 'PNG',
}

_PDF_DPI: int = 72

PAGE_SIZES: dict[str, tuple[float, float]] = {
    'a4': (595.0, 842.0),
    'letter': (612.0, 792.0),
    'a3': (842.0, 1191.0),
    'legal': (612.0, 1008.0),
}


def _fit_image_on_page(img: PIL.Image.Image, page_px_w: int, page_px_h: int) -> PIL.Image.Image:
    """Flatten alpha/palette → RGB, FIT-scale, centre on white canvas."""
    # Normalise mode
    if img.mode in ('RGBA', 'LA', 'PA'):
        background = PIL.Image.new('RGB', img.size, (255, 255, 255))
        if img.mode == 'PA':
            img = img.convert('RGBA')
        background.paste(img, mask=img.split()[-1])
        img = background
    elif img.mode != 'RGB':
        img = img.convert('RGB')

    # FIT-scale preserving aspect ratio
    img_w, img_h = img.size
    scale = min(page_px_w / img_w, page_px_h / img_h)
    new_w = max(1, int(img_w * scale))
    new_h = max(1, int(img_h * scale))
    img = img.resize((new_w, new_h), PIL.Image.Resampling.LANCZOS)

    # Centre on white canvas
    canvas = PIL.Image.new('RGB', (page_px_w, page_px_h), (255, 255, 255))
    x_off = (page_px_w - new_w) // 2
    y_off = (page_px_h - new_h) // 2
    canvas.paste(img, (x_off, y_off))
    return canvas


def combine(
    assets: Iterable[Asset],
    *,
    page_width: float,
    page_height: float,
) -> Asset:
    """
    Combines a sequence of image assets into a multi-page PDF.

    Each image is scaled to fit the page dimensions (preserving aspect ratio)
    and centred on a white background.  The page dimensions are given in PDF
    points (1 pt = 1/72 inch); at 72 DPI one point equals one pixel.

    :param assets: Iterable of image assets
    :type assets: Iterable[Asset]
    :param page_width: Page width in PDF points (must be positive)
    :type page_width: float
    :param page_height: Page height in PDF points (must be positive)
    :type page_height: float
    :return: Asset with ``mime_type='application/pdf'`` and ``page_count``
    :rtype: Asset
    :raises ValueError: If *assets* is empty or dimensions are non-positive
    :raises OperatorError: If an asset is not an image or cannot be decoded

    .. versionadded:: 1.0
    """
    asset_list = list(assets)
    if not asset_list:
        raise ValueError('Cannot combine an empty sequence of assets')
    if page_width <= 0:
        raise ValueError(f'page_width must be positive, got {page_width!r}')
    if page_height <= 0:
        raise ValueError(f'page_height must be positive, got {page_height!r}')

    page_px_w = int(round(page_width))
    page_px_h = int(round(page_height))

    pages: list[PIL.Image.Image] = []
    for asset in asset_list:
        mime = str(asset.mime_type)
        if not mime.startswith('image/'):
            raise OperatorError(f'Expected an image asset, got mime_type={mime!r}')
        try:
            img = PIL.Image.open(asset.essence)
            img.load()
            asset.essence.seek(0)
        except Exception as exc:
            raise OperatorError(f'Cannot decode image asset: {exc}') from exc
        pages.append(_fit_image_on_page(img, page_px_w, page_px_h))

    buf = io.BytesIO()
    pages[0].save(
        buf,
        format='PDF',
        save_all=True,
        append_images=pages[1:],
        resolution=_PDF_DPI,
    )
    buf.seek(0)
    return Asset._from_bytes(buf.getvalue(), mime_type='application/pdf', page_count=len(pages))


class PDFMetadataProcessor(MetadataProcessor):
    """
    Reads, strips, and writes PDF document information metadata (title, author,
    subject, creator, producer).

    Metadata is stored under the ``'pdf'`` format key, so reading a PDF via
    :class:`PDFProcessor` yields ``asset.pdf`` as a mapping with the available
    fields.

    Requires the ``pypdf`` package (``madam[pdf]`` extra).

    .. versionadded:: 1.0
    """

    supported_mime_types: frozenset = frozenset({MimeType('application/pdf')})

    # PDF /Info key → madam attribute name
    _FIELD_MAP: tuple[tuple[str, str], ...] = (
        ('/Title', 'title'),
        ('/Author', 'author'),
        ('/Subject', 'subject'),
        ('/Creator', 'creator'),
        ('/Producer', 'producer'),
    )

    def __init__(self, config: Mapping[str, Any] | None = None) -> None:
        super().__init__(config)

    @property
    def formats(self) -> frozenset:
        return frozenset({'pdf'})

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _require_pypdf():
        try:
            import pypdf

            return pypdf
        except ImportError as e:
            raise UnsupportedFormatError('pypdf is required; install the pdf extra') from e

    @staticmethod
    def _check_pdf_header(file: IO) -> bytes:
        header = file.read(4)
        file.seek(0)
        if header != b'%PDF':
            raise UnsupportedFormatError('Not a PDF file')
        return file.read()

    def _make_reader(self, data: bytes):
        pypdf = self._require_pypdf()
        try:
            return pypdf.PdfReader(io.BytesIO(data))
        except Exception as exc:
            raise UnsupportedFormatError('Not a valid PDF file') from exc

    # ------------------------------------------------------------------
    # MetadataProcessor interface
    # ------------------------------------------------------------------

    def read(self, file: IO) -> Mapping[str, Mapping]:
        """
        Extract document information from a PDF file.

        :return: ``{'pdf': {'title': ..., 'author': ..., ...}}`` or ``{}`` if
            the document carries no info metadata.
        :raises UnsupportedFormatError: if *file* is not a PDF.
        """
        data = self._check_pdf_header(file)
        file.seek(0)
        reader = self._make_reader(data)

        result: dict[str, str] = {}
        if reader.metadata:
            for pdf_key, madam_key in self._FIELD_MAP:
                val = reader.metadata.get(pdf_key)
                if val:
                    result[madam_key] = str(val)

        return {'pdf': result} if result else {}

    def strip(self, file: IO) -> IO:
        """
        Return a copy of the PDF with document information fields cleared.

        :raises UnsupportedFormatError: if *file* is not a PDF.
        """
        pypdf = self._require_pypdf()
        data = self._check_pdf_header(file)
        file.seek(0)
        reader = self._make_reader(data)

        if not reader.metadata or not any(reader.metadata.values()):
            return io.BytesIO(data)

        writer = pypdf.PdfWriter()
        writer.clone_reader_document_root(reader)
        writer.add_metadata({pdf_key: '' for pdf_key, _ in self._FIELD_MAP})

        out = io.BytesIO()
        writer.write(out)
        out.seek(0)
        return out

    def combine(self, file: IO, metadata: Mapping) -> IO:
        """
        Return a copy of the PDF with the given document information written back.

        :raises UnsupportedFormatError: if *file* is not a PDF or *metadata*
            contains no ``'pdf'`` entry.
        """
        pdf_meta = metadata.get('pdf', {})
        if not pdf_meta:
            raise UnsupportedFormatError('No PDF metadata to write')

        pypdf = self._require_pypdf()
        data = self._check_pdf_header(file)
        file.seek(0)
        reader = self._make_reader(data)

        writer = pypdf.PdfWriter()
        writer.clone_reader_document_root(reader)

        info: dict[str, str] = {}
        for pdf_key, madam_key in self._FIELD_MAP:
            if madam_key in pdf_meta:
                info[pdf_key] = str(pdf_meta[madam_key])
        if info:
            writer.add_metadata(info)

        out = io.BytesIO()
        writer.write(out)
        out.seek(0)
        return out


class PDFProcessor(Processor):
    """
    Represents a processor that handles *Portable Document Format* (PDF) files.

    Reading requires `pypdf <https://pypdf.readthedocs.io/>`_.  Rasterization
    additionally requires `pdf2image <https://github.com/Belval/pdf2image>`_
    and a system-wide installation of *poppler*.

    .. versionadded:: 0.24
    """

    def __init__(self, config: Mapping[str, Any] | None = None) -> None:
        """
        Initializes a new ``PDFProcessor``.

        :param config: Mapping with settings.
        """
        super().__init__(config)

    @property
    def supported_mime_types(self) -> frozenset:
        return frozenset({'application/pdf'})

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

        extra: dict[str, Any] = {}

        if reader.pages:
            box = reader.pages[0].mediabox
            extra['page_width'] = float(box.width)
            extra['page_height'] = float(box.height)

        # Delegate document info metadata to PDFMetadataProcessor
        try:
            meta_by_format = PDFMetadataProcessor().read(io.BytesIO(pdf_bytes))
            extra.update(meta_by_format)
        except UnsupportedFormatError:
            pass

        return Asset._from_bytes(pdf_bytes, mime_type='application/pdf', page_count=page_count, **extra)

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
