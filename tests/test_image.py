import io

import PIL.Image
import PIL.ImageChops
import PIL.ImageCms
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
    def test_resize_in_fill_mode_crops_landscape_image_to_target(self, processor, width, height):
        jpeg_image_asset_landscape = get_jpeg_image_asset(width=width, height=height)
        resize_operator = processor.resize(width=9, height=10, mode=madam.image.ResizeMode.FILL)

        resized_asset = resize_operator(jpeg_image_asset_landscape)

        assert resized_asset.width == 9
        assert resized_asset.height == 10

    @pytest.mark.parametrize('width, height', [(3, 5), (30, 50)])
    def test_resize_in_fill_mode_crops_portrait_image_to_target(self, processor, width, height):
        jpeg_image_asset_portrait = get_jpeg_image_asset(width=width, height=height)
        resize_operator = processor.resize(width=9, height=10, mode=madam.image.ResizeMode.FILL)

        resized_asset = resize_operator(jpeg_image_asset_portrait)

        assert resized_asset.width == 9
        assert resized_asset.height == 10

    def test_resize_in_fill_mode_produces_exact_target_dimensions(self, processor):
        asset = get_jpeg_image_asset(width=4, height=3)
        result = processor.resize(width=9, height=10, mode=madam.image.ResizeMode.FILL)(asset)
        assert result.width == 9
        assert result.height == 10

    @pytest.mark.parametrize(
        'gravity,x_sample,expected_pixel_column',
        [
            # Source: 20x10 image, left half white, right half black.
            # Scaled to fill 10x10 doubles width → 20x10 (height already fits).
            # west gravity crops from left  → white column at x=0
            # east gravity crops from right → black column at x=0 of the crop
            ('west', 0, (255, 255, 255)),
            ('east', 0, (0, 0, 0)),
        ],
    )
    def test_resize_in_fill_mode_gravity_selects_crop_region(self, processor, gravity, x_sample, expected_pixel_column):
        # Build a 20x10 PNG: left half white, right half black
        image = PIL.Image.new('RGB', (20, 10), (0, 0, 0))
        for y in range(10):
            for x in range(10):
                image.putpixel((x, y), (255, 255, 255))
        essence = io.BytesIO()
        image.save(essence, 'PNG')
        essence.seek(0)
        asset = madam.core.Asset(
            essence,
            mime_type='image/png',
            width=20,
            height=10,
            color_space='RGB',
            depth=8,
            data_type='uint',
        )
        # Resize to 10x10 fill — the image already fills height; width is
        # cropped. west keeps left (white), east keeps right (black).
        result = processor.resize(width=10, height=10, mode=madam.image.ResizeMode.FILL, gravity=gravity)(asset)
        assert result.width == 10
        assert result.height == 10
        with PIL.Image.open(result.essence) as img:
            assert img.getpixel((x_sample, 5)) == expected_pixel_column

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

    def test_crop_with_gravity_center_crops_to_correct_dimensions(self, processor):
        asset = _solid_png_asset((100, 100, 100), width=20, height=20)
        result = processor.crop(width=10, height=10, gravity='center')(asset)
        assert result.width == 10
        assert result.height == 10

    @pytest.mark.parametrize(
        'gravity,expected_pixel',
        [
            # Source: 20x20, white left half, black right half.
            # Crop 10x20 using gravity — west takes left (white), east takes right (black).
            ('west', (255, 255, 255)),
            ('east', (0, 0, 0)),
        ],
    )
    def test_crop_with_gravity_selects_correct_region(self, processor, gravity, expected_pixel):
        image = PIL.Image.new('RGB', (20, 20), (0, 0, 0))
        for y in range(20):
            for x in range(10):
                image.putpixel((x, y), (255, 255, 255))
        essence = io.BytesIO()
        image.save(essence, 'PNG')
        essence.seek(0)
        asset = madam.core.Asset(
            essence,
            mime_type='image/png',
            width=20,
            height=20,
            color_space='RGB',
            depth=8,
            data_type='uint',
        )
        result = processor.crop(width=10, height=20, gravity=gravity)(asset)
        with PIL.Image.open(result.essence) as img:
            assert img.getpixel((5, 10)) == expected_pixel

    def test_crop_explicit_x_y_ignores_gravity(self, processor):
        # Explicit x=0,y=0 always takes the top-left regardless of gravity
        asset = _solid_png_asset((0, 0, 0), width=20, height=20)
        result = processor.crop(x=0, y=0, width=10, height=10, gravity='south_east')(asset)
        assert result.width == 10
        assert result.height == 10

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


