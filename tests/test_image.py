import io

import PIL.Image
import PIL.ImageChops
import pytest
from assets import (
    DEFAULT_HEIGHT,
    DEFAULT_WIDTH,
    get_jpeg_image_asset,
)

import madam.core
import madam.image
from madam.core import OperatorError


def _solid_png_asset(color, width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT):
    """Return a lossless PNG Asset filled with a uniform color."""
    image = PIL.Image.new('RGB', (width, height), color)
    essence = io.BytesIO()
    image.save(essence, 'PNG')
    essence.seek(0)
    return madam.core.Asset(
        essence,
        mime_type='image/png',
        width=width,
        height=height,
        color_space='RGB',
        depth=8,
        data_type='uint',
    )


def is_equal_in_black_white_space(result_image, expected_image):
    result_image_bw = result_image.convert('L').point(lambda value: 0 if value < 128 else 255, '1')
    expected_image_bw = expected_image.convert('L').point(lambda value: 0 if value < 128 else 255, '1')
    return PIL.ImageChops.difference(result_image_bw, expected_image_bw).getbbox() is None


class TestPillowProcessor:
    @pytest.fixture(name='processor', scope='class')
    def pillow_processor(self):
        return madam.image.PillowProcessor()

    def test_stores_configuration(self):
        config = dict(foo='bar')
        processor = madam.image.PillowProcessor(config)

        assert processor.config['foo'] == 'bar'

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

        with PIL.Image.open(transposed_asset.essence) as transposed_image, PIL.Image.open(asset.essence) as image:
            assert is_equal_in_black_white_space(transposed_image, image)

    def test_transpose_keeps_original_mime_type(self, processor):
        asset = get_jpeg_image_asset()
        transpose_operator = processor.transpose()

        transposed_asset = transpose_operator(asset)

        assert transposed_asset.mime_type == asset.mime_type

    @pytest.mark.parametrize(
        'orientation', [madam.image.FlipOrientation.HORIZONTAL, madam.image.FlipOrientation.VERTICAL]
    )
    def test_flip_is_reversible(self, processor, orientation):
        asset = get_jpeg_image_asset()
        flip_operator = processor.flip(orientation=orientation)

        flipped_asset = flip_operator(flip_operator(asset))

        with PIL.Image.open(flipped_asset.essence) as flipped_image, PIL.Image.open(asset.essence) as image:
            assert is_equal_in_black_white_space(flipped_image, image)

    @pytest.mark.parametrize(
        'exif_orientation, image_transpositions',
        [
            (1, []),
            (2, [PIL.Image.FLIP_LEFT_RIGHT]),
            (3, [PIL.Image.ROTATE_180]),
            (4, [PIL.Image.FLIP_TOP_BOTTOM]),
            (5, [PIL.Image.ROTATE_90, PIL.Image.FLIP_TOP_BOTTOM]),
            (6, [PIL.Image.ROTATE_90]),
            (7, [PIL.Image.ROTATE_90, PIL.Image.FLIP_LEFT_RIGHT]),
            (8, [PIL.Image.ROTATE_270]),
        ],
    )
    def test_auto_orient_rotates_asset_correctly(self, processor, exif_orientation, image_transpositions):
        reference_asset = get_jpeg_image_asset()
        misoriented_asset = get_jpeg_image_asset(
            transpositions=image_transpositions, exif={'orientation': exif_orientation}
        )
        auto_orient_operator = processor.auto_orient()

        oriented_asset = auto_orient_operator(misoriented_asset)

        with (
            PIL.Image.open(reference_asset.essence) as reference_image,
            PIL.Image.open(oriented_asset.essence) as oriented_image,
        ):
            assert is_equal_in_black_white_space(reference_image, oriented_image)

    def test_auto_orient_without_orientation_returns_identical_asset(self, processor, jpeg_image_asset):
        asset_without_orientation_metadata = jpeg_image_asset

        auto_orient_operator = processor.auto_orient()

        oriented_asset = auto_orient_operator(asset_without_orientation_metadata)
        assert oriented_asset is asset_without_orientation_metadata

    def test_convert_returns_asset_with_correct_mime_type(self, processor, image_asset):
        asset = image_asset
        conversion_operator = processor.convert(mime_type='image/png', color_space='RGB', depth=8, data_type='uint')

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
        conversion_operator = processor.convert(mime_type='image/png', color_space='RGB', depth=8, data_type='uint')

        converted_asset = conversion_operator(asset)

        with PIL.Image.open(converted_asset.essence) as image:
            assert image.format == 'PNG'

    def test_convert_returns_essence_with_specified_color_mode(self, processor, tiff_image_asset):
        asset = tiff_image_asset
        conversion_operator = processor.convert(mime_type='image/tiff', color_space='CMYK', depth=8, data_type='uint')

        converted_asset = conversion_operator(asset)

        with PIL.Image.open(converted_asset.essence) as image:
            assert image.mode == 'CMYK'

    @pytest.mark.parametrize('color_space,depth,data_type', [('RGB', 8, 'uint'), ('LUMA', 8, 'uint')])
    def test_convert_returns_asset_with_correct_color_mode_metadata(
        self, processor, image_asset, color_space, depth, data_type
    ):
        asset = image_asset
        conversion_operator = processor.convert(
            mime_type='image/tiff', color_space=color_space, depth=depth, data_type=data_type
        )

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
        with PIL.Image.open(asset.essence) as original_image:
            original_palette = original_image.getpalette()
        conversion_operator = processor.convert(mime_type='image/png', color_space='PALETTE', depth=8, data_type='uint')
        converted_asset = conversion_operator(asset)

        with PIL.Image.open(converted_asset.essence) as converted_image:
            assert converted_image.mode == 'P'
            assert converted_image.getpalette() == original_palette

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

    @pytest.mark.parametrize(
        'x, y, width, height, cropped_width, cropped_height',
        [
            (
                -DEFAULT_WIDTH // 2,
                -DEFAULT_HEIGHT // 2,
                DEFAULT_WIDTH,
                DEFAULT_HEIGHT,
                DEFAULT_WIDTH // 2,
                DEFAULT_HEIGHT // 2,
            ),
            (
                DEFAULT_WIDTH // 2,
                DEFAULT_HEIGHT // 2,
                DEFAULT_WIDTH,
                DEFAULT_HEIGHT,
                DEFAULT_WIDTH // 2,
                DEFAULT_HEIGHT // 2,
            ),
        ],
    )
    def test_crop_fixes_partially_overlapping_cropping_area(
        self, processor, image_asset, x, y, width, height, cropped_width, cropped_height
    ):
        crop_operator = processor.crop(x=x, y=y, width=width, height=height)

        cropped_asset = crop_operator(image_asset)

        assert cropped_asset.width == cropped_width
        assert cropped_asset.height == cropped_height

    @pytest.mark.parametrize(
        'x, y, width, height',
        [
            (-DEFAULT_WIDTH, -DEFAULT_HEIGHT, DEFAULT_WIDTH, DEFAULT_HEIGHT),
            (DEFAULT_WIDTH, DEFAULT_HEIGHT, DEFAULT_WIDTH, DEFAULT_HEIGHT),
            (0, 0, -DEFAULT_WIDTH, -DEFAULT_HEIGHT),
        ],
    )
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

    def test_read_avif_returns_correct_metadata(self, processor, avif_image_asset):
        assert avif_image_asset.mime_type == 'image/avif'
        assert avif_image_asset.width == DEFAULT_WIDTH
        assert avif_image_asset.height == DEFAULT_HEIGHT

    def test_avif_quality_is_configurable(self):
        config = {'image/avif': {'quality': 50, 'speed': 8}}
        processor = madam.image.PillowProcessor(config)
        asset = madam.image.PillowProcessor()._image_to_asset(
            PIL.Image.new('RGB', (DEFAULT_WIDTH, DEFAULT_HEIGHT)), 'image/avif'
        )
        converted = processor.convert(mime_type='image/avif')(asset)
        assert converted.mime_type == 'image/avif'


