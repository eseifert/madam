import io
import sys
from unittest.mock import patch

import piexif
import pytest

from madam import Madam
from madam.core import Asset, UnsupportedFormatError
from assets import DEFAULT_WIDTH, DEFAULT_HEIGHT, DEFAULT_DURATION
from assets import asset, unknown_asset
from assets import get_jpeg_image_asset, image_asset, jpeg_image_asset, png_image_asset_rgb, png_image_asset_rgb_alpha, \
    png_image_asset_palette, png_image_asset_gray, png_image_asset_gray_alpha, png_image_asset, gif_image_asset, \
    bmp_image_asset, tiff_image_asset_rgb, tiff_image_asset_rgb_alpha, tiff_image_asset_palette, \
    tiff_image_asset_gray_8bit, tiff_image_asset_gray_8bit_alpha, tiff_image_asset_gray_16bit, tiff_image_asset_cmyk, \
    tiff_image_asset, webp_image_asset_rgb, webp_image_asset_rgb_alpha, webp_image_asset, svg_vector_asset, \
    jpeg_data_with_exif
from assets import audio_asset, mp3_audio_asset, nut_audio_asset, opus_audio_asset, wav_audio_asset
from assets import video_asset, avi_video_asset, mp2_video_asset, mp4_video_asset, mkv_video_asset, nut_video_asset, \
    ogg_video_asset


class TestAsset:
    def test_asset_string_representation_contains_class_name(self):
        asset = Asset(essence=io.BytesIO(), mime_type='application/x-empty')

        asset_repr = repr(asset)

        assert asset.__class__.__qualname__ in asset_repr

    def test_asset_string_representation_contains_metadata(self):
        asset = Asset(essence=io.BytesIO(), mime_type='application/x-empty', magic=42)

        asset_repr = repr(asset)

        for key, val in asset.metadata.items():
            assert '{}={!r}'.format(key, val) in asset_repr

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

    def test_get_processor_returns_processor_for_readable_asset(self, manager, asset):
        processor = manager.get_processor(asset.essence)

        assert processor is not None

    def test_get_processor_returns_none_for_unreadable_asset(self, manager, unknown_asset):
        processor = manager.get_processor(unknown_asset.essence)

        assert processor is None

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
            manager.read(invalid_file)

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
        import datetime, fractions, frozendict
        allowed_types = {str, float, int, tuple, frozendict.frozendict,
                         datetime.datetime, fractions.Fraction}
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

    def test_config_contains_list_of_all_processors_by_default(self, manager):
        assert manager.config['processors'] == [
            'madam.image.PillowProcessor',
            'madam.vector.SVGProcessor',
            'madam.ffmpeg.FFmpegProcessor',
        ]

    def test_config_contains_list_of_all_metadata_processors_by_default(self, manager):
        assert manager.config['metadata_processors'] == [
            'madam.exif.ExifMetadataProcessor',
            'madam.vector.SVGMetadataProcessor',
            'madam.ffmpeg.FFmpegMetadataProcessor',
        ]

    def test_config_does_not_contain_metadata_processor_when_it_is_not_installed(self):
        with patch.dict(sys.modules, {'madam.exif': None}):
            manager = Madam()

        assert 'madam.exif.ExifMetadataProcessor' not in manager.config['metadata_processors']
