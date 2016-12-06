import io
import sys
from unittest.mock import patch

import pyexiv2
import pytest

from madam import Madam
from madam.core import Asset, UnsupportedFormatError
from assets import DEFAULT_WIDTH, DEFAULT_HEIGHT, DEFAULT_DURATION
from assets import asset, unknown_asset
from assets import image_asset, jpeg_asset, png_asset, gif_asset
from assets import audio_asset, mp3_asset, opus_asset, wav_asset
from assets import video_asset, mp4_asset, mkv_video_asset, ogg_video_asset


@pytest.fixture(name='madam', scope='class')
def madam_instance():
    return Madam()


def test_read_returns_jpeg_asset_whose_essence_does_not_contain_exif(madam, jpeg_asset, tmpdir):
    exif = jpeg_asset.exif
    file = tmpdir.join('asset_with_exif.jpg')
    file.write(jpeg_asset.essence.read(), 'wb')
    metadata = pyexiv2.metadata.ImageMetadata(str(file))
    metadata.read()
    for key in exif:
        metadata['Exif.'+key.title()] = exif[key]
    metadata.write()

    asset = madam.read(file.open('rb'))

    essence_file = tmpdir.join('essence_without_exif.jpg')
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

    read_asset = madam.read(asset.essence, metadata=dict(filename=filename))

    assert 'filename' in read_asset.metadata
    assert read_asset.filename == filename


def test_read_returns_asset_whose_essence_is_filled(read_asset):
    assert read_asset.essence.read()


def test_read_jpeg_does_not_alter_the_original_file(madam):
    jpeg_data = jpeg_asset().essence
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


def test_writes_correct_essence_without_metadata(madam, asset):
    asset = Asset(essence=asset.essence)
    file = io.BytesIO()

    madam.write(asset, file)

    file.seek(0)
    assert file.read() == asset.essence.read()


def test_writes_correct_essence_with_metadata(madam, jpeg_asset):
    file = io.BytesIO()

    madam.write(jpeg_asset, file)

    file.seek(0)
    assert file.read() != jpeg_asset.essence.read()


def test_config_contains_list_of_all_processors_by_default(madam):
    assert madam.config['processors'] == [
        'madam.image.PillowProcessor',
        'madam.ffmpeg.FFmpegProcessor',
    ]


def test_config_contains_list_of_all_metadata_processors_by_default(madam):
    assert madam.config['metadata_processors'] == [
        'madam.exiv2.Exiv2MetadataProcessor',
        'madam.ffmpeg.FFmpegMetadataProcessor',
    ]


def test_config_does_not_contain_metadata_processor_when_it_is_not_installed():
    with patch.dict(sys.modules, {'madam.exiv2': None}):
        madam = Madam()

    assert 'madam.exiv2.Exiv2MetadataProcessor' not in madam.config['metadata_processors']
