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


class TestCombine:
    def test_combine_single_image_returns_asset(self, jpeg_image_asset):
        from madam.pdf import combine

        result = combine([jpeg_image_asset], page_width=200, page_height=200)
        assert isinstance(result, madam.core.Asset)

    def test_combine_single_image_mime_type(self, jpeg_image_asset):
        from madam.pdf import combine

        result = combine([jpeg_image_asset], page_width=200, page_height=200)
        assert result.mime_type == 'application/pdf'

    def test_combine_single_image_page_count(self, jpeg_image_asset):
        from madam.pdf import combine

        result = combine([jpeg_image_asset], page_width=200, page_height=200)
        assert result.page_count == 1

    def test_combine_single_image_essence_starts_with_pdf_magic(self, jpeg_image_asset):
        from madam.pdf import combine

        result = combine([jpeg_image_asset], page_width=200, page_height=200)
        assert result.essence.read(4) == b'%PDF'

    def test_combine_two_images_page_count(self, jpeg_image_asset, png_image_asset_rgb):
        from madam.pdf import combine

        result = combine([jpeg_image_asset, png_image_asset_rgb], page_width=200, page_height=200)
        assert result.page_count == 2

    def test_combine_three_images_page_count(self, jpeg_image_asset, png_image_asset_rgb, png_image_asset_rgb_alpha):
        from madam.pdf import combine

        result = combine(
            [jpeg_image_asset, png_image_asset_rgb, png_image_asset_rgb_alpha],
            page_width=200,
            page_height=200,
        )
        assert result.page_count == 3

    def test_combine_page_size_portrait(self, jpeg_image_asset):
        pypdf = pytest.importorskip('pypdf')
        from madam.pdf import combine

        result = combine([jpeg_image_asset], page_width=595, page_height=842)
        reader = pypdf.PdfReader(result.essence)
        box = reader.pages[0].mediabox
        assert float(box.width) == pytest.approx(595, abs=1)
        assert float(box.height) == pytest.approx(842, abs=1)

    def test_combine_page_size_landscape(self, jpeg_image_asset):
        pypdf = pytest.importorskip('pypdf')
        from madam.pdf import combine

        result = combine([jpeg_image_asset], page_width=842, page_height=595)
        reader = pypdf.PdfReader(result.essence)
        box = reader.pages[0].mediabox
        assert float(box.width) == pytest.approx(842, abs=1)
        assert float(box.height) == pytest.approx(595, abs=1)

    def test_combine_rasterized_dimensions_match_page(self, jpeg_image_asset):
        pytest.importorskip('pdf2image')
        from madam.pdf import combine

        result = combine([jpeg_image_asset], page_width=200, page_height=300)
        import pdf2image

        images = pdf2image.convert_from_bytes(result.essence.read(), dpi=72)
        assert images[0].width == 200
        assert images[0].height == 300

    def test_combine_wide_image_letterboxed(self, png_image_asset_rgb):
        pytest.importorskip('pdf2image')
        import pdf2image

        from madam.pdf import combine

        # Use a tall page so the wide image must be letterboxed (whitespace top/bottom)
        result = combine([png_image_asset_rgb], page_width=400, page_height=400)
        images = pdf2image.convert_from_bytes(result.essence.read(), dpi=72)
        img = images[0].convert('RGB')
        top_pixel = img.getpixel((img.width // 2, 0))
        assert top_pixel == (255, 255, 255) or top_pixel[0] > 200

    def test_combine_tall_image_pillarboxed(self):
        pytest.importorskip('pdf2image')
        import io

        import pdf2image

        from madam.pdf import combine

        # Create a tall narrow image
        tall_img = PIL.Image.new('RGB', (50, 400), color=(255, 0, 0))
        buf = io.BytesIO()
        tall_img.save(buf, format='JPEG')
        buf.seek(0)
        tall_asset = madam.core.Asset(essence=buf, mime_type='image/jpeg', width=50, height=400)

        result = combine([tall_asset], page_width=400, page_height=400)
        images = pdf2image.convert_from_bytes(result.essence.read(), dpi=72)
        img = images[0].convert('RGB')
        left_pixel = img.getpixel((0, img.height // 2))
        assert left_pixel == (255, 255, 255) or left_pixel[0] > 200

    def test_combine_rgba_image(self, png_image_asset_rgb_alpha):
        from madam.pdf import combine

        result = combine([png_image_asset_rgb_alpha], page_width=200, page_height=200)
        assert result.mime_type == 'application/pdf'

    def test_combine_palette_image(self, png_image_asset_palette):
        from madam.pdf import combine

        result = combine([png_image_asset_palette], page_width=200, page_height=200)
        assert result.mime_type == 'application/pdf'

    def test_combine_empty_raises_value_error(self):
        from madam.pdf import combine

        with pytest.raises(ValueError):
            combine([], page_width=200, page_height=200)

    def test_combine_zero_page_width_raises_value_error(self, jpeg_image_asset):
        from madam.pdf import combine

        with pytest.raises(ValueError):
            combine([jpeg_image_asset], page_width=0, page_height=200)

    def test_combine_negative_page_height_raises_value_error(self, jpeg_image_asset):
        from madam.pdf import combine

        with pytest.raises(ValueError):
            combine([jpeg_image_asset], page_width=200, page_height=-1)

    def test_combine_non_image_asset_raises_operator_error(self, pdf_asset):
        from madam.pdf import combine

        with pytest.raises(madam.core.OperatorError):
            combine([pdf_asset], page_width=200, page_height=200)

    def test_combine_accepts_generator(self, jpeg_image_asset, png_image_asset_rgb):
        from madam.pdf import combine

        def gen():
            yield jpeg_image_asset
            yield png_image_asset_rgb

        result = combine(gen(), page_width=200, page_height=200)
        assert result.page_count == 2

    def test_combine_mixed_formats(self, jpeg_image_asset, png_image_asset_rgb_alpha):
        from madam.pdf import combine

        result = combine([jpeg_image_asset, png_image_asset_rgb_alpha], page_width=200, page_height=200)
        assert result.page_count == 2


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

    def test_rasterize_raises_for_unsupported_mime_type(self, pdf_processor, pdf_asset):
        pytest.importorskip('pdf2image')
        rasterize = pdf_processor.rasterize(page=0, dpi=72, mime_type='image/bmp')

        with pytest.raises(madam.core.OperatorError):
            rasterize(pdf_asset)


class TestCombinePAMode:
    """Additional coverage for _fit_image_on_page with palette+alpha (PA) mode."""

    def test_combine_palette_alpha_image(self):
        from madam.pdf import _fit_image_on_page

        # Build a PA-mode image directly (palette with alpha channel)
        p_img = PIL.Image.new('P', (16, 16), 0)
        pa_img = p_img.convert('PA')

        # _fit_image_on_page must handle PA mode without error
        result = _fit_image_on_page(pa_img, 100, 100)

        assert result.mode == 'RGB'
        assert result.size == (100, 100)


class TestCombineEdgeCases:
    def test_combine_corrupt_image_bytes_raises_operator_error(self):
        """combine() must raise OperatorError when PIL cannot decode the asset."""
        from madam.pdf import combine

        corrupt = madam.core.Asset(io.BytesIO(b'\xff\xd8corrupt'), mime_type='image/jpeg')

        with pytest.raises(madam.core.OperatorError):
            combine([corrupt], page_width=200.0, page_height=200.0)

    def test_rasterize_no_output_raises_operator_error(self, pdf_processor, pdf_asset, monkeypatch):
        """rasterize() must raise OperatorError when pdf2image returns an empty list."""
        pdf2image = pytest.importorskip('pdf2image')

        monkeypatch.setattr(pdf2image, 'convert_from_bytes', lambda *a, **kw: [])

        rasterize = pdf_processor.rasterize(page=0, dpi=72)

        with pytest.raises(madam.core.OperatorError):
            rasterize(pdf_asset)