class TestPillowVignette:
    @pytest.fixture(name='processor', scope='class')
    def pillow_processor(self):
        return madam.image.PillowProcessor()

    def test_vignette_preserves_dimensions(self, processor):
        asset = _solid_png_asset((200, 200, 200))
        result = processor.vignette()(asset)
        assert result.width == asset.width
        assert result.height == asset.height

    def test_vignette_preserves_mime_type(self, processor):
        asset = _solid_png_asset((200, 200, 200))
        result = processor.vignette()(asset)
        assert result.mime_type == asset.mime_type

    def test_vignette_darkens_corners_relative_to_center(self, processor):
        # On a uniform image, center pixel should be brighter than corner pixel
        asset = _solid_png_asset((200, 200, 200), width=32, height=32)
        result = processor.vignette(strength=0.8)(asset)
        with PIL.Image.open(result.essence) as image:
            center = image.getpixel((16, 16))
            corner = image.getpixel((0, 0))
            # Sum of RGB channels: center must be brighter than corner
            assert sum(center) > sum(corner)

    def test_vignette_strength_zero_leaves_image_unchanged(self, processor):
        asset = _solid_png_asset((128, 64, 32))
        result = processor.vignette(strength=0.0)(asset)
        with PIL.Image.open(result.essence) as r, PIL.Image.open(asset.essence) as s:
            assert list(r.get_flattened_data()) == list(s.get_flattened_data())


