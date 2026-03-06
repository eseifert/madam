import io

import PIL.Image
import pytest

import madam.core


@pytest.fixture(scope='module')
def pdf_processor():
    pypdf = pytest.importorskip('pypdf')  # noqa: F841
    from madam.pdf import PDFProcessor

    return PDFProcessor()


@pytest.fixture(scope='module')
def pdf_asset(pdf_processor):
    with open('tests/resources/test.pdf', 'rb') as f:
        return pdf_processor.read(f)


class TestPDFProcessorRegistration:
    def test_madam_registers_pdf_processor(self):
        pytest.importorskip('pypdf')
        from madam.pdf import PDFProcessor

        manager = madam.core.Madam()
        processor = manager.get_processor('application/pdf')
        assert isinstance(processor, PDFProcessor)

    def test_pdf_processor_supported_mime_types(self):
        pytest.importorskip('pypdf')
        from madam.pdf import PDFProcessor

        processor = PDFProcessor()
        assert 'application/pdf' in processor.supported_mime_types


class TestPDFProcessor:
    def test_can_read_pdf(self, pdf_processor):
        with open('tests/resources/test.pdf', 'rb') as f:
            assert pdf_processor.can_read(f)

    def test_cannot_read_non_pdf(self, pdf_processor):
        buf = io.BytesIO(b'not a pdf')
        assert not pdf_processor.can_read(buf)

    def test_read_returns_pdf_asset(self, pdf_asset):
        assert isinstance(pdf_asset, madam.core.Asset)

    def test_read_returns_correct_mime_type(self, pdf_asset):
        assert pdf_asset.mime_type == 'application/pdf'

    def test_read_includes_page_count(self, pdf_asset):
        assert pdf_asset.page_count == 2

    def test_read_preserves_essence(self, pdf_asset):
        data = pdf_asset.essence.read()
        pdf_asset.essence.seek(0)
        assert data[:4] == b'%PDF'


class TestPDFRasterize:
    def test_rasterize_returns_image_asset(self, pdf_processor, pdf_asset):
        pytest.importorskip('pdf2image')
        rasterize = pdf_processor.rasterize(page=0, dpi=72)

        image_asset = rasterize(pdf_asset)

        assert image_asset.mime_type == 'image/jpeg'

    def test_rasterize_returns_non_empty_image(self, pdf_processor, pdf_asset):
        pytest.importorskip('pdf2image')
        rasterize = pdf_processor.rasterize(page=0, dpi=72)

        image_asset = rasterize(pdf_asset)

        assert image_asset.width > 0
        assert image_asset.height > 0

    def test_rasterize_accepts_custom_mime_type(self, pdf_processor, pdf_asset):
        pytest.importorskip('pdf2image')
        rasterize = pdf_processor.rasterize(page=0, dpi=72, mime_type='image/png')

        image_asset = rasterize(pdf_asset)

        assert image_asset.mime_type == 'image/png'

    def test_rasterize_second_page(self, pdf_processor, pdf_asset):
        pytest.importorskip('pdf2image')
        rasterize = pdf_processor.rasterize(page=1, dpi=72)

        image_asset = rasterize(pdf_asset)

        assert image_asset.width > 0
        assert image_asset.height > 0

    def test_rasterize_raises_for_out_of_range_page(self, pdf_processor, pdf_asset):
        pytest.importorskip('pdf2image')
        rasterize = pdf_processor.rasterize(page=99, dpi=72)

        with pytest.raises(madam.core.OperatorError):
            rasterize(pdf_asset)