class TestPillowCropToFocalPoint:
    @pytest.fixture(name='processor', scope='class')
    def pillow_processor(self):
        return madam.image.PillowProcessor()

    def test_crop_to_focal_point_produces_requested_dimensions(self, processor):
        asset = _solid_png_asset((100, 100, 100), width=40, height=30)
        result = processor.crop_to_focal_point(width=20, height=15, focal_x=0.5, focal_y=0.5)(asset)
        assert result.width == 20
        assert result.height == 15

    def test_crop_to_focal_point_preserves_mime_type(self, processor):
        asset = _solid_png_asset((100, 100, 100), width=40, height=30)
        result = processor.crop_to_focal_point(width=20, height=15, focal_x=0.5, focal_y=0.5)(asset)
        assert result.mime_type == asset.mime_type

    def test_crop_to_focal_point_center_focal_point_crops_center(self, processor):
        # 40x10 source: left quarter white, rest black.
        # focal at (0.5, 0.5) — center. Crop 10x10.
        # Center of 40x10 is at x=20. A 10x10 window centered there spans x 15-25.
        # Left column (x<10) should not appear; all crop pixels should be black.
        image = PIL.Image.new('RGB', (40, 10), (0, 0, 0))
        for y in range(10):
            for x in range(10):
                image.putpixel((x, y), (255, 255, 255))
        essence = io.BytesIO()
        image.save(essence, 'PNG')
        essence.seek(0)
        asset = madam.core.Asset(
            essence,
            mime_type='image/png',
            width=40,
            height=10,
            color_space='RGB',
            depth=8,
            data_type='uint',
        )
        result = processor.crop_to_focal_point(width=10, height=10, focal_x=0.5, focal_y=0.5)(asset)
        with PIL.Image.open(result.essence) as img:
            # All pixels in this center crop should be black
            assert all(p == (0, 0, 0) for p in img.get_flattened_data())

    def test_crop_to_focal_point_edge_focal_point_clamps_to_bounds(self, processor):
        # focal at (0.0, 0.0) — top-left corner. The crop window cannot go
        # left of x=0 or above y=0, so it must start at (0, 0).
        asset = _solid_png_asset((0, 0, 0), width=40, height=30)
        result = processor.crop_to_focal_point(width=10, height=10, focal_x=0.0, focal_y=0.0)(asset)
        assert result.width == 10
        assert result.height == 10

    def test_crop_to_focal_point_raises_when_crop_larger_than_source(self, processor):
        asset = _solid_png_asset((100, 100, 100), width=10, height=10)
        with pytest.raises(OperatorError):
            processor.crop_to_focal_point(width=20, height=20, focal_x=0.5, focal_y=0.5)(asset)


class TestPillowRoundCorners:
    @pytest.fixture(name='processor', scope='class')
    def pillow_processor(self):
        return madam.image.PillowProcessor()

    def test_round_corners_preserves_dimensions(self, processor):
        asset = _solid_png_asset((200, 200, 200))
        result = processor.round_corners(radius=4)(asset)
        assert result.width == asset.width
        assert result.height == asset.height

    def test_round_corners_output_is_png(self, processor):
        asset = _solid_png_asset((200, 200, 200))
        result = processor.round_corners(radius=4)(asset)
        assert result.mime_type == 'image/png'

    def test_round_corners_output_has_alpha_channel(self, processor):
        asset = _solid_png_asset((200, 200, 200))
        result = processor.round_corners(radius=4)(asset)
        with PIL.Image.open(result.essence) as image:
            assert image.mode == 'RGBA'

    def test_round_corners_corner_pixels_are_transparent(self, processor):
        asset = _solid_png_asset((200, 200, 200), width=20, height=20)
        result = processor.round_corners(radius=8)(asset)
        with PIL.Image.open(result.essence) as image:
            # Very corner pixel should be transparent (alpha = 0)
            assert image.getpixel((0, 0))[3] == 0

    def test_round_corners_center_pixel_is_opaque(self, processor):
        asset = _solid_png_asset((200, 200, 200), width=20, height=20)
        result = processor.round_corners(radius=4)(asset)
        with PIL.Image.open(result.essence) as image:
            assert image.getpixel((10, 10))[3] == 255


