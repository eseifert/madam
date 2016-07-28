import pytest

import madam.image
import io
import PIL.Image
import PIL.ImageChops
import piexif


jpeg_exif = {'0th': {piexif.ImageIFD.Artist: b'Test artist'}}


@pytest.fixture(scope='module', autouse=True)
def pillow_processor():
    exif_processor = madam.image.ExifProcessor()
    processor = madam.image.PillowProcessor(exif_processor)
    return processor


def image_rgb(width=4, height=3, transpositions=[]):
    image = PIL.Image.new('RGB', (width, height))
    # Fill the image with a shape which is (probably) not invariant towards
    # rotations or flips as long as the image has a size of (2, 2) or greater
    for y in range(0, height):
        for x in range(0, width):
            color = (255, 255, 255) if y == 0 or x == 0 else (0, 0, 0)
            image.putpixel((x, y), color)
    for transposition in transpositions:
        image = image.transpose(transposition)
    return image


def jpeg_rgb(exif={}, width=4, height=3, transpositions=[]):
    image = image_rgb(width=width, height=height, transpositions=transpositions)
    image_data = io.BytesIO()
    image.save(image_data, 'JPEG', quality=100)
    image_data.seek(0)

    image_with_exif_metadata = add_exif_to_jpeg(exif, image_data) if exif else image_data
    return image_with_exif_metadata


def png_rgb():
    image = image_rgb()
    image_data = io.BytesIO()
    image.save(image_data, 'PNG')
    image_data.seek(0)
    return image_data


def add_exif_to_jpeg(exif, image_data):
    exif_bytes = piexif.dump(exif)
    image_with_exif_metadata = io.BytesIO()
    piexif.insert(exif_bytes, image_data.read(), image_with_exif_metadata)
    return image_with_exif_metadata


def jpeg_asset(width=4, height=3, exif={}, transpositions=[]):
    asset = madam.core.Asset()
    asset.essence = jpeg_rgb(width=width, height=height, transpositions=transpositions)
    asset.metadata['exif'] = exif
    asset.metadata['madam'] = {'width': width, 'height': height}
    return asset


def png_asset():
    asset = madam.core.Asset()
    asset.essence = png_rgb()
    return asset


def is_equal_in_black_white_space(result_image, expected_image):
    result_image_bw = result_image.convert('L').point(lambda value: 0 if value < 128 else 255, '1')
    expected_image_bw = expected_image.convert('L').point(lambda value: 0 if value < 128 else 255, '1')
    return PIL.ImageChops.difference(result_image_bw, expected_image_bw).getbbox() is None


