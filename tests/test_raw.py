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


class TestRawImageProcessorRegistration:
    def test_madam_registers_raw_processor(self):
        pytest.importorskip('rawpy')
        from madam.raw import RawImageProcessor

        manager = madam.core.Madam()
        processor = manager.get_processor('image/x-raw')
        assert isinstance(processor, RawImageProcessor)

    def test_raw_processor_supported_mime_types(self):
        pytest.importorskip('rawpy')
        from madam.raw import RawImageProcessor

        processor = RawImageProcessor()
        assert 'image/x-raw' in processor.supported_mime_types


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

    def test_read_exif_metadata_stored_under_exif_key(self, raw_asset):
        assert hasattr(raw_asset, 'exif')

    def test_read_camera_model(self, raw_asset):
        # test.dng embeds 'Canon EOS 5D Mark III'
        assert raw_asset.exif['camera.model'] == 'Canon EOS 5D Mark III'

    def test_read_iso_speed_is_float_when_present(self, raw_asset):
        if 'iso_speed' in raw_asset.exif:
            assert isinstance(raw_asset.exif['iso_speed'], float)
            assert raw_asset.exif['iso_speed'] > 0

    def test_read_exposure_time_is_float_when_present(self, raw_asset):
        if 'exposure_time' in raw_asset.exif:
            assert isinstance(raw_asset.exif['exposure_time'], float)
            assert raw_asset.exif['exposure_time'] > 0

    def test_read_fnumber_is_float_when_present(self, raw_asset):
        if 'fnumber' in raw_asset.exif:
            assert isinstance(raw_asset.exif['fnumber'], float)
            assert raw_asset.exif['fnumber'] > 0

    def test_read_focal_length_is_float_when_present(self, raw_asset):
        if 'focal_length' in raw_asset.exif:
            assert isinstance(raw_asset.exif['focal_length'], float)
            assert raw_asset.exif['focal_length'] > 0

    def test_read_created_at_is_str_when_present(self, raw_asset):
        if 'created_at' in raw_asset.exif:
            assert isinstance(raw_asset.exif['created_at'], str)


class TestRawMetadataProcessor:
    @pytest.fixture
    def processor(self):
        pytest.importorskip('rawpy')
        from madam.raw import RawMetadataProcessor

        return RawMetadataProcessor()

    def test_formats_contains_exif(self, processor):
        assert 'exif' in processor.formats

    def test_read_returns_exif_format_key(self, processor):
        with open('tests/resources/test.dng', 'rb') as f:
            result = processor.read(f)
        assert 'exif' in result

    def test_read_extracts_camera_model(self, processor):
        with open('tests/resources/test.dng', 'rb') as f:
            result = processor.read(f)
        assert result['exif']['camera.model'] == 'Canon EOS 5D Mark III'

    def test_read_raises_for_non_raw(self, processor):
        from madam.core import UnsupportedFormatError

        with pytest.raises(UnsupportedFormatError):
            processor.read(io.BytesIO(b'not a raw file'))

    def test_strip_returns_io(self, processor):
        with open('tests/resources/test.dng', 'rb') as f:
            result = processor.strip(f)
        assert hasattr(result, 'read')

    def test_combine_raises_unsupported(self, processor):
        from madam.core import UnsupportedFormatError

        with open('tests/resources/test.dng', 'rb') as f:
            with pytest.raises(UnsupportedFormatError):
                processor.combine(f, {'exif': {'camera.model': 'Test'}})


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