class TestPillowApplyMask:
    @pytest.fixture(name='processor', scope='class')
    def pillow_processor(self):
        return madam.image.PillowProcessor()

    def _grey_png_asset(self, value):
        """Return a single-channel greyscale PNG Asset filled with `value`."""
        image = PIL.Image.new('L', (DEFAULT_WIDTH, DEFAULT_HEIGHT), value)
        essence = io.BytesIO()
        image.save(essence, 'PNG')
        essence.seek(0)
        return madam.core.Asset(
            essence,
            mime_type='image/png',
            width=DEFAULT_WIDTH,
            height=DEFAULT_HEIGHT,
            color_space='LUMA',
            depth=8,
            data_type='uint',
        )

    def test_apply_mask_preserves_dimensions(self, processor):
        base = _solid_png_asset((200, 200, 200))
        mask = self._grey_png_asset(128)
        result = processor.apply_mask(mask_asset=mask)(base)
        assert result.width == base.width
        assert result.height == base.height

    def test_apply_mask_output_is_png(self, processor):
        base = _solid_png_asset((200, 200, 200))
        mask = self._grey_png_asset(255)
        result = processor.apply_mask(mask_asset=mask)(base)
        assert result.mime_type == 'image/png'

    def test_apply_mask_output_has_alpha_channel(self, processor):
        base = _solid_png_asset((200, 200, 200))
        mask = self._grey_png_asset(255)
        result = processor.apply_mask(mask_asset=mask)(base)
        with PIL.Image.open(result.essence) as image:
            assert image.mode == 'RGBA'

    def test_apply_mask_white_mask_makes_image_fully_opaque(self, processor):
        base = _solid_png_asset((200, 200, 200))
        mask = self._grey_png_asset(255)
        result = processor.apply_mask(mask_asset=mask)(base)
        with PIL.Image.open(result.essence) as image:
            assert all(p[3] == 255 for p in image.get_flattened_data())

    def test_apply_mask_black_mask_makes_image_fully_transparent(self, processor):
        base = _solid_png_asset((200, 200, 200))
        mask = self._grey_png_asset(0)
        result = processor.apply_mask(mask_asset=mask)(base)
        with PIL.Image.open(result.essence) as image:
            assert all(p[3] == 0 for p in image.get_flattened_data())


class TestRenderText:
    def test_render_text_returns_asset(self):
        result = madam.image.render_text('Hello')
        assert isinstance(result, madam.core.Asset)

    def test_render_text_returns_png(self):
        result = madam.image.render_text('Hello')
        assert result.mime_type == 'image/png'

    def test_render_text_has_positive_dimensions(self):
        result = madam.image.render_text('Hello')
        assert result.width > 0
        assert result.height > 0

    def test_render_text_longer_text_produces_wider_image(self):
        short = madam.image.render_text('Hi')
        long_ = madam.image.render_text('Hello, World!')
        assert long_.width > short.width

    def test_render_text_larger_font_size_produces_taller_image(self):
        small = madam.image.render_text('Hi', font_size=12)
        large = madam.image.render_text('Hi', font_size=48)
        assert large.height > small.height

    def test_render_text_output_is_rgba(self):
        result = madam.image.render_text('Hi')
        with PIL.Image.open(result.essence) as image:
            assert image.mode == 'RGBA'


class TestPillowComposite:
    @pytest.fixture(name='processor', scope='class')
    def pillow_processor(self):
        return madam.image.PillowProcessor()

    def test_composite_preserves_base_dimensions(self, processor):
        base = _solid_png_asset((100, 100, 100), width=20, height=20)
        overlay = _solid_png_asset((255, 0, 0), width=5, height=5)
        result = processor.composite(overlay_asset=overlay)(base)
        assert result.width == base.width
        assert result.height == base.height

    def test_composite_preserves_mime_type(self, processor):
        base = _solid_png_asset((100, 100, 100), width=20, height=20)
        overlay = _solid_png_asset((255, 0, 0), width=5, height=5)
        result = processor.composite(overlay_asset=overlay)(base)
        assert result.mime_type == base.mime_type

    def test_composite_opacity_zero_leaves_base_unchanged(self, processor):
        base = _solid_png_asset((100, 100, 100), width=20, height=20)
        overlay = _solid_png_asset((255, 0, 0), width=20, height=20)
        result = processor.composite(overlay_asset=overlay, opacity=0.0)(base)
        with PIL.Image.open(result.essence) as r, PIL.Image.open(base.essence) as s:
            assert list(r.get_flattened_data()) == list(s.get_flattened_data())

    def test_composite_opacity_one_fills_overlay_region_with_overlay_color(self, processor):
        base = _solid_png_asset((0, 0, 0), width=20, height=20)
        overlay = _solid_png_asset((255, 0, 0), width=10, height=10)
        result = processor.composite(overlay_asset=overlay, x=0, y=0, opacity=1.0)(base)
        with PIL.Image.open(result.essence) as image:
            # Top-left corner should now be fully red
            assert image.getpixel((0, 0)) == (255, 0, 0)
            # Bottom-right corner (outside overlay) should still be black
            assert image.getpixel((19, 19)) == (0, 0, 0)

    def test_composite_gravity_positions_overlay(self, processor):
        base = _solid_png_asset((0, 0, 0), width=20, height=20)
        overlay = _solid_png_asset((255, 255, 255), width=4, height=4)
        result = processor.composite(overlay_asset=overlay, gravity='south_east', opacity=1.0)(base)
        with PIL.Image.open(result.essence) as image:
            # Bottom-right corner should be white (overlay placed there)
            assert image.getpixel((19, 19)) == (255, 255, 255)
            # Top-left should still be black
            assert image.getpixel((0, 0)) == (0, 0, 0)


