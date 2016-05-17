import pytest

import adam.image
import io
import PIL.Image
import piexif


def test_supports_jfif():
    assert 'image/jpeg' in adam.supported_mime_types


jpeg_exif = {'0th': {piexif.ImageIFD.Artist: b'Test artist'}}


@pytest.fixture(scope='module', autouse=True)
def pillow_processor():
    processor = adam.image.PillowProcessor()
    return processor


def jpeg_rgb(exif={}, width=4, height=3):
    empty_image = PIL.Image.new('RGB', (width, height))
    image_data = io.BytesIO()
    empty_image.save(image_data, 'JPEG')
    image_data.seek(0)

    image_with_exif_metadata = add_exif_to_jpeg(exif, image_data) if exif else image_data
    return image_with_exif_metadata


def add_exif_to_jpeg(exif, image_data):
    exif_bytes = piexif.dump(exif)
    image_with_exif_metadata = io.BytesIO()
    piexif.insert(exif_bytes, image_data.read(), image_with_exif_metadata)
    return image_with_exif_metadata


@pytest.fixture
def jpeg_asset(width=4, height=3):
    jpeg_asset = adam.read(jpeg_rgb(width=width, height=height), 'image/jpeg')
    return jpeg_asset


@pytest.fixture
def jpeg_asset_with_exif():
    jpeg_data = jpeg_rgb(exif=jpeg_exif)
    jpeg_asset = adam.read(jpeg_data, 'image/jpeg')
    return jpeg_asset


def test_read_jpeg_does_not_alter_the_original_file():
    jpeg_data = jpeg_rgb()
    original_image_data = jpeg_data.read()
    jpeg_data.seek(0)

    adam.read(jpeg_data, 'image/jpeg')

    jpeg_data.seek(0)
    image_data_after_reading = jpeg_data.read()
    assert original_image_data == image_data_after_reading


def test_read_jpeg_returns_asset_with_jpeg_mime_type(jpeg_asset):
    assert jpeg_asset['mime_type'] == 'image/jpeg'


def test_jpeg_asset_essence_is_filled(jpeg_asset):
    assert jpeg_asset.essence is not None


def test_jpeg_asset_contains_size_information(jpeg_asset):
    assert jpeg_asset.metadata['adam']['width'] == 4
    assert jpeg_asset.metadata['adam']['height'] == 3


def test_jpeg_asset_essence_is_a_jpeg(jpeg_asset):
    jpeg_image = PIL.Image.open(jpeg_asset.essence)

    assert jpeg_image.format == 'JPEG'


def test_jpeg_asset_essence_can_be_read_multiple_times(jpeg_asset):
    essence_contents = jpeg_asset.essence.read()
    same_essence_contents = jpeg_asset.essence.read()

    assert essence_contents == same_essence_contents


def test_jpeg_asset_essence_does_not_contain_exif_metadata(jpeg_asset_with_exif):
    essence_bytes = jpeg_asset_with_exif.essence.read()

    essence_exif = piexif.load(essence_bytes)

    for ifd, ifd_data in essence_exif.items():
        assert not ifd_data


def test_jpeg_asset_contains_artist_information_when_exif_metadata_is_available(jpeg_asset_with_exif):
    assert jpeg_asset_with_exif.metadata['adam']['artist'] == 'Test artist'


def test_jpeg_asset_contains_raw_exif_metadata(jpeg_asset_with_exif):
    assert jpeg_asset_with_exif.metadata['exif'] == jpeg_exif


class TestPillowProcessor:
    @pytest.mark.parametrize('width, height', [(4, 3), (40, 30)])
    def test_resize_in_fit_mode_preserves_aspect_ratio_for_landscape_image(self, pillow_processor, width, height):
        jpeg_asset_landscape = jpeg_asset(width=width, height=height)
        fit_asset_operator = pillow_processor.resize(width=9, height=10, mode=adam.image.ResizeMode.FIT)

        fitted_asset = fit_asset_operator(jpeg_asset_landscape)

        assert fitted_asset['width'] == 9
        assert fitted_asset['height'] == 7

    @pytest.mark.parametrize('width, height', [(3, 5), (30, 50)])
    def test_resize_in_fit_mode_preserves_aspect_ratio_for_portrait_image(self, pillow_processor, width, height):
        jpeg_asset_portrait = jpeg_asset(width=width, height=height)
        fit_asset_operator = pillow_processor.resize(width=9, height=10, mode=adam.image.ResizeMode.FIT)

        fitted_asset = fit_asset_operator(jpeg_asset_portrait)

        assert fitted_asset['width'] == 6
        assert fitted_asset['height'] == 10

    @pytest.mark.parametrize('width, height', [(4, 3), (40, 30)])
    def test_resize_in_fill_mode_preserves_aspect_ratio_for_landscape_image(self, pillow_processor, width, height):
        jpeg_asset_landscape = jpeg_asset(width=width, height=height)
        fill_asset_operator = pillow_processor.resize(width=9, height=10, mode=adam.image.ResizeMode.FILL)

        filling_asset = fill_asset_operator(jpeg_asset_landscape)

        assert filling_asset['width'] == 13
        assert filling_asset['height'] == 10

    @pytest.mark.parametrize('width, height', [(3, 5), (30, 50)])
    def test_resize_in_fill_mode_preserves_aspect_ratio_for_portrait_image(self, pillow_processor, width, height):
        jpeg_asset_portrait = jpeg_asset(width=width, height=height)
        fill_asset_operator = pillow_processor.resize(width=9, height=10, mode=adam.image.ResizeMode.FILL)

        filling_asset = fill_asset_operator(jpeg_asset_portrait)

        assert filling_asset['width'] == 9
        assert filling_asset['height'] == 15

    def test_resize_scales_image_to_exact_dimensions_by_default(self, pillow_processor):
        jpeg = jpeg_asset()
        resize_operator = pillow_processor.resize(width=9, height=10)

        filling_asset = resize_operator(jpeg)

        assert filling_asset['width'] == 9
        assert filling_asset['height'] == 10

    def test_write_jpeg_creates_file_containing_asset_essence(self, pillow_processor, jpeg_asset):
        file_data = io.BytesIO()

        pillow_processor.write(jpeg_asset, file_data)

        file_data.seek(0)
        assert file_data.read() == jpeg_asset.essence.read()
