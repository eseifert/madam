import PIL.Image
import PIL.ImageChops
import pytest

import madam.image
from madam.core import OperatorError
from assets import DEFAULT_WIDTH, DEFAULT_HEIGHT
from assets import image_asset, get_jpeg_image_asset, jpeg_image_asset, png_image_asset_rgb, png_image_asset_rgb_alpha, \
    png_image_asset_palette, png_image_asset_gray, png_image_asset_gray_alpha, png_image_asset, gif_image_asset, \
    bmp_image_asset, tiff_image_asset_rgb, tiff_image_asset_rgb_alpha, tiff_image_asset_palette, \
    tiff_image_asset_gray_8bit, tiff_image_asset_gray_8bit_alpha, tiff_image_asset_gray_16bit, tiff_image_asset_cmyk,\
    tiff_image_asset, webp_image_asset_rgb, webp_image_asset_rgb_alpha, webp_image_asset, unknown_asset


def is_equal_in_black_white_space(result_image, expected_image):
    result_image_bw = result_image.convert('L').point(lambda value: 0 if value < 128 else 255, '1')
    expected_image_bw = expected_image.convert('L').point(lambda value: 0 if value < 128 else 255, '1')
    return PIL.ImageChops.difference(result_image_bw, expected_image_bw).getbbox() is None