class TestPillowTint:
    @pytest.fixture(name='processor', scope='class')
    def pillow_processor(self):
        return madam.image.PillowProcessor()

    def test_tint_preserves_dimensions(self, processor):
        asset = _solid_png_asset((200, 200, 200))
        result = processor.tint(color=(255, 0, 0))(asset)
        assert result.width == asset.width
        assert result.height == asset.height

    def test_tint_preserves_mime_type(self, processor):
        asset = _solid_png_asset((200, 200, 200))
        result = processor.tint(color=(255, 0, 0))(asset)
        assert result.mime_type == asset.mime_type

    def test_tint_shifts_pixel_colour_toward_tint(self, processor):
        # A white image tinted red: result must have more red than blue
        asset = _solid_png_asset((255, 255, 255))
        result = processor.tint(color=(255, 0, 0))(asset)
        with PIL.Image.open(result.essence) as image:
            r, g, b = image.getpixel((0, 0))
            assert r > b

    def test_tint_opacity_zero_leaves_image_unchanged(self, processor):
        asset = _solid_png_asset((80, 120, 200))
        result = processor.tint(color=(255, 0, 0), opacity=0.0)(asset)
        with PIL.Image.open(result.essence) as r, PIL.Image.open(asset.essence) as s:
            assert list(r.get_flattened_data()) == list(s.get_flattened_data())


class TestPillowSepia:
    @pytest.fixture(name='processor', scope='class')
    def pillow_processor(self):
        return madam.image.PillowProcessor()

    def test_sepia_preserves_dimensions(self, processor):
        asset = _solid_png_asset((200, 100, 50))
        result = processor.sepia()(asset)
        assert result.width == asset.width
        assert result.height == asset.height

    def test_sepia_output_is_png(self, processor):
        asset = _solid_png_asset((200, 100, 50))
        result = processor.sepia()(asset)
        assert result.mime_type == 'image/png'

    def test_sepia_produces_rgb_output(self, processor):
        asset = _solid_png_asset((200, 100, 50))
        result = processor.sepia()(asset)
        with PIL.Image.open(result.essence) as image:
            assert image.mode == 'RGB'

    def test_sepia_warm_tones(self, processor):
        # Sepia of a mid-grey pixel should have R > B (warm brownish tone)
        asset = _solid_png_asset((128, 128, 128))
        result = processor.sepia()(asset)
        with PIL.Image.open(result.essence) as image:
            r, g, b = image.getpixel((0, 0))
            assert r > b


