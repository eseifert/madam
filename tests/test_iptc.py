import io

import PIL.Image
import pytest

from madam.core import UnsupportedFormatError


@pytest.fixture(scope='module')
def iptc_processor():
    from madam.iptc import IPTCMetadataProcessor

    return IPTCMetadataProcessor()


@pytest.fixture(scope='module')
def iptc_asset_bytes():
    with open('tests/resources/image_with_iptc.jpg', 'rb') as f:
        return f.read()


class TestIPTCMetadataProcessor:
    def test_supports_iptc_format(self, iptc_processor):
        assert 'iptc' in iptc_processor.formats

    def test_read_returns_dict_with_iptc_key(self, iptc_processor, iptc_asset_bytes):
        metadata = iptc_processor.read(io.BytesIO(iptc_asset_bytes))

        assert 'iptc' in metadata

    def test_read_returns_headline(self, iptc_processor, iptc_asset_bytes):
        metadata = iptc_processor.read(io.BytesIO(iptc_asset_bytes))

        assert metadata['iptc']['headline'] == 'Test Headline'

    def test_read_returns_caption(self, iptc_processor, iptc_asset_bytes):
        metadata = iptc_processor.read(io.BytesIO(iptc_asset_bytes))

        assert metadata['iptc']['caption'] == 'Test Caption'

    def test_read_returns_copyright(self, iptc_processor, iptc_asset_bytes):
        metadata = iptc_processor.read(io.BytesIO(iptc_asset_bytes))

        assert metadata['iptc']['copyright'] == 'Test Copyright'

    def test_read_returns_keywords_as_list(self, iptc_processor, iptc_asset_bytes):
        metadata = iptc_processor.read(io.BytesIO(iptc_asset_bytes))

        assert metadata['iptc']['keywords'] == ['keyword1', 'keyword2']

    def test_read_returns_city(self, iptc_processor, iptc_asset_bytes):
        metadata = iptc_processor.read(io.BytesIO(iptc_asset_bytes))

        assert metadata['iptc']['city'] == 'Berlin'

    def test_read_returns_country(self, iptc_processor, iptc_asset_bytes):
        metadata = iptc_processor.read(io.BytesIO(iptc_asset_bytes))

        assert metadata['iptc']['country'] == 'Germany'

    def test_read_returns_credit(self, iptc_processor, iptc_asset_bytes):
        metadata = iptc_processor.read(io.BytesIO(iptc_asset_bytes))

        assert metadata['iptc']['credit'] == 'Test Credit'

    def test_read_fails_for_non_jpeg(self, iptc_processor):
        buf = io.BytesIO(b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01')

        with pytest.raises(UnsupportedFormatError):
            iptc_processor.read(buf)

    def test_read_returns_empty_for_jpeg_without_iptc(self, iptc_processor):
        buf = io.BytesIO()
        PIL.Image.new('RGB', (16, 16)).save(buf, format='JPEG')
        buf.seek(0)

        metadata = iptc_processor.read(buf)

        assert metadata == {}

    def test_strip_removes_iptc_from_jpeg(self, iptc_processor, iptc_asset_bytes):
        result = iptc_processor.strip(io.BytesIO(iptc_asset_bytes))
        result_bytes = result.read()

        # The stripped file should be smaller (no APP13 block)
        assert len(result_bytes) < len(iptc_asset_bytes)
        # The stripped file must still be a valid JPEG
        img_buf = io.BytesIO(result_bytes)
        with PIL.Image.open(img_buf) as img:
            assert img.format == 'JPEG'

    def test_strip_produces_jpeg_without_iptc(self, iptc_processor, iptc_asset_bytes):
        result = iptc_processor.strip(io.BytesIO(iptc_asset_bytes))

        # After stripping, reading IPTC should return empty
        result.seek(0)
        metadata = iptc_processor.read(result)

        assert metadata == {}

    def test_combine_adds_headline_to_jpeg(self, iptc_processor, iptc_asset_bytes):
        stripped = iptc_processor.strip(io.BytesIO(iptc_asset_bytes))
        stripped.seek(0)
        result = iptc_processor.combine(stripped, {'iptc': {'headline': 'New Headline'}})
        result.seek(0)

        metadata = iptc_processor.read(result)

        assert metadata['iptc']['headline'] == 'New Headline'

    def test_combine_adds_keywords_to_jpeg(self, iptc_processor, iptc_asset_bytes):
        stripped = iptc_processor.strip(io.BytesIO(iptc_asset_bytes))
        stripped.seek(0)
        result = iptc_processor.combine(stripped, {'iptc': {'keywords': ['foo', 'bar']}})
        result.seek(0)

        metadata = iptc_processor.read(result)

        assert metadata['iptc']['keywords'] == ['foo', 'bar']

    def test_combine_round_trips_all_fields(self, iptc_processor, iptc_asset_bytes):
        expected = {
            'headline': 'My Headline',
            'caption': 'My Caption',
            'copyright': 'My Copyright',
            'city': 'Hamburg',
            'country': 'Germany',
            'credit': 'My Credit',
        }
        stripped = iptc_processor.strip(io.BytesIO(iptc_asset_bytes))
        stripped.seek(0)
        result = iptc_processor.combine(stripped, {'iptc': expected})
        result.seek(0)

        metadata = iptc_processor.read(result)

        for key, value in expected.items():
            assert metadata['iptc'][key] == value
