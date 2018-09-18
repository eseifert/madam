import io
import sys
from unittest.mock import patch

import pyexiv2
import pytest

from madam import Madam
from madam.core import Asset, UnsupportedFormatError
from assets import DEFAULT_WIDTH, DEFAULT_HEIGHT, DEFAULT_DURATION
from assets import asset, unknown_asset
from assets import image_asset, jpeg_image_asset, png_image_asset, \
    gif_image_asset, bmp_image_asset, tiff_image_asset,  webp_image_asset, \
    svg_vector_asset, jpeg_data_with_exif
from assets import audio_asset, mp3_audio_asset, opus_audio_asset, wav_audio_asset
from assets import video_asset, avi_video_asset, mp2_video_asset, mp4_video_asset, mkv_video_asset, ogg_video_asset


@pytest.fixture(name='madam', scope='class')
def madam_instance():
    return Madam()


def test_get_processor_returns_processor_for_readable_asset(madam, asset):
    processor = madam.get_processor(asset.essence)
    assert processor is not None


def test_get_processor_returns_none_for_unreadable_asset(madam, unknown_asset):
    processor = madam.get_processor(unknown_asset.essence)
    assert processor is None


def test_read_returns_jpeg_asset_with_correct_metadata(madam, jpeg_data_with_exif):
    jpeg_with_metadata = jpeg_data_with_exif

    asset = madam.read(jpeg_with_metadata)

    assert 'exif' in asset.metadata


def test_read_returns_jpeg_asset_whose_essence_does_not_contain_metadata(madam, jpeg_image_asset, tmpdir):
    jpeg_with_metadata = jpeg_image_asset

    asset = madam.read(jpeg_with_metadata.essence)

    essence_file = tmpdir.join('essence_without_metadata.jpg')
    essence_file.write(asset.essence.read(), 'wb')
    metadata = pyexiv2.metadata.ImageMetadata(str(essence_file))
    metadata.read()
    assert not metadata


def test_read_empty_file_raises_error(madam):
    file_data = io.BytesIO()

    with pytest.raises(UnsupportedFormatError):
        madam.read(file_data)


def test_read_raises_when_file_is_none(madam):
    invalid_file = None

    with pytest.raises(TypeError):
        madam.read(invalid_file)


def test_read_raises_error_when_format_is_unknown(madam, unknown_asset):
    with pytest.raises(UnsupportedFormatError):
        madam.read(unknown_asset.essence)


@pytest.fixture(scope='class')
def read_asset(madam, asset):
    return madam.read(asset.essence)


def test_read_returns_asset_when_reading_valid_data(read_asset):
    assert read_asset is not None


def test_read_returns_asset_with_correct_mime_type(madam, asset):
    read_asset = madam.read(asset.essence)
    assert read_asset.mime_type == asset.mime_type


def test_read_stores_additional_metadata(madam, asset):
    filename = 'foobar'

    read_asset = madam.read(asset.essence, additional_metadata=dict(filename=filename))

    assert 'filename' in read_asset.metadata
    assert read_asset.filename == filename


def test_read_returns_asset_whose_essence_is_filled(read_asset):
    assert read_asset.essence.read()


def test_read_jpeg_does_not_alter_the_original_file(madam):
    jpeg_data = jpeg_image_asset().essence
    original_image_data = jpeg_data.read()
    jpeg_data.seek(0)

    madam.read(jpeg_data)

    jpeg_data.seek(0)
    image_data_after_reading = jpeg_data.read()
    assert original_image_data == image_data_after_reading


def test_read_video_returns_asset_with_duration_metadata(madam, video_asset):
    asset = madam.read(video_asset.essence)

    assert asset.duration == pytest.approx(video_asset.duration, rel=0.4)


def test_read_video_returns_asset_containing_video_size_metadata(madam, video_asset):
    asset = madam.read(video_asset.essence)

    assert asset.width == DEFAULT_WIDTH
    assert asset.height == DEFAULT_HEIGHT


def test_read_returns_asset_containing_image_size_metadata(madam, image_asset):
    image_data = image_asset.essence

    asset = madam.read(image_data)

    assert asset.width == DEFAULT_WIDTH
    assert asset.height == DEFAULT_HEIGHT


def test_read_return_correct_hierarchy_of_metadata(madam, jpeg_image_asset, tmpdir):
    file = tmpdir.join('asset_with_metadata.jpg')
    file.write(jpeg_image_asset.essence.read(), 'wb')
    metadata = pyexiv2.metadata.ImageMetadata(str(file))
    metadata.read()
    metadata['Iptc.Application2.Headline'] = ['Foo']
    metadata['Iptc.Application2.Caption'] = ['Bar']
    metadata.write()

    asset = madam.read(file.open('rb'))

    assert 'exif' not in asset.metadata
    assert 'iptc' in asset.metadata
    assert len(asset.iptc) == 2


def test_read_only_returns_python_types_in_metadata(madam, jpeg_image_asset, tmpdir):
    import datetime, fractions, frozendict
    allowed_types = {str, float, int, tuple, frozendict.frozendict,
                     datetime.datetime, fractions.Fraction}
    file = tmpdir.join('asset_with_metadata.jpg')
    file.write(jpeg_image_asset.essence.read(), 'wb')
    metadata = pyexiv2.metadata.ImageMetadata(str(file))
    metadata.read()
    metadata['Exif.Image.Artist'] = b'Test artist'
    metadata['Iptc.Application2.Caption'] = ['Foo bar']
    metadata.write()

    asset = madam.read(file.open('rb'))

    for metadata_type in {'exif', 'iptc'}:
        values = asset.metadata[metadata_type].values()
        assert values
        for value in values:
            assert type(value) in allowed_types


def test_writes_correct_essence_without_metadata(madam, asset):
    asset = Asset(essence=asset.essence)
    file = io.BytesIO()

    madam.write(asset, file)

    file.seek(0)
    assert file.read() == asset.essence.read()


def test_writes_correct_essence_with_metadata(madam, jpeg_image_asset):
    file = io.BytesIO()

    madam.write(jpeg_image_asset, file)

    file.seek(0)
    assert file.read() != jpeg_image_asset.essence.read()


def test_config_contains_list_of_all_processors_by_default(madam):
    assert madam.config['processors'] == [
        'madam.image.PillowProcessor',
        'madam.vector.SVGProcessor',
        'madam.ffmpeg.FFmpegProcessor',
    ]


def test_config_contains_list_of_all_metadata_processors_by_default(madam):
    assert madam.config['metadata_processors'] == [
        'madam.exiv2.Exiv2MetadataProcessor',
        'madam.vector.SVGMetadataProcessor',
        'madam.ffmpeg.FFmpegMetadataProcessor',
    ]


def test_config_does_not_contain_metadata_processor_when_it_is_not_installed():
    with patch.dict(sys.modules, {'madam.exiv2': None}):
        manager = Madam()

    assert 'madam.exiv2.Exiv2MetadataProcessor' not in manager.config['metadata_processors']