class TestPillowFillBackground:
    @pytest.fixture(name='processor', scope='class')
    def pillow_processor(self):
        return madam.image.PillowProcessor()

    def test_fill_background_preserves_dimensions(self, processor):
        asset = _solid_png_asset((100, 100, 100))
        result = processor.fill_background(color=(255, 255, 255))(asset)
        assert result.width == asset.width
        assert result.height == asset.height

    def test_fill_background_preserves_mime_type(self, processor):
        asset = _solid_png_asset((100, 100, 100))
        result = processor.fill_background(color=(255, 255, 255))(asset)
        assert result.mime_type == asset.mime_type

    def test_fill_background_opaque_image_pixels_unchanged(self, processor):
        # An opaque RGB image has no alpha; pixels should be unchanged
        asset = _solid_png_asset((80, 120, 200))
        result = processor.fill_background(color=(255, 0, 0))(asset)
        with PIL.Image.open(result.essence) as r, PIL.Image.open(asset.essence) as s:
            assert list(r.get_flattened_data()) == list(s.get_flattened_data())

    def test_fill_background_removes_alpha_channel(self, processor):
        # Create a fully transparent RGBA image
        image = PIL.Image.new('RGBA', (DEFAULT_WIDTH, DEFAULT_HEIGHT), (0, 0, 0, 0))
        essence = io.BytesIO()
        image.save(essence, 'PNG')
        essence.seek(0)
        asset = madam.core.Asset(
            essence,
            mime_type='image/png',
            width=DEFAULT_WIDTH,
            height=DEFAULT_HEIGHT,
            color_space='RGBA',
            depth=8,
            data_type='uint',
        )
        result = processor.fill_background(color=(0, 255, 0))(asset)
        with PIL.Image.open(result.essence) as image:
            assert image.mode == 'RGB'

    def test_fill_background_transparent_area_shows_fill_color(self, processor):
        # Fully transparent RGBA image: after fill, all pixels == fill color
        image = PIL.Image.new('RGBA', (DEFAULT_WIDTH, DEFAULT_HEIGHT), (255, 0, 0, 0))
        essence = io.BytesIO()
        image.save(essence, 'PNG')
        essence.seek(0)
        asset = madam.core.Asset(
            essence,
            mime_type='image/png',
            width=DEFAULT_WIDTH,
            height=DEFAULT_HEIGHT,
            color_space='RGBA',
            depth=8,
            data_type='uint',
        )
        result = processor.fill_background(color=(0, 0, 255))(asset)
        with PIL.Image.open(result.essence) as image:
            assert all(p == (0, 0, 255) for p in image.get_flattened_data())


class TestPillowPad:
    @pytest.fixture(name='processor', scope='class')
    def pillow_processor(self):
        return madam.image.PillowProcessor()

    def test_pad_sets_output_to_requested_dimensions(self, processor):
        asset = _solid_png_asset((100, 100, 100), width=10, height=10)
        result = processor.pad(width=20, height=30)(asset)
        assert result.width == 20
        assert result.height == 30

    def test_pad_preserves_mime_type(self, processor):
        asset = _solid_png_asset((100, 100, 100), width=10, height=10)
        result = processor.pad(width=20, height=20)(asset)
        assert result.mime_type == asset.mime_type

    def test_pad_fill_color_appears_in_added_area(self, processor):
        # Source is 4x4 red; pad to 8x4 with blue fill at north_west gravity
        asset = _solid_png_asset((255, 0, 0), width=4, height=4)
        result = processor.pad(width=8, height=4, color=(0, 0, 255), gravity='north_west')(asset)
        with PIL.Image.open(result.essence) as image:
            # Right half should be blue (fill colour)
            assert image.getpixel((7, 2)) == (0, 0, 255)

    @pytest.mark.parametrize(
        'gravity,expected_origin',
        [
            ('north_west', (0, 0)),
            ('north_east', (10, 0)),
            ('south_west', (0, 10)),
            ('south_east', (10, 10)),
            ('center', (5, 5)),
        ],
    )
    def test_pad_gravity_positions_source_correctly(self, processor, gravity, expected_origin):
        # Source: 10x10 white; canvas: 20x20 black
        asset = _solid_png_asset((255, 255, 255), width=10, height=10)
        result = processor.pad(width=20, height=20, color=(0, 0, 0), gravity=gravity)(asset)
        with PIL.Image.open(result.essence) as image:
            ox, oy = expected_origin
            # The source pixel at (0,0) should appear at the expected origin
            assert image.getpixel((ox, oy)) == (255, 255, 255)

    def test_pad_raises_when_canvas_smaller_than_source(self, processor):
        asset = _solid_png_asset((100, 100, 100), width=20, height=20)
        with pytest.raises(OperatorError):
            processor.pad(width=10, height=10)(asset)


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
            essence,
            mime_type='image/png',
            width=DEFAULT_WIDTH,
            height=DEFAULT_HEIGHT,
            color_space='RGB',
            depth=8,
            data_type='uint',
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
            essence,
            mime_type='image/png',
            width=DEFAULT_WIDTH,
            height=DEFAULT_HEIGHT,
            color_space='RGB',
            depth=8,
            data_type='uint',
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


