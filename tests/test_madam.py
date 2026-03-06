import io
import sys
from unittest.mock import patch

import piexif
import pytest
from assets import (
    DEFAULT_HEIGHT,
    DEFAULT_WIDTH,
    get_jpeg_image_asset,
)

from madam import Madam
from madam.core import Asset, Processor, UnsupportedFormatError


class TestAsset:
    def test_asset_string_representation_contains_class_name(self):
        asset = Asset(essence=io.BytesIO(), mime_type='application/x-empty')

        asset_repr = repr(asset)

        assert asset.__class__.__qualname__ in asset_repr

    def test_asset_string_representation_contains_metadata(self):
        asset = Asset(essence=io.BytesIO(), mime_type='application/x-empty', magic=42)

        asset_repr = repr(asset)

        for key, val in asset.metadata.items():
            assert f'{key}={val!r}' in asset_repr

    def test_asset_string_representation_does_not_contain_complex_metadata(self):
        asset = Asset(essence=io.BytesIO(), mime_type='application/x-empty', complex=dict(k1='v1', k2=42))

        asset_repr = repr(asset)

        assert '{}={!r}'.format('mime_type', asset.mime_type) in asset_repr
        assert '{}={!r}'.format('complex', asset.complex) not in asset_repr


class TestMadam:
    @pytest.fixture(name='manager', scope='class')
    def madam_instance(self):
        return Madam()

    @pytest.fixture(scope='class')
    def read_asset(self, manager, asset):
        return manager.read(asset.essence)

    def test_stores_configuration(self):
        config = dict(foo='bar')
        manager = Madam(config)

        assert manager.config['foo'] == 'bar'

    def test_get_processor_returns_processor_for_readable_asset(self, manager, asset):
        processor = manager.get_processor(asset)

        assert processor is not None

    def test_get_processor_raises_for_unreadable_file(self, manager, unknown_asset):
        with pytest.raises(UnsupportedFormatError):
            manager.get_processor(unknown_asset.essence)

    def test_get_processor_accepts_asset(self, manager, asset):
        processor = manager.get_processor(asset)

        assert isinstance(processor, Processor)

    def test_get_processor_accepts_mime_type_string(self, manager):
        processor = manager.get_processor('image/jpeg')

        assert isinstance(processor, Processor)

    def test_get_processor_asset_matches_essence(self, manager, asset):
        assert manager.get_processor(asset) is manager.get_processor(asset.essence)

    def test_get_processor_raises_for_unknown_asset(self, manager, unknown_asset):
        with pytest.raises(UnsupportedFormatError):
            manager.get_processor(unknown_asset)

    def test_get_processor_raises_for_unknown_mime_type(self, manager):
        with pytest.raises(UnsupportedFormatError):
            manager.get_processor('application/octet-stream')

    def test_get_processor_does_not_change_file_seek_position(self, manager, asset):
        with asset.essence as essence:
            manager.get_processor(essence)
            assert essence.tell() == 0

    def test_read_returns_jpeg_asset_with_correct_metadata(self, manager, jpeg_data_with_exif):
        jpeg_with_metadata = jpeg_data_with_exif

        asset = manager.read(jpeg_with_metadata)

        assert 'exif' in asset.metadata

    def test_read_returns_jpeg_asset_whose_essence_does_not_contain_metadata(self, manager, jpeg_image_asset, tmpdir):
        jpeg_with_metadata = jpeg_image_asset

        asset = manager.read(jpeg_with_metadata.essence)

        essence_file = tmpdir.join('essence_without_metadata.jpg')
        essence_file.write(asset.essence.read(), 'wb')
        metadata = piexif.load(str(essence_file))
        assert not any(metadata.values())

    def test_read_empty_file_raises_error(self, manager):
        file_data = io.BytesIO()

        with pytest.raises(UnsupportedFormatError):
            manager.read(file_data)

    def test_read_raises_when_file_is_none(self, manager):
        invalid_file = None

        with pytest.raises(TypeError):
            manager.read(invalid_file)  # noqa

    def test_read_raises_error_when_format_is_unknown(self, manager, unknown_asset):
        with pytest.raises(UnsupportedFormatError):
            manager.read(unknown_asset.essence)

    def test_read_returns_asset_when_reading_valid_data(self, read_asset):
        assert read_asset is not None

    def test_read_returns_asset_with_correct_mime_type(self, manager, asset):
        read_asset = manager.read(asset.essence)

        assert read_asset.mime_type == asset.mime_type

    def test_read_stores_additional_metadata(self, manager, asset):
        filename = 'foobar'

        read_asset = manager.read(asset.essence, additional_metadata=dict(filename=filename))

        assert 'filename' in read_asset.metadata
        assert read_asset.filename == filename

    def test_read_returns_asset_whose_essence_is_filled(self, read_asset):
        assert read_asset.essence.read()

    def test_read_returns_image_asset_with_correct_color_mode(self, manager, image_asset):
        asset = image_asset

        read_asset = manager.read(asset.essence)

        assert read_asset.color_space == asset.color_space
        assert read_asset.depth == asset.depth
        assert read_asset.data_type == asset.data_type

    def test_read_jpeg_does_not_alter_the_original_file(self, manager):
        jpeg_data = get_jpeg_image_asset().essence
        original_image_data = jpeg_data.read()
        jpeg_data.seek(0)

        manager.read(jpeg_data)

        jpeg_data.seek(0)
        image_data_after_reading = jpeg_data.read()
        assert original_image_data == image_data_after_reading

    def test_read_video_returns_asset_with_duration_metadata(self, manager, video_asset):
        asset = manager.read(video_asset.essence)

        assert asset.duration == pytest.approx(video_asset.duration, rel=0.4)

    def test_read_video_returns_asset_containing_video_size_metadata(self, manager, video_asset):
        asset = manager.read(video_asset.essence)

        assert asset.width == DEFAULT_WIDTH
        assert asset.height == DEFAULT_HEIGHT

    def test_read_returns_video_asset_containing_video_stream_metadata(self, manager, video_asset):
        asset = video_asset

        read_asset = manager.read(asset.essence)

        assert 'video' in read_asset.metadata

    def test_read_returns_video_asset_containing_color_mode_metadata(self, manager, video_asset):
        asset = video_asset

        read_asset = manager.read(asset.essence)

        assert read_asset.video['color_space'] == asset.video['color_space']
        assert read_asset.video['depth'] == asset.video['depth']
        assert read_asset.video['data_type'] == asset.video['data_type']

    def test_read_returns_asset_containing_image_size_metadata(self, manager, image_asset):
        image_data = image_asset.essence

        asset = manager.read(image_data)

        assert asset.width == DEFAULT_WIDTH
        assert asset.height == DEFAULT_HEIGHT

    def test_read_returns_image_asset_containing_color_depth_metadata(self, manager, image_asset):
        image_data = image_asset.essence

        asset = manager.read(image_data)

        assert isinstance(asset.metadata['depth'], int)
        assert asset.metadata['depth'] > 0
        assert asset.metadata['depth'] == image_asset.metadata['depth']

    def test_read_only_returns_python_types_in_metadata(self, manager, jpeg_image_asset, tmpdir):
        import datetime
        import fractions

        import frozendict

        allowed_types = {str, float, int, tuple, frozendict.frozendict, datetime.datetime, fractions.Fraction}
        file = tmpdir.join('asset_with_metadata.jpg')
        file.write(jpeg_image_asset.essence.read(), 'wb')
        metadata = piexif.load(str(file))
        metadata['0th'][piexif.ImageIFD.Artist] = 'Test artist'
        piexif.insert(piexif.dump(metadata), str(file))

        asset = manager.read(file.open('rb'))

        for metadata_type in {'exif'}:
            values = asset.metadata[metadata_type].values()
            assert values
            for value in values:
                assert type(value) in allowed_types

    def test_writes_correct_essence_without_metadata(self, manager, asset):
        asset = Asset(essence=asset.essence)
        file = io.BytesIO()

        manager.write(asset, file)

        file.seek(0)
        assert file.read() == asset.essence.read()

    def test_writes_correct_essence_with_metadata(self, manager, jpeg_image_asset):
        file = io.BytesIO()

        manager.write(jpeg_image_asset, file)

        file.seek(0)
        assert file.read() != jpeg_image_asset.essence.read()

    def test_contains_set_of_all_processors_by_default(self, manager):
        assert {
            'madam.image.PillowProcessor',
            'madam.vector.SVGProcessor',
            'madam.ffmpeg.FFmpegProcessor',
        }.issubset(manager.processors)

    def test_contains_set_of_all_metadata_processors_by_default(self, manager):
        assert manager.metadata_processors == {
            'madam.exif.ExifMetadataProcessor',
            'madam.iptc.IPTCMetadataProcessor',
            'madam.xmp.XMPMetadataProcessor',
            'madam.vector.SVGMetadataProcessor',
            'madam.ffmpeg.FFmpegMetadataProcessor',
        }

    def test_read_calls_strip_exactly_once_per_metadata_processor(self, manager, jpeg_image_asset):
        """Madam.read() must not amplify I/O: strip() called exactly N times for N processors."""
        strip_call_count = []
        original_strip_methods = {}
        for mp in manager._metadata_processors:
            original = mp.strip
            original_strip_methods[mp] = original

            def counting_strip(file, _mp=mp, _orig=original):
                strip_call_count.append(type(_mp).__name__)
                return _orig(file)

            mp.strip = counting_strip

        try:
            manager.read(jpeg_image_asset.essence)
        finally:
            for mp, orig in original_strip_methods.items():
                mp.strip = orig

        n_processors = len(manager._metadata_processors)
        assert len(strip_call_count) == n_processors, (
            f'Expected strip() called {n_processors} times (once per metadata processor), '
            f'got {len(strip_call_count)}: {strip_call_count}'
        )

    def test_does_not_contain_metadata_processor_when_it_is_not_installed(self):
        with patch.dict(sys.modules, {'madam.exif': None}):
            manager = Madam()

        assert 'madam.exif.ExifMetadataProcessor' not in manager.metadata_processors

    def test_read_sets_created_at_from_exif_datetime_original(self):
        """Madam.read() must extract a top-level created_at from EXIF DateTimeOriginal."""
        manager = Madam()
        with open('tests/resources/image_with_exif.jpg', 'rb') as f:
            asset = manager.read(f)

        # image_with_exif.jpg has DateTimeOriginal = 2014:05:24 19:35:30
        assert hasattr(asset, 'created_at')
        assert asset.created_at == '2014-05-24T19:35:30'

    def test_read_sets_created_at_from_xmp_create_date(self):
        """Madam.read() must fall back to XMP CreateDate when no EXIF datetime is present."""
        manager = Madam()
        with open('tests/resources/image_with_xmp.jpg', 'rb') as f:
            asset = manager.read(f)

        # image_with_xmp.jpg has xmp:CreateDate = 2024-01-15T10:30:00
        assert hasattr(asset, 'created_at')
        assert asset.created_at == '2024-01-15T10:30:00'

    def test_read_does_not_set_created_at_when_no_timestamp_available(self, png_image_asset):
        """Madam.read() must not add created_at when no creation timestamp can be found."""
        manager = Madam()

        asset = manager.read(png_image_asset.essence)

        assert not hasattr(asset, 'created_at')

    def test_strip_returns_asset(self, manager, jpeg_data_with_exif):
        asset = manager.read(jpeg_data_with_exif)

        stripped = manager.strip(asset)

        assert isinstance(stripped, Asset)

    def test_strip_removes_metadata_format_keys(self, manager, jpeg_data_with_exif):
        asset = manager.read(jpeg_data_with_exif)
        assert 'exif' in asset.metadata

        stripped = manager.strip(asset)

        assert 'exif' not in stripped.metadata

    def test_strip_removes_created_at(self):
        manager = Madam()
        with open('tests/resources/image_with_exif.jpg', 'rb') as f:
            asset = manager.read(f)
        assert hasattr(asset, 'created_at')

        stripped = manager.strip(asset)

        assert not hasattr(stripped, 'created_at')

    def test_strip_preserves_structural_metadata(self, manager, jpeg_image_asset):
        asset = manager.read(jpeg_image_asset.essence)

        stripped = manager.strip(asset)

        assert stripped.mime_type == asset.mime_type
        assert stripped.width == asset.width
        assert stripped.height == asset.height

    def test_strip_removes_embedded_metadata_from_essence(self, manager, jpeg_data_with_exif, tmpdir):
        asset = manager.read(jpeg_data_with_exif)

        stripped = manager.strip(asset)

        essence_file = tmpdir.join('stripped.jpg')
        essence_file.write(stripped.essence.read(), 'wb')
        metadata = piexif.load(str(essence_file))
        assert not any(metadata.values())

    def test_strip_raises_for_unsupported_format(self, manager, unknown_asset):
        with pytest.raises(UnsupportedFormatError):
            manager.strip(unknown_asset)