class TestPillowSharpen:
    @pytest.fixture(name='processor', scope='class')
    def pillow_processor(self):
        return madam.image.PillowProcessor()

    def test_sharpen_preserves_dimensions(self, processor):
        asset = _solid_png_asset((128, 64, 32))
        result = processor.sharpen()(asset)
        assert result.width == asset.width
        assert result.height == asset.height

    def test_sharpen_preserves_mime_type(self, processor):
        asset = _solid_png_asset((128, 64, 32))
        result = processor.sharpen()(asset)
        assert result.mime_type == asset.mime_type

    def test_sharpen_changes_pixels_on_non_uniform_image(self, processor):
        image = PIL.Image.new('RGB', (DEFAULT_WIDTH, DEFAULT_HEIGHT), (128, 128, 128))
        image.putpixel((DEFAULT_WIDTH // 2, DEFAULT_HEIGHT // 2), (255, 255, 255))
        essence = io.BytesIO()
        image.save(essence, 'PNG')
        essence.seek(0)
        asset = madam.core.Asset(
            essence, mime_type='image/png', width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT,
            color_space='RGB', depth=8, data_type='uint',
        )
        result = processor.sharpen()(asset)
        with PIL.Image.open(result.essence) as r, PIL.Image.open(asset.essence) as s:
            assert list(r.get_flattened_data()) != list(s.get_flattened_data())


class TestPillowBlur:
    @pytest.fixture(name='processor', scope='class')
    def pillow_processor(self):
        return madam.image.PillowProcessor()

    def test_blur_preserves_dimensions(self, processor):
        asset = _solid_png_asset((128, 64, 32))
        result = processor.blur(radius=2)(asset)
        assert result.width == asset.width
        assert result.height == asset.height

    def test_blur_preserves_mime_type(self, processor):
        asset = _solid_png_asset((128, 64, 32))
        result = processor.blur(radius=2)(asset)
        assert result.mime_type == asset.mime_type

    def test_blur_changes_pixels_on_non_uniform_image(self, processor):
        # A non-uniform image: blurring spreads edge pixel values into interior
        image = PIL.Image.new('RGB', (DEFAULT_WIDTH, DEFAULT_HEIGHT), (0, 0, 0))
        image.putpixel((0, 0), (255, 255, 255))
        essence = io.BytesIO()
        image.save(essence, 'PNG')
        essence.seek(0)
        asset = madam.core.Asset(
            essence, mime_type='image/png', width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT,
            color_space='RGB', depth=8, data_type='uint',
        )
        result = processor.blur(radius=3)(asset)
        with PIL.Image.open(result.essence) as r, PIL.Image.open(asset.essence) as s:
            assert list(r.get_flattened_data()) != list(s.get_flattened_data())

    def test_blur_radius_zero_preserves_pixels(self, processor):
        asset = _solid_png_asset((80, 120, 200))
        result = processor.blur(radius=0)(asset)
        with PIL.Image.open(result.essence) as r, PIL.Image.open(asset.essence) as s:
            assert list(r.get_flattened_data()) == list(s.get_flattened_data())


class TestPillowAdjustSharpness:
    @pytest.fixture(name='processor', scope='class')
    def pillow_processor(self):
        return madam.image.PillowProcessor()

    def test_adjust_sharpness_preserves_dimensions(self, processor):
        asset = _solid_png_asset((128, 64, 32))
        result = processor.adjust_sharpness(factor=2.0)(asset)
        assert result.width == asset.width
        assert result.height == asset.height

    def test_adjust_sharpness_preserves_mime_type(self, processor):
        asset = _solid_png_asset((128, 64, 32))
        result = processor.adjust_sharpness(factor=2.0)(asset)
        assert result.mime_type == asset.mime_type

    def test_adjust_sharpness_factor_one_preserves_pixels(self, processor):
        asset = _solid_png_asset((80, 120, 200))
        result = processor.adjust_sharpness(factor=1.0)(asset)
        with PIL.Image.open(result.essence) as r, PIL.Image.open(asset.essence) as s:
            assert list(r.get_flattened_data()) == list(s.get_flattened_data())


class TestPillowAdjustSaturation:
    @pytest.fixture(name='processor', scope='class')
    def pillow_processor(self):
        return madam.image.PillowProcessor()

    def test_adjust_saturation_preserves_dimensions(self, processor):
        asset = _solid_png_asset((200, 100, 50))
        result = processor.adjust_saturation(factor=0.5)(asset)
        assert result.width == asset.width
        assert result.height == asset.height

    def test_adjust_saturation_preserves_mime_type(self, processor):
        asset = _solid_png_asset((200, 100, 50))
        result = processor.adjust_saturation(factor=0.5)(asset)
        assert result.mime_type == asset.mime_type

    def test_adjust_saturation_factor_one_preserves_pixels(self, processor):
        asset = _solid_png_asset((200, 100, 50))
        result = processor.adjust_saturation(factor=1.0)(asset)
        with PIL.Image.open(result.essence) as r, PIL.Image.open(asset.essence) as s:
            assert list(r.get_flattened_data()) == list(s.get_flattened_data())

    def test_adjust_saturation_factor_zero_produces_greyscale(self, processor):
        # factor=0 strips all colour — R, G, B channels become equal
        asset = _solid_png_asset((200, 100, 50))
        result = processor.adjust_saturation(factor=0.0)(asset)
        with PIL.Image.open(result.essence) as image:
            pixels = list(image.get_flattened_data())
            assert all(p[0] == p[1] == p[2] for p in pixels)


class TestPillowAdjustContrast:
    @pytest.fixture(name='processor', scope='class')
    def pillow_processor(self):
        return madam.image.PillowProcessor()

    def test_adjust_contrast_preserves_dimensions(self, processor):
        asset = _solid_png_asset((128, 128, 128))
        result = processor.adjust_contrast(factor=0.5)(asset)
        assert result.width == asset.width
        assert result.height == asset.height

    def test_adjust_contrast_preserves_mime_type(self, processor):
        asset = _solid_png_asset((128, 128, 128))
        result = processor.adjust_contrast(factor=0.5)(asset)
        assert result.mime_type == asset.mime_type

    def test_adjust_contrast_factor_one_preserves_pixels(self, processor):
        asset = _solid_png_asset((80, 120, 200))
        result = processor.adjust_contrast(factor=1.0)(asset)
        with PIL.Image.open(result.essence) as r, PIL.Image.open(asset.essence) as s:
            assert list(r.get_flattened_data()) == list(s.get_flattened_data())

    def test_adjust_contrast_factor_zero_produces_solid_grey(self, processor):
        # factor=0 collapses all pixels to the image mean — a solid grey
        asset = _solid_png_asset((0, 0, 0), width=4, height=4)
        result = processor.adjust_contrast(factor=0.0)(asset)
        with PIL.Image.open(result.essence) as image:
            pixels = list(image.get_flattened_data())
            assert len(set(pixels)) == 1  # all pixels identical


class TestPillowAdjustBrightness:
    @pytest.fixture(name='processor', scope='class')
    def pillow_processor(self):
        return madam.image.PillowProcessor()

    def test_adjust_brightness_preserves_dimensions(self, processor):
        asset = _solid_png_asset((128, 128, 128))
        result = processor.adjust_brightness(factor=0.5)(asset)
        assert result.width == asset.width
        assert result.height == asset.height

    def test_adjust_brightness_preserves_mime_type(self, processor):
        asset = _solid_png_asset((128, 128, 128))
        result = processor.adjust_brightness(factor=0.5)(asset)
        assert result.mime_type == asset.mime_type

    def test_adjust_brightness_factor_one_preserves_pixels(self, processor):
        asset = _solid_png_asset((128, 64, 32))
        result = processor.adjust_brightness(factor=1.0)(asset)
        with PIL.Image.open(result.essence) as r, PIL.Image.open(asset.essence) as s:
            assert list(r.get_flattened_data()) == list(s.get_flattened_data())

    def test_adjust_brightness_factor_zero_produces_black_image(self, processor):
        asset = _solid_png_asset((128, 128, 128))
        result = processor.adjust_brightness(factor=0.0)(asset)
        with PIL.Image.open(result.essence) as image:
            assert all(p == (0, 0, 0) for p in image.get_flattened_data())