class TestPillowHEIF:
    """Tests for HEIC/HEIF support via the pillow-heif plugin."""

    @pytest.fixture(name='processor', scope='class')
    def pillow_processor(self):
        pytest.importorskip('pillow_heif')
        return madam.image.PillowProcessor()

    @pytest.fixture(scope='class')
    def heic_asset(self, processor):
        """Create a synthetic HEIC asset for testing."""
        image = PIL.Image.new('RGB', (DEFAULT_WIDTH, DEFAULT_HEIGHT), (200, 100, 50))
        buf = io.BytesIO()
        image.save(buf, format='HEIF')
        buf.seek(0)
        return processor.read(buf)

    def test_read_heic_returns_correct_mime_type(self, heic_asset):
        assert heic_asset.mime_type == 'image/heic'

    def test_read_heic_returns_correct_dimensions(self, heic_asset):
        assert heic_asset.width == DEFAULT_WIDTH
        assert heic_asset.height == DEFAULT_HEIGHT

    def test_can_read_heic(self, processor):
        image = PIL.Image.new('RGB', (DEFAULT_WIDTH, DEFAULT_HEIGHT), (200, 100, 50))
        buf = io.BytesIO()
        image.save(buf, format='HEIF')
        buf.seek(0)
        assert processor.can_read(buf)

    def test_convert_png_to_heic(self, processor):
        png_asset = _solid_png_asset((200, 100, 50))
        convert_op = processor.convert(mime_type='image/heic')
        heic_asset = convert_op(png_asset)
        assert heic_asset.mime_type == 'image/heic'
        assert heic_asset.width == DEFAULT_WIDTH
        assert heic_asset.height == DEFAULT_HEIGHT

    def test_convert_heic_to_png(self, processor, heic_asset):
        convert_op = processor.convert(mime_type='image/png')
        png_asset = convert_op(heic_asset)
        assert png_asset.mime_type == 'image/png'
        assert png_asset.width == DEFAULT_WIDTH
        assert png_asset.height == DEFAULT_HEIGHT


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


class TestPillowAnimatedFrames:
    """Tests for animated GIF/WebP frame_count metadata and extract_frame operator."""

    _FRAME_COUNT = 3

    @pytest.fixture(name='processor', scope='class')
    def pillow_processor(self):
        return madam.image.PillowProcessor()

    @pytest.fixture(name='animated_gif_asset', scope='class')
    def animated_gif_asset(self, processor):
        """Create a synthetic animated GIF with _FRAME_COUNT distinct frames."""
        # Use 'L' (grayscale) mode: 'P' frames with an uninitialized palette
        # are indistinguishable to the GIF encoder and collapse to 1 frame.
        frames = [
            PIL.Image.new('L', (DEFAULT_WIDTH, DEFAULT_HEIGHT), color=i * 80)
            for i in range(TestPillowAnimatedFrames._FRAME_COUNT)
        ]
        buf = io.BytesIO()
        frames[0].save(buf, format='GIF', save_all=True, append_images=frames[1:], loop=0)
        buf.seek(0)
        return processor.read(buf)

    @pytest.fixture(name='animated_webp_asset', scope='class')
    def animated_webp_asset(self, processor):
        """Create a synthetic animated WebP with _FRAME_COUNT distinct frames."""
        frames = [
            PIL.Image.new('RGB', (DEFAULT_WIDTH, DEFAULT_HEIGHT), color=(i * 80, 0, 0))
            for i in range(TestPillowAnimatedFrames._FRAME_COUNT)
        ]
        buf = io.BytesIO()
        frames[0].save(buf, format='WEBP', save_all=True, append_images=frames[1:])
        buf.seek(0)
        return processor.read(buf)

    def test_read_animated_gif_includes_frame_count(self, animated_gif_asset):
        assert animated_gif_asset.frame_count == TestPillowAnimatedFrames._FRAME_COUNT

    def test_read_animated_webp_includes_frame_count(self, animated_webp_asset):
        assert animated_webp_asset.frame_count == TestPillowAnimatedFrames._FRAME_COUNT

    def test_read_static_gif_has_no_frame_count(self, processor):
        image = PIL.Image.new('P', (DEFAULT_WIDTH, DEFAULT_HEIGHT), color=0)
        buf = io.BytesIO()
        image.save(buf, format='GIF')
        buf.seek(0)
        asset = processor.read(buf)
        assert not hasattr(asset, 'frame_count')

    def test_extract_frame_returns_image_asset(self, processor, animated_gif_asset):
        frame_asset = processor.extract_frame(frame=0)(animated_gif_asset)
        assert isinstance(frame_asset, madam.core.Asset)

    def test_extract_frame_returns_correct_mime_type(self, processor, animated_gif_asset):
        frame_asset = processor.extract_frame(frame=0)(animated_gif_asset)
        assert frame_asset.mime_type == 'image/gif'

    def test_extract_frame_has_correct_dimensions(self, processor, animated_gif_asset):
        frame_asset = processor.extract_frame(frame=0)(animated_gif_asset)
        assert frame_asset.width == DEFAULT_WIDTH
        assert frame_asset.height == DEFAULT_HEIGHT

    def test_extract_frame_zero_and_last_differ(self, processor, animated_gif_asset):
        frame_0 = processor.extract_frame(frame=0)(animated_gif_asset)
        frame_last = processor.extract_frame(frame=TestPillowAnimatedFrames._FRAME_COUNT - 1)(animated_gif_asset)
        assert frame_0.essence.read() != frame_last.essence.read()

    def test_extract_frame_raises_for_out_of_range_index(self, processor, animated_gif_asset):
        with pytest.raises(OperatorError):
            processor.extract_frame(frame=TestPillowAnimatedFrames._FRAME_COUNT)(animated_gif_asset)

    def test_extract_frame_webp_returns_png(self, processor, animated_webp_asset):
        frame_asset = processor.extract_frame(frame=0)(animated_webp_asset)
        assert frame_asset.mime_type == 'image/webp'


