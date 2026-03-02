import io

import PIL.Image
import pytest

from madam.core import UnsupportedFormatError


@pytest.fixture(scope='module')
def xmp_processor():
    from madam.xmp import XMPMetadataProcessor

    return XMPMetadataProcessor()


@pytest.fixture(scope='module')
def xmp_asset_bytes():
    with open('tests/resources/image_with_xmp.jpg', 'rb') as f:
        return f.read()


class TestXMPMetadataProcessor:
    def test_supports_xmp_format(self, xmp_processor):
        assert 'xmp' in xmp_processor.formats

    def test_read_returns_dict_with_xmp_key(self, xmp_processor, xmp_asset_bytes):
        metadata = xmp_processor.read(io.BytesIO(xmp_asset_bytes))

        assert 'xmp' in metadata

    def test_read_returns_title(self, xmp_processor, xmp_asset_bytes):
        metadata = xmp_processor.read(io.BytesIO(xmp_asset_bytes))

        assert metadata['xmp']['title'] == 'Test Title'

    def test_read_returns_description(self, xmp_processor, xmp_asset_bytes):
        metadata = xmp_processor.read(io.BytesIO(xmp_asset_bytes))

        assert metadata['xmp']['description'] == 'Test Description'

    def test_read_returns_subject_as_list(self, xmp_processor, xmp_asset_bytes):
        metadata = xmp_processor.read(io.BytesIO(xmp_asset_bytes))

        assert metadata['xmp']['subject'] == ['xmp_kw1', 'xmp_kw2']

    def test_read_returns_rights(self, xmp_processor, xmp_asset_bytes):
        metadata = xmp_processor.read(io.BytesIO(xmp_asset_bytes))

        assert metadata['xmp']['rights'] == 'CC BY 4.0'

    def test_read_returns_creator(self, xmp_processor, xmp_asset_bytes):
        metadata = xmp_processor.read(io.BytesIO(xmp_asset_bytes))

        assert metadata['xmp']['creator'] == 'Test Author'

    def test_read_returns_create_date(self, xmp_processor, xmp_asset_bytes):
        metadata = xmp_processor.read(io.BytesIO(xmp_asset_bytes))

        assert metadata['xmp']['create_date'] == '2024-01-15T10:30:00'

    def test_read_returns_modify_date(self, xmp_processor, xmp_asset_bytes):
        metadata = xmp_processor.read(io.BytesIO(xmp_asset_bytes))

        assert metadata['xmp']['modify_date'] == '2024-06-01T12:00:00'

    def test_read_fails_for_non_jpeg(self, xmp_processor):
        buf = io.BytesIO(b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01')

        with pytest.raises(UnsupportedFormatError):
            xmp_processor.read(buf)

    def test_read_returns_empty_for_jpeg_without_xmp(self, xmp_processor):
        buf = io.BytesIO()
        PIL.Image.new('RGB', (16, 16)).save(buf, format='JPEG')
        buf.seek(0)

        metadata = xmp_processor.read(buf)

        assert metadata == {}

    def test_strip_removes_xmp_from_jpeg(self, xmp_processor, xmp_asset_bytes):
        result = xmp_processor.strip(io.BytesIO(xmp_asset_bytes))
        result_bytes = result.read()

        # The stripped file should be smaller (no XMP APP1 block)
        assert len(result_bytes) < len(xmp_asset_bytes)
        # Must still be a valid JPEG
        with PIL.Image.open(io.BytesIO(result_bytes)) as img:
            assert img.format == 'JPEG'

    def test_strip_produces_jpeg_without_xmp(self, xmp_processor, xmp_asset_bytes):
        result = xmp_processor.strip(io.BytesIO(xmp_asset_bytes))

        result.seek(0)
        metadata = xmp_processor.read(result)

        assert metadata == {}

    def test_combine_adds_title_to_jpeg(self, xmp_processor, xmp_asset_bytes):
        stripped = xmp_processor.strip(io.BytesIO(xmp_asset_bytes))
        stripped.seek(0)
        result = xmp_processor.combine(stripped, {'xmp': {'title': 'New Title'}})
        result.seek(0)

        metadata = xmp_processor.read(result)

        assert metadata['xmp']['title'] == 'New Title'

    def test_combine_adds_subject_list_to_jpeg(self, xmp_processor, xmp_asset_bytes):
        stripped = xmp_processor.strip(io.BytesIO(xmp_asset_bytes))
        stripped.seek(0)
        result = xmp_processor.combine(stripped, {'xmp': {'subject': ['alpha', 'beta']}})
        result.seek(0)

        metadata = xmp_processor.read(result)

        assert metadata['xmp']['subject'] == ['alpha', 'beta']

    def test_combine_round_trips_all_fields(self, xmp_processor, xmp_asset_bytes):
        expected = {
            'title': 'Round-trip Title',
            'description': 'Round-trip Description',
            'rights': 'All rights reserved',
            'creator': 'Jane Doe',
            'create_date': '2025-03-01T09:00:00',
        }
        stripped = xmp_processor.strip(io.BytesIO(xmp_asset_bytes))
        stripped.seek(0)
        result = xmp_processor.combine(stripped, {'xmp': expected})
        result.seek(0)

        metadata = xmp_processor.read(result)

        for key, value in expected.items():
            assert metadata['xmp'][key] == value
