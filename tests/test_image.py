import PIL.Image
import PIL.ImageChops
import io
import piexif
import pytest

import madam.image
from madam.core import OperatorError, UnsupportedFormatError
from assets import jpeg_asset, png_asset, unknown_asset


def is_equal_in_black_white_space(result_image, expected_image):
    result_image_bw = result_image.convert('L').point(lambda value: 0 if value < 128 else 255, '1')
    expected_image_bw = expected_image.convert('L').point(lambda value: 0 if value < 128 else 255, '1')
    return PIL.ImageChops.difference(result_image_bw, expected_image_bw).getbbox() is None


class TestPillowProcessor:
    @pytest.fixture
    def pillow_processor(self):
        return madam.image.PillowProcessor()

    @pytest.mark.parametrize('width, height', [(4, 3), (40, 30)])
    def test_resize_in_fit_mode_preserves_aspect_ratio_for_landscape_image(self, pillow_processor, width, height):
        jpeg_asset_landscape = jpeg_asset(width=width, height=height)
        fit_asset_operator = pillow_processor.resize(width=9, height=10, mode=madam.image.ResizeMode.FIT)

        fitted_asset = fit_asset_operator(jpeg_asset_landscape)

        assert fitted_asset.width == 9
        assert fitted_asset.height == 7

    @pytest.mark.parametrize('width, height', [(3, 5), (30, 50)])
    def test_resize_in_fit_mode_preserves_aspect_ratio_for_portrait_image(self, pillow_processor, width, height):
        jpeg_asset_portrait = jpeg_asset(width=width, height=height)
        fit_asset_operator = pillow_processor.resize(width=9, height=10, mode=madam.image.ResizeMode.FIT)

        fitted_asset = fit_asset_operator(jpeg_asset_portrait)

        assert fitted_asset.width == 6
        assert fitted_asset.height == 10

    @pytest.mark.parametrize('width, height', [(4, 3), (40, 30)])
    def test_resize_in_fill_mode_preserves_aspect_ratio_for_landscape_image(self, pillow_processor, width, height):
        jpeg_asset_landscape = jpeg_asset(width=width, height=height)
        fill_asset_operator = pillow_processor.resize(width=9, height=10, mode=madam.image.ResizeMode.FILL)

        filling_asset = fill_asset_operator(jpeg_asset_landscape)

        assert filling_asset.width == 13
        assert filling_asset.height == 10

    @pytest.mark.parametrize('width, height', [(3, 5), (30, 50)])
    def test_resize_in_fill_mode_preserves_aspect_ratio_for_portrait_image(self, pillow_processor, width, height):
        jpeg_asset_portrait = jpeg_asset(width=width, height=height)
        fill_asset_operator = pillow_processor.resize(width=9, height=10, mode=madam.image.ResizeMode.FILL)

        filling_asset = fill_asset_operator(jpeg_asset_portrait)

        assert filling_asset.width == 9
        assert filling_asset.height == 15

    def test_resize_scales_image_to_exact_dimensions_by_default(self, pillow_processor):
        jpeg = jpeg_asset()
        resize_operator = pillow_processor.resize(width=9, height=10)

        filling_asset = resize_operator(jpeg)

        assert filling_asset.width == 9
        assert filling_asset.height == 10

    def test_transpose_flips_dimensions(self, pillow_processor):
        asset = jpeg_asset()
        transpose_operator = pillow_processor.transpose()

        transposed_asset = transpose_operator(asset)

        assert asset.width == transposed_asset.height and asset.height == transposed_asset.width

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
        misoriented_asset = jpeg_asset(transpositions=image_transpositions,
                                       exif={'0th': {piexif.ImageIFD.Orientation: exif_orientation}})
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

        assert isinstance(converted_asset, madam.core.Asset)
        assert converted_asset != asset

    def test_convert_raises_error_when_it_fails(self, pillow_processor, unknown_asset):
        conversion_operator = pillow_processor.convert(mime_type='image/png')

        with pytest.raises(OperatorError):
            conversion_operator(unknown_asset)

    def test_converted_essence_is_of_specified_type(self, pillow_processor):
        asset = jpeg_asset()
        conversion_operator = pillow_processor.convert(mime_type='image/png')

        converted_asset = conversion_operator(asset)

        image = PIL.Image.open(converted_asset.essence)
        assert image.format == 'PNG'

    def test_read_jpeg_does_not_alter_the_original_file(self, pillow_processor):
        jpeg_data = jpeg_asset().essence
        original_image_data = jpeg_data.read()
        jpeg_data.seek(0)

        pillow_processor._read(jpeg_data)

        jpeg_data.seek(0)
        image_data_after_reading = jpeg_data.read()
        assert original_image_data == image_data_after_reading

    @pytest.mark.parametrize('image_data', [jpeg_asset().essence, png_asset().essence])
    def test_image_asset_essence_is_filled(self, image_data, pillow_processor):
        asset = pillow_processor._read(image_data)

        assert asset.essence.read()

    @pytest.mark.parametrize('image_data', [jpeg_asset().essence, png_asset().essence])
    def test_jpeg_asset_contains_size_information(self, pillow_processor, image_data):
        asset = pillow_processor._read(image_data)

        assert asset.metadata['width'] == 4
        assert asset.metadata['height'] == 3


class TestExifProcessor:
    @pytest.fixture
    def exif_processor(self):
        return madam.image.ExifProcessor()

    def test_read_returns_empty_dict_when_jpeg_contains_no_exif(self, exif_processor):
        data_without_exif = jpeg_asset().essence

        exif = exif_processor.read(data_without_exif)

        assert not exif

    def test_read_returns_exif_dict_when_jpeg_contains_exif(self, exif_processor):
        exif = jpeg_asset().metadata['exif']
        data_with_exif = io.BytesIO()
        piexif.insert(piexif.dump(exif), jpeg_asset().essence.read(), new_file=data_with_exif)

        exif = exif_processor.read(data_with_exif)

        assert exif

    def test_read_raises_error_when_file_format_is_invalid(self, exif_processor):
        junk_data = io.BytesIO(b'abc123')

        with pytest.raises(UnsupportedFormatError):
            exif_processor.read(junk_data)

    def test_remove_returns_essence_without_metadata(self, exif_processor):
        exif = jpeg_asset().metadata['exif']
        jpeg_data = io.BytesIO()
        piexif.insert(piexif.dump(exif), jpeg_asset().essence.read(), new_file=jpeg_data)
        essence = exif_processor.strip(jpeg_data)

        essence_exif = piexif.load(essence.read())
        essence_exif_stripped_from_empty_entries = {key: value for (key, value) in essence_exif.items() if value}

        assert not essence_exif_stripped_from_empty_entries

    def test_add_returns_essence_with_metadata(self, exif_processor):
        essence = jpeg_asset().essence
        exif = jpeg_asset().metadata['exif']

        essence_with_exif = exif_processor.combine(essence, exif)

        contained_exif = piexif.load(essence_with_exif.read())
        exif_stripped_from_empty_entries = {key: value for (key, value) in contained_exif.items() if value}
        assert exif_stripped_from_empty_entries == exif