class TestPillowOptimizeQuality:
    @pytest.fixture(name='processor', scope='class')
    def pillow_processor(self):
        pytest.importorskip('ssimulacra2')
        return madam.image.PillowProcessor()

    @pytest.fixture(name='source_asset', scope='class')
    def source_asset_fixture(self):
        # 256×256 RGB gradient PNG (lossless) — varied content for SSIMULACRA2 measurement.
        image = PIL.Image.new('RGB', (256, 256))
        pixels = image.load()
        for x in range(256):
            for y in range(256):
                pixels[x, y] = (x, y, (x + y) % 256)
        buf = io.BytesIO()
        image.save(buf, 'PNG')
        buf.seek(0)
        return madam.image.PillowProcessor().read(buf)

    def test_optimize_quality_returns_asset(self, processor, source_asset):
        result = processor.optimize_quality(min_ssim_score=80.0, mime_type='image/jpeg')(source_asset)

        assert isinstance(result, madam.core.Asset)

    def test_optimize_quality_preserves_dimensions(self, processor, source_asset):
        result = processor.optimize_quality(min_ssim_score=80.0, mime_type='image/jpeg')(source_asset)

        assert result.width == source_asset.width
        assert result.height == source_asset.height

    def test_optimize_quality_produces_jpeg(self, processor, source_asset):
        result = processor.optimize_quality(min_ssim_score=80.0, mime_type='image/jpeg')(source_asset)

        assert result.mime_type == 'image/jpeg'

    def test_optimize_quality_produces_webp(self, processor, source_asset):
        result = processor.optimize_quality(min_ssim_score=80.0, mime_type='image/webp')(source_asset)

        assert result.mime_type == 'image/webp'

    def test_optimize_quality_satisfies_ssim_score(self, processor, source_asset):
        min_score = 80.0
        result = processor.optimize_quality(min_ssim_score=min_score, mime_type='image/jpeg')(source_asset)

        source_asset.essence.seek(0)
        original_img = PIL.Image.open(source_asset.essence).convert('RGB')
        result_img = PIL.Image.open(result.essence).convert('RGB')
        score = madam.image._ssimulacra2_score(original_img, result_img)
        assert score >= min_score

    def test_optimize_quality_higher_score_threshold_yields_larger_file(self, processor, source_asset):
        # Higher minimum SSIM score → higher encoding quality → larger output file.
        strict = processor.optimize_quality(min_ssim_score=90.0, mime_type='image/jpeg')(source_asset)
        lenient = processor.optimize_quality(min_ssim_score=70.0, mime_type='image/jpeg')(source_asset)

        assert len(strict.essence.read()) >= len(lenient.essence.read())

    def test_optimize_quality_raises_when_target_format_is_lossless(self, processor, source_asset):
        # Source is PNG; no mime_type → target defaults to image/png → OperatorError.
        with pytest.raises(OperatorError):
            processor.optimize_quality(min_ssim_score=80.0)(source_asset)


def _gradient_png_asset(width=256, height=256) -> madam.core.Asset:
    """Return a lossless PNG Asset filled with a color gradient."""
    image = PIL.Image.new('RGB', (width, height))
    pixels = image.load()
    for x in range(width):
        for y in range(height):
            pixels[x, y] = (x % 256, y % 256, (x + y) % 256)
    buf = io.BytesIO()
    image.save(buf, 'PNG')
    buf.seek(0)
    return madam.image.PillowProcessor().read(buf)