class TestPillowProcessor:
    @pytest.mark.parametrize('width, height', [(4, 3), (40, 30)])
    def test_resize_in_fit_mode_preserves_aspect_ratio_for_landscape_image(self, pillow_processor, width, height):
        jpeg_asset_landscape = jpeg_asset(width=width, height=height)
        fit_asset_operator = pillow_processor.resize(width=9, height=10, mode=madam.image.ResizeMode.FIT)

        fitted_asset = fit_asset_operator(jpeg_asset_landscape)

        assert fitted_asset['width'] == 9
        assert fitted_asset['height'] == 7

    @pytest.mark.parametrize('width, height', [(3, 5), (30, 50)])
    def test_resize_in_fit_mode_preserves_aspect_ratio_for_portrait_image(self, pillow_processor, width, height):
        jpeg_asset_portrait = jpeg_asset(width=width, height=height)
        fit_asset_operator = pillow_processor.resize(width=9, height=10, mode=madam.image.ResizeMode.FIT)

        fitted_asset = fit_asset_operator(jpeg_asset_portrait)

        assert fitted_asset['width'] == 6
        assert fitted_asset['height'] == 10

    @pytest.mark.parametrize('width, height', [(4, 3), (40, 30)])
    def test_resize_in_fill_mode_preserves_aspect_ratio_for_landscape_image(self, pillow_processor, width, height):
        jpeg_asset_landscape = jpeg_asset(width=width, height=height)
        fill_asset_operator = pillow_processor.resize(width=9, height=10, mode=madam.image.ResizeMode.FILL)

        filling_asset = fill_asset_operator(jpeg_asset_landscape)

        assert filling_asset['width'] == 13
        assert filling_asset['height'] == 10

    @pytest.mark.parametrize('width, height', [(3, 5), (30, 50)])
    def test_resize_in_fill_mode_preserves_aspect_ratio_for_portrait_image(self, pillow_processor, width, height):
        jpeg_asset_portrait = jpeg_asset(width=width, height=height)
        fill_asset_operator = pillow_processor.resize(width=9, height=10, mode=madam.image.ResizeMode.FILL)

        filling_asset = fill_asset_operator(jpeg_asset_portrait)

        assert filling_asset['width'] == 9
        assert filling_asset['height'] == 15

    def test_resize_scales_image_to_exact_dimensions_by_default(self, pillow_processor):
        jpeg = jpeg_asset()
        resize_operator = pillow_processor.resize(width=9, height=10)

        filling_asset = resize_operator(jpeg)

        assert filling_asset['width'] == 9
        assert filling_asset['height'] == 10

    def test_transpose_flips_dimensions(self, pillow_processor):
        asset = jpeg_asset()
        transpose_operator = pillow_processor.transpose()

        transposed_asset = transpose_operator(asset)

        assert asset['width'] == transposed_asset['height'] and asset['height'] == transposed_asset['width']

    def test_transpose_is_reversible(self, pillow_processor):
        asset = jpeg_asset()
        transpose_operator = pillow_processor.transpose()

        transposed_asset = transpose_operator(transpose_operator(asset))

        assert is_equal_in_black_white_space(PIL.Image.open(transposed_asset.essence), PIL.Image.open(asset.essence))

    @pytest.mark.parametrize('orientation', [madam.image.FlipOrientation.HORIZONTAL, madam.image.FlipOrientation.VERTICAL])
    def test_flip_is_reversible(self, pillow_processor, orientation):
        asset = jpeg_asset()
        flip_operator = pillow_processor.flip(orientation=orientation)

        flipped_asset = flip_operator(flip_operator(asset))

        assert is_equal_in_black_white_space(PIL.Image.open(flipped_asset.essence), PIL.Image.open(asset.essence))

    @pytest.mark.parametrize('exif_orientation, image_transpositions', [
        (1, []),
        (2, [PIL.Image.FLIP_LEFT_RIGHT]),
        (3, [PIL.Image.ROTATE_180]),
        (4, [PIL.Image.FLIP_TOP_BOTTOM]),
        (5, [PIL.Image.ROTATE_90, PIL.Image.FLIP_TOP_BOTTOM]),
        (6, [PIL.Image.ROTATE_90]),
        (7, [PIL.Image.ROTATE_90, PIL.Image.FLIP_LEFT_RIGHT]),
        (8, [PIL.Image.ROTATE_270])
    ])
    def test_auto_orient(self, pillow_processor, exif_orientation, image_transpositions):
        reference_asset = jpeg_asset()
        misoriented_asset = jpeg_asset(exif={'0th': {piexif.ImageIFD.Orientation: exif_orientation}}, transpositions=image_transpositions)
        auto_orient_operator = pillow_processor.auto_orient()

        oriented_asset = auto_orient_operator(misoriented_asset)

        assert is_equal_in_black_white_space(PIL.Image.open(reference_asset.essence), PIL.Image.open(oriented_asset.essence))

    def test_converted_asset_receives_correct_mime_type(self, pillow_processor):
        asset = jpeg_asset()
        conversion_operator = pillow_processor.convert(mime_type='image/png')

        converted_asset = conversion_operator(asset)

        assert converted_asset.mime_type == 'image/png'

    def test_convert_creates_new_asset(self, pillow_processor):
        asset = jpeg_asset()
        conversion_operator = pillow_processor.convert(mime_type='image/png')

        converted_asset = conversion_operator(asset)

        assert converted_asset is not asset

    def test_converted_essence_is_of_specified_type(self, pillow_processor):
        asset = jpeg_asset()
        conversion_operator = pillow_processor.convert(mime_type='image/png')

        converted_asset = conversion_operator(asset)

        image = PIL.Image.open(converted_asset.essence)
        assert image.format == 'PNG'

    @pytest.mark.parametrize('image_data, mime_type', [
        (jpeg_rgb(), 'image/jpeg'),
        (png_rgb(), 'image/png')
    ])
    def test_read_image_returns_asset_with_image_mime_type(self, pillow_processor, image_data, mime_type):
        asset = pillow_processor.read(image_data)

        assert asset['mime_type'] == mime_type

    def test_read_jpeg_does_not_alter_the_original_file(self, pillow_processor):
        jpeg_data = jpeg_rgb()
        original_image_data = jpeg_data.read()
        jpeg_data.seek(0)

        pillow_processor.read(jpeg_data)

        jpeg_data.seek(0)
        image_data_after_reading = jpeg_data.read()
        assert original_image_data == image_data_after_reading

    @pytest.mark.parametrize('image_data', [jpeg_rgb(), png_rgb()])
    def test_image_asset_essence_is_filled(self, image_data, pillow_processor):
        asset = pillow_processor.read(image_data)

        assert asset.essence is not None

    def test_jpeg_asset_contains_size_information(self, pillow_processor):
        jpeg_data = jpeg_rgb()

        asset = pillow_processor.read(jpeg_data)

        assert asset.metadata['madam']['width'] == 4
        assert asset.metadata['madam']['height'] == 3

    def test_jpeg_asset_essence_does_not_contain_exif_metadata(self, pillow_processor):
        jpeg_data = jpeg_rgb(exif=jpeg_exif)
        asset = pillow_processor.read(jpeg_data)
        essence_bytes = asset.essence.read()

        essence_exif = piexif.load(essence_bytes)

        for ifd, ifd_data in essence_exif.items():
            assert not ifd_data


class TestExifProcessor:
    @pytest.fixture
    def exif_processor(self):
        return madam.image.ExifProcessor()

    def test_read_returns_empty_dict_when_jpeg_contains_no_exif(self, exif_processor):
        jpeg_data = jpeg_rgb()

        exif = exif_processor.read(jpeg_data)

        assert not exif

    def test_read_returns_exif_dict_when_jpeg_contains_exif(self, exif_processor):
        jpeg_data = jpeg_rgb(exif=jpeg_exif)

        exif = exif_processor.read(jpeg_data)

        assert exif

    def test_remove_returns_essence_without_metadata(self, exif_processor):
        jpeg_data = jpeg_rgb(exif=jpeg_exif)
        essence = exif_processor.remove(jpeg_data)

        essence_exif = piexif.load(essence.read())
        essence_exif_stripped_from_empty_entries = {key: value for (key, value) in essence_exif.items() if value}

        assert not essence_exif_stripped_from_empty_entries
