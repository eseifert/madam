import io

import pytest

import madam.core


@pytest.fixture(scope='module')
def raw_processor():
    rawpy = pytest.importorskip('rawpy')  # noqa: F841
    from madam.raw import RawImageProcessor

    return RawImageProcessor()


@pytest.fixture(scope='module')
def raw_asset(raw_processor):
    with open('tests/resources/test.dng', 'rb') as f:
        return raw_processor.read(f)


class TestRawImageProcessor:
    def test_can_read_dng(self, raw_processor):
        with open('tests/resources/test.dng', 'rb') as f:
            assert raw_processor.can_read(f)

    def test_cannot_read_non_raw(self, raw_processor):
        buf = io.BytesIO(b'not a raw file')
        assert not raw_processor.can_read(buf)

    def test_read_returns_asset(self, raw_asset):
        assert isinstance(raw_asset, madam.core.Asset)

    def test_read_returns_correct_mime_type(self, raw_asset):
        assert raw_asset.mime_type == 'image/x-raw'

    def test_read_includes_width(self, raw_asset):
        assert raw_asset.width == 32

    def test_read_includes_height(self, raw_asset):
        assert raw_asset.height == 24

    def test_read_preserves_essence(self, raw_asset):
        data = raw_asset.essence.read()
        assert data[:4] in (b'II\x2a\x00', b'MM\x00\x2a')  # TIFF/DNG magic


class TestRawImageProcessorDecode:
    def test_decode_returns_asset(self, raw_processor, raw_asset):
        asset = raw_processor.decode(mime_type='image/png')(raw_asset)
        assert isinstance(asset, madam.core.Asset)

    def test_decode_returns_correct_mime_type(self, raw_processor, raw_asset):
        asset = raw_processor.decode(mime_type='image/png')(raw_asset)
        assert asset.mime_type == 'image/png'

    def test_decode_returns_jpeg(self, raw_processor, raw_asset):
        asset = raw_processor.decode(mime_type='image/jpeg')(raw_asset)
        assert asset.mime_type == 'image/jpeg'

    def test_decode_has_correct_dimensions(self, raw_processor, raw_asset):
        asset = raw_processor.decode(mime_type='image/png')(raw_asset)
        assert asset.width == 32
        assert asset.height == 24

    def test_decode_produces_non_empty_essence(self, raw_processor, raw_asset):
        asset = raw_processor.decode(mime_type='image/png')(raw_asset)
        assert len(asset.essence.read()) > 0

    def test_decode_raises_for_unsupported_mime_type(self, raw_processor, raw_asset):
        with pytest.raises(madam.core.OperatorError):
            raw_processor.decode(mime_type='application/pdf')(raw_asset)