class TestExtractPalette:
    def test_extract_palette_returns_list(self):
        asset = _solid_png_asset((255, 0, 0))

        result = madam.image.extract_palette(asset)

        assert isinstance(result, list)

    def test_extract_palette_returns_rgb_tuples(self):
        asset = _solid_png_asset((0, 128, 64))

        result = madam.image.extract_palette(asset)

        for entry in result:
            assert isinstance(entry, tuple)
            assert len(entry) == 3
            assert all(isinstance(c, int) for c in entry)

    def test_extract_palette_solid_color_first_entry_matches_color(self):
        color = (200, 100, 50)
        asset = _solid_png_asset(color)

        result = madam.image.extract_palette(asset, count=5)

        assert result[0] == color

    def test_extract_palette_returns_count_entries_for_rich_image(self):
        # A gradient has many unique colors; quantizing to 5 should yield 5 entries.
        asset = _gradient_png_asset()

        result = madam.image.extract_palette(asset, count=5)

        assert len(result) == 5

    def test_extract_palette_count_one_returns_dominant_color(self):
        color = (10, 20, 30)
        asset = _solid_png_asset(color)

        result = madam.image.extract_palette(asset, count=1)

        assert len(result) == 1
        assert result[0] == color

    def test_extract_palette_most_frequent_color_is_first(self):
        # Build an image: large red region and a small blue pixel.
        image = PIL.Image.new('RGB', (DEFAULT_WIDTH, DEFAULT_HEIGHT), (255, 0, 0))
        image.putpixel((0, 0), (0, 0, 255))
        buf = io.BytesIO()
        image.save(buf, 'PNG')
        buf.seek(0)
        asset = madam.core.Asset(
            buf,
            mime_type='image/png',
            width=DEFAULT_WIDTH,
            height=DEFAULT_HEIGHT,
            color_space='RGB',
            depth=8,
            data_type='uint',
        )

        result = madam.image.extract_palette(asset, count=2)

        assert result[0] == (255, 0, 0)


def _jpeg_with_icc_profile() -> madam.core.Asset:
    """Return a small JPEG Asset with an embedded sRGB ICC profile."""
    icc_profile = PIL.ImageCms.ImageCmsProfile(PIL.ImageCms.createProfile('sRGB')).tobytes()
    image = PIL.Image.new('RGB', (8, 8), (100, 150, 200))
    buf = io.BytesIO()
    image.save(buf, 'JPEG', icc_profile=icc_profile, quality=95)
    buf.seek(0)
    return madam.core.Asset(
        buf, mime_type='image/jpeg', width=8, height=8, color_space='RGB', depth=8, data_type='uint'
    )


class TestPillowIccProfile:
    @pytest.fixture(name='processor', scope='class')
    def pillow_processor(self):
        return madam.image.PillowProcessor()

    @pytest.fixture(name='jpeg_with_icc', scope='class')
    def jpeg_with_icc_fixture(self):
        return _jpeg_with_icc_profile()

    def test_read_jpeg_with_icc_profile_stores_profile_in_metadata(self, processor):
        asset = _jpeg_with_icc_profile()

        read_asset = processor.read(asset.essence)

        assert hasattr(read_asset, 'icc_profile') or 'icc_profile' in read_asset.metadata
        assert read_asset.icc_profile is not None
        assert isinstance(read_asset.icc_profile, bytes)
        assert len(read_asset.icc_profile) > 0

    def test_read_jpeg_without_icc_profile_has_no_icc_profile(self, processor):
        image = PIL.Image.new('RGB', (8, 8), (100, 150, 200))
        buf = io.BytesIO()
        image.save(buf, 'JPEG', quality=95)
        buf.seek(0)

        read_asset = processor.read(buf)

        assert read_asset.metadata.get('icc_profile') is None

    def test_convert_jpeg_to_png_preserves_icc_profile(self, processor, jpeg_with_icc):
        read_asset = processor.read(jpeg_with_icc.essence)
        convert_op = processor.convert(mime_type='image/png')

        converted = convert_op(read_asset)

        assert converted.icc_profile is not None
        assert isinstance(converted.icc_profile, bytes)
        assert len(converted.icc_profile) > 0

    def test_resize_preserves_icc_profile(self, processor, jpeg_with_icc):
        read_asset = processor.read(jpeg_with_icc.essence)
        resize_op = processor.resize(width=4, height=4)

        resized = resize_op(read_asset)

        assert resized.metadata.get('icc_profile') is not None
        assert isinstance(resized.metadata.get('icc_profile'), bytes)