class TestPillowProcessor:
    @pytest.fixture(name='processor', scope='class')
    def pillow_processor(self):
        return madam.image.PillowProcessor()

    @pytest.mark.parametrize('width, height', [(4, 3), (40, 30)])
    def test_resize_in_fit_mode_preserves_aspect_ratio_for_landscape_image(self, processor, width, height):
        jpeg_image_asset_landscape = get_jpeg_image_asset(width=width, height=height)
        resize_operator = processor.resize(width=9, height=10, mode=madam.image.ResizeMode.FIT)

        resized_asset = resize_operator(jpeg_image_asset_landscape)

        assert resized_asset.width == 9
        assert resized_asset.height == 7

    @pytest.mark.parametrize('width, height', [(3, 5), (30, 50)])
    def test_resize_in_fit_mode_preserves_aspect_ratio_for_portrait_image(self, processor, width, height):
        jpeg_image_asset_portrait = get_jpeg_image_asset(width=width, height=height)
        resize_operator = processor.resize(width=9, height=10, mode=madam.image.ResizeMode.FIT)

        resized_asset = resize_operator(jpeg_image_asset_portrait)

        assert resized_asset.width == 6
        assert resized_asset.height == 10

    @pytest.mark.parametrize('width, height', [(4, 3), (40, 30)])
    def test_resize_in_fill_mode_preserves_aspect_ratio_for_landscape_image(self, processor, width, height):
        jpeg_image_asset_landscape = get_jpeg_image_asset(width=width, height=height)
        resize_operator = processor.resize(width=9, height=10, mode=madam.image.ResizeMode.FILL)

        resized_asset = resize_operator(jpeg_image_asset_landscape)

        assert resized_asset.width == 13
        assert resized_asset.height == 10

    @pytest.mark.parametrize('width, height', [(3, 5), (30, 50)])
    def test_resize_in_fill_mode_preserves_aspect_ratio_for_portrait_image(self, processor, width, height):
        jpeg_image_asset_portrait = get_jpeg_image_asset(width=width, height=height)
        resize_operator = processor.resize(width=9, height=10, mode=madam.image.ResizeMode.FILL)

        resized_asset = resize_operator(jpeg_image_asset_portrait)

        assert resized_asset.width == 9
        assert resized_asset.height == 15

    def test_resize_scales_image_to_exact_dimensions_by_default(self, processor, jpeg_image_asset):
        asset = jpeg_image_asset
        resize_operator = processor.resize(width=9, height=10)

        resized_asset = resize_operator(asset)

        assert resized_asset.width == 9
        assert resized_asset.height == 10

    def test_resize_keeps_original_mime_type(self, processor, image_asset):
        resize_operator = processor.resize(width=9, height=10)

        resized_asset = resize_operator(image_asset)

        assert resized_asset.mime_type == image_asset.mime_type

    def test_transpose_flips_dimensions(self, processor):
        asset = get_jpeg_image_asset()
        transpose_operator = processor.transpose()

        transposed_asset = transpose_operator(asset)

        assert asset.width == transposed_asset.height and asset.height == transposed_asset.width

    def test_transpose_is_reversible(self, processor):
        asset = get_jpeg_image_asset()
        transpose_operator = processor.transpose()

        transposed_asset = transpose_operator(transpose_operator(asset))

        assert is_equal_in_black_white_space(PIL.Image.open(transposed_asset.essence), PIL.Image.open(asset.essence))

    def test_transpose_keeps_original_mime_type(self, processor):
        asset = get_jpeg_image_asset()
        transpose_operator = processor.transpose()

        transposed_asset = transpose_operator(asset)

        assert transposed_asset.mime_type == asset.mime_type

    @pytest.mark.parametrize('orientation', [
        madam.image.FlipOrientation.HORIZONTAL,
        madam.image.FlipOrientation.VERTICAL
    ])
    def test_flip_is_reversible(self, processor, orientation):
        asset = get_jpeg_image_asset()
        flip_operator = processor.flip(orientation=orientation)

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
    def test_auto_orient_rotates_asset_correctly(self, processor, exif_orientation, image_transpositions):
        reference_asset = get_jpeg_image_asset()
        misoriented_asset = get_jpeg_image_asset(transpositions=image_transpositions,
                                                 exif={'orientation': exif_orientation})
        auto_orient_operator = processor.auto_orient()

        oriented_asset = auto_orient_operator(misoriented_asset)

        assert is_equal_in_black_white_space(
            PIL.Image.open(reference_asset.essence),
            PIL.Image.open(oriented_asset.essence)
        )

    def test_auto_orient_without_orientation_returns_identical_asset(self, processor, jpeg_image_asset):
        asset_without_orientation_metadata = jpeg_image_asset

        auto_orient_operator = processor.auto_orient()

        oriented_asset = auto_orient_operator(asset_without_orientation_metadata)
        assert oriented_asset is asset_without_orientation_metadata

    def test_convert_returns_asset_with_correct_mime_type(self, processor, image_asset):
        asset = image_asset
        conversion_operator = processor.convert(
            mime_type='image/png', color_space='RGB', depth=8, data_type='uint')

        converted_asset = conversion_operator(asset)

        assert converted_asset.mime_type == 'image/png'

    def test_convert_creates_new_asset(self, processor):
        asset = get_jpeg_image_asset()
        conversion_operator = processor.convert(mime_type='image/png')

        converted_asset = conversion_operator(asset)

        assert isinstance(converted_asset, madam.core.Asset)
        assert converted_asset != asset

    def test_convert_raises_error_when_it_fails(self, processor, unknown_asset):
        conversion_operator = processor.convert(mime_type='image/png')

        with pytest.raises(OperatorError):
            conversion_operator(unknown_asset)

    def test_convert_returns_essence_is_of_specified_type(self, processor, image_asset):
        asset = image_asset
        conversion_operator = processor.convert(
            mime_type='image/png', color_space='RGB', depth=8, data_type='uint')

        converted_asset = conversion_operator(asset)

        image = PIL.Image.open(converted_asset.essence)
        assert image.format == 'PNG'

    def test_convert_returns_essence_with_specified_color_mode(self, processor, tiff_image_asset):
        asset = tiff_image_asset
        conversion_operator = processor.convert(mime_type='image/tiff', color_space='CMYK', depth=8, data_type='uint')

        converted_asset = conversion_operator(asset)

        image = PIL.Image.open(converted_asset.essence)
        assert image.mode == 'CMYK'

    @pytest.mark.parametrize('color_space,depth,data_type', [
        ('RGB', 8, 'uint'), ('LUMA', 8, 'uint')
    ])
    def test_convert_returns_asset_with_correct_color_mode_metadata(self, processor, image_asset,
                                                                    color_space, depth, data_type):
        asset = image_asset
        conversion_operator = processor.convert(
            mime_type='image/tiff', color_space=color_space, depth=depth, data_type=data_type)

        converted_asset = conversion_operator(asset)

        assert converted_asset.color_space == color_space

    def test_convert_maintains_dimensions(self, processor, jpeg_image_asset):
        asset = jpeg_image_asset
        conversion_operator = processor.convert(mime_type='image/png')

        converted_asset = conversion_operator(asset)

        assert converted_asset.width == asset.width
        assert converted_asset.height == asset.height

    def test_convert_maintains_original_palette(self, processor, png_image_asset_palette):
        asset = png_image_asset_palette
        original_image = PIL.Image.open(asset.essence)
        conversion_operator = processor.convert(
            mime_type='image/png', color_space='PALETTE', depth=8, data_type='uint')

        converted_asset = conversion_operator(asset)

        converted_image = PIL.Image.open(converted_asset.essence)
        assert converted_image.mode == 'P'
        assert converted_image.getpalette() == original_image.getpalette()

    def test_crop_with_original_dimensions_returns_identical_asset(self, processor, image_asset):
        crop_operator = processor.crop(x=0, y=0, width=image_asset.width, height=image_asset.height)

        cropped_asset = crop_operator(image_asset)

        assert cropped_asset is image_asset

    def test_crop_returns_asset_with_correct_dimensions(self, processor, image_asset):
        crop_width = image_asset.width // 2
        crop_height = image_asset.height // 2
        crop_x = (image_asset.width - crop_width) // 2
        crop_y = (image_asset.height - crop_height) // 2
        crop_operator = processor.crop(x=crop_x, y=crop_y, width=crop_width, height=crop_height)

        cropped_asset = crop_operator(image_asset)

        assert cropped_asset.width == crop_width
        assert cropped_asset.height == crop_height

    @pytest.mark.parametrize('x, y, width, height, cropped_width, cropped_height', [
        (-DEFAULT_WIDTH//2, -DEFAULT_HEIGHT//2, DEFAULT_WIDTH, DEFAULT_HEIGHT, DEFAULT_WIDTH//2, DEFAULT_HEIGHT//2),
        (DEFAULT_WIDTH//2, DEFAULT_HEIGHT//2, DEFAULT_WIDTH, DEFAULT_HEIGHT, DEFAULT_WIDTH//2, DEFAULT_HEIGHT//2),
    ])
    def test_crop_fixes_partially_overlapping_cropping_area(self, processor, image_asset,
                                                            x, y, width, height, cropped_width, cropped_height):
        crop_operator = processor.crop(x=x, y=y, width=width, height=height)

        cropped_asset = crop_operator(image_asset)

        assert cropped_asset.width == cropped_width
        assert cropped_asset.height == cropped_height

    @pytest.mark.parametrize('x, y, width, height', [
        (-DEFAULT_WIDTH, -DEFAULT_HEIGHT, DEFAULT_WIDTH, DEFAULT_HEIGHT),
        (DEFAULT_WIDTH, DEFAULT_HEIGHT, DEFAULT_WIDTH, DEFAULT_HEIGHT),
        (0, 0, -DEFAULT_WIDTH, -DEFAULT_HEIGHT),
    ])
    def test_crop_fails_with_non_overlapping_cropping_area(self, processor, image_asset, x, y, width, height):
        crop_operator = processor.crop(x=x, y=y, width=width, height=height)

        with pytest.raises(OperatorError):
            crop_operator(image_asset)

    @pytest.mark.parametrize('angle', [0.0, 360.0, -360.0])
    def test_rotate_without_rotation_returns_identical_asset(self, processor, image_asset, angle):
        rotate_operator = processor.rotate(angle=angle)

        rotated_asset = rotate_operator(image_asset)

        assert rotated_asset is image_asset

    @pytest.mark.parametrize('angle', [-45.0, 15.0, 90.0])
    def test_rotate_without_expand_maintains_original_dimensions(self, processor, image_asset, angle):
        rotate_operator = processor.rotate(angle=angle)

        rotated_asset = rotate_operator(image_asset)

        assert rotated_asset.width == image_asset.width
        assert rotated_asset.height == image_asset.height

    @pytest.mark.parametrize('angle', [-45.0, 15.0, 90.0])
    def test_rotate_with_expand_changes_dimensions(self, processor, image_asset, angle):
        rotate_operator = processor.rotate(angle=angle, expand=True)

        rotated_asset = rotate_operator(image_asset)

        assert rotated_asset.width != image_asset.width
        assert rotated_asset.height != image_asset.height
