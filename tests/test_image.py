import pytest

import adam.image
import io
import PIL.Image
import piexif


def test_supports_jfif():
    assert 'image/jpeg' in adam.supported_mime_types


jpeg_exif = {'0th': {piexif.ImageIFD.Artist: b'Test artist'}}


def jpeg_rgb_with_metadata():
    empty_image = PIL.Image.new('RGB', (1, 1))
    image_data = io.BytesIO()
    empty_image.save(image_data, 'JPEG')
    image_data.seek(0)

    exif_bytes = piexif.dump(jpeg_exif)
    image_with_exif_metadata = io.BytesIO()
    piexif.insert(exif_bytes, image_data.read(), image_with_exif_metadata)
    return image_with_exif_metadata


@pytest.fixture
def jpeg_asset():
    image_data = jpeg_rgb_with_metadata()
    jpeg_asset = adam.image.read_jpeg(image_data)
    return jpeg_asset


def test_read_jpeg_does_not_alter_the_original_file():
    original_image_file = jpeg_rgb_with_metadata()
    original_image_data = original_image_file.read()
    original_image_file.seek(0)

    adam.image.read_jpeg(original_image_file)

    original_image_file.seek(0)
    image_data_after_reading = original_image_file.read()
    assert original_image_data == image_data_after_reading


def test_read_jpeg_returns_asset_with_jpeg_mime_type(jpeg_asset):
    assert jpeg_asset['mime_type'] == 'image/jpeg'


def test_jpeg_asset_essence_is_filled(jpeg_asset):
    assert jpeg_asset.essence is not None


def test_jpeg_asset_contains_size_information(jpeg_asset):
    assert jpeg_asset.metadata['adam']['width'] == 1
    assert jpeg_asset.metadata['adam']['height'] == 1


def test_jpeg_asset_essence_is_a_jpeg(jpeg_asset):
    jpeg_image = PIL.Image.open(jpeg_asset.essence)

    assert jpeg_image.format == 'JPEG'


def test_jpeg_asset_essence_can_be_read_multiple_times(jpeg_asset):
    essence_contents = jpeg_asset.essence.read()
    same_essence_contents = jpeg_asset.essence.read()

    assert essence_contents == same_essence_contents


def test_jpeg_asset_essence_does_not_contain_exif_metadata(jpeg_asset):
    essence_bytes = jpeg_asset.essence.read()

    essence_exif = piexif.load(essence_bytes)

    for ifd, ifd_data in essence_exif.items():
        assert not ifd_data


def test_jpeg_asset_contains_artist_information(jpeg_asset):
    assert jpeg_asset.metadata['adam']['artist'] == 'Test artist'


def test_jpeg_asset_contains_raw_exif_metadata(jpeg_asset):
    assert jpeg_asset.metadata['exif'] == jpeg_exif