class TestPillowContext:
    def test_pillow_context_is_importable(self):
        from madam.image import PillowContext  # noqa: F401

    def test_pillow_context_holds_image_and_mime_type(self):
        import PIL.Image
        from madam.image import PillowContext, PillowProcessor

        proc = PillowProcessor()
        img = PIL.Image.new('RGB', (10, 8), (255, 0, 0))
        ctx = PillowContext(proc, img, 'image/png')

        assert ctx.image is img
        assert ctx.mime_type == 'image/png'

    def test_pillow_context_processor_returns_owning_processor(self):
        import PIL.Image
        from madam.image import PillowContext, PillowProcessor

        proc = PillowProcessor()
        img = PIL.Image.new('RGB', (10, 8))
        ctx = PillowContext(proc, img, 'image/png')

        assert ctx.processor is proc

    def test_pillow_context_materialize_returns_asset_with_correct_mime_type(self):
        import PIL.Image
        from madam.image import PillowContext, PillowProcessor

        proc = PillowProcessor()
        img = PIL.Image.new('RGB', (10, 8), (0, 128, 0))
        ctx = PillowContext(proc, img, 'image/png')

        asset = ctx.materialize()

        assert asset.mime_type == 'image/png'

    def test_pillow_context_materialize_returns_asset_with_correct_dimensions(self):
        import PIL.Image
        from madam.image import PillowContext, PillowProcessor

        proc = PillowProcessor()
        img = PIL.Image.new('RGB', (10, 8))
        ctx = PillowContext(proc, img, 'image/jpeg')

        asset = ctx.materialize()

        assert asset.width == 10
        assert asset.height == 8

    def test_pillow_context_is_processing_context_subclass(self):
        from madam.core import ProcessingContext
        from madam.image import PillowContext

        assert issubclass(PillowContext, ProcessingContext)


class TestPillowDeferredExecution:
    @pytest.fixture(name='processor')
    def pillow_processor(self):
        return madam.image.PillowProcessor()

    def test_pipeline_calls_pil_open_once_for_chained_operators(self, processor):
        """Two Pillow operators in a Pipeline must decode the image only once."""
        import unittest.mock
        from madam.core import Pipeline

        jpeg_asset = get_jpeg_image_asset(width=64, height=64)
        resize_op = processor.resize(width=32, height=32)
        crop_op = processor.crop(width=16, height=16, x=0, y=0)
        pipeline = Pipeline()
        pipeline.add(resize_op)
        pipeline.add(crop_op)

        original_open = PIL.Image.open
        open_calls = []

        def counting_open(fp, *args, **kwargs):
            open_calls.append(1)
            return original_open(fp, *args, **kwargs)

        with unittest.mock.patch('PIL.Image.open', side_effect=counting_open):
            result = list(pipeline.process(jpeg_asset))

        assert len(open_calls) == 1, f'Expected 1 PIL.Image.open call, got {len(open_calls)}'
        assert result[0].width == 16
        assert result[0].height == 16

    def test_pipeline_deferred_result_has_correct_mime_type(self, processor):
        from madam.core import Pipeline

        jpeg_asset = get_jpeg_image_asset(width=32, height=32)
        resize_op = processor.resize(width=16, height=16)
        pipeline = Pipeline()
        pipeline.add(resize_op)

        result = list(pipeline.process(jpeg_asset))

        assert result[0].mime_type == 'image/jpeg'


class TestPillowDeferredICC:
    """ICC profile propagation through PillowContext (regression guard)."""

    @pytest.fixture(name='processor')
    def pillow_processor(self):
        return madam.image.PillowProcessor()

    def test_icc_profile_preserved_through_deferred_pipeline(self, processor):
        from madam.core import Pipeline

        # Build a JPEG with an embedded ICC profile.
        icc_bytes = b'\x00\x01' * 50  # minimal fake ICC
        img = PIL.Image.new('RGB', (64, 64), (200, 100, 50))
        buf = io.BytesIO()
        img.save(buf, 'JPEG', icc_profile=icc_bytes, quality=90)
        buf.seek(0)
        asset_with_icc = processor.read(buf)

        resize_op = processor.resize(width=32, height=32)
        crop_op = processor.crop(width=16, height=16, x=0, y=0)
        pipeline = Pipeline()
        pipeline.add(resize_op)
        pipeline.add(crop_op)

        result = list(pipeline.process(asset_with_icc))

        assert result[0].metadata.get('icc_profile') is not None


class TestPillowDeferredFormatConversion:
    """Format conversion inside a Pillow run without intermediate encode."""

    @pytest.fixture(name='processor')
    def pillow_processor(self):
        return madam.image.PillowProcessor()

    def test_resize_then_convert_calls_pil_open_once(self, processor):
        import unittest.mock
        from madam.core import Pipeline

        png_img = PIL.Image.new('RGB', (64, 64), (0, 128, 255))
        buf = io.BytesIO()
        png_img.save(buf, 'PNG')
        buf.seek(0)
        png_asset = processor.read(buf)

        resize_op = processor.resize(width=32, height=32)
        convert_op = processor.convert(mime_type='image/jpeg')
        pipeline = Pipeline()
        pipeline.add(resize_op)
        pipeline.add(convert_op)

        original_open = PIL.Image.open
        open_calls = []

        def counting_open(fp, *args, **kwargs):
            open_calls.append(1)
            return original_open(fp, *args, **kwargs)

        with unittest.mock.patch('PIL.Image.open', side_effect=counting_open):
            result = list(pipeline.process(png_asset))

        assert len(open_calls) == 1
        assert result[0].mime_type == 'image/jpeg'
        assert result[0].width == 32
        assert result[0].height == 32
