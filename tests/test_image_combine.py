import io

import PIL.Image
import pytest

import madam.core


def _make_solid_asset(color, mime_type='image/png', size=(32, 32)):
    """Create an Asset with a solid-color image for combine() tests."""
    mode = 'RGB' if len(color) == 3 else 'RGBA'
    img = PIL.Image.new(mode, size, color)
    buf = io.BytesIO()
    fmt = 'PNG' if mime_type == 'image/png' else 'JPEG'
    img.save(buf, fmt)
    buf.seek(0)
    return madam.core.Asset(buf, mime_type=mime_type, width=size[0], height=size[1])


class TestCombineAnimated:
    def test_combine_gif_returns_asset(self, jpeg_image_asset, png_image_asset_rgb):
        from madam.image import combine

        result = combine([jpeg_image_asset, png_image_asset_rgb], 'image/gif')
        assert isinstance(result, madam.core.Asset)

    def test_combine_gif_mime_type(self, jpeg_image_asset, png_image_asset_rgb):
        from madam.image import combine

        result = combine([jpeg_image_asset, png_image_asset_rgb], 'image/gif')
        assert result.mime_type == 'image/gif'

    def test_combine_gif_frame_count(self, jpeg_image_asset, png_image_asset_rgb):
        from madam.image import combine

        result = combine([jpeg_image_asset, png_image_asset_rgb], 'image/gif')
        assert result.frame_count == 2

    def test_combine_webp_returns_asset(self, jpeg_image_asset, png_image_asset_rgb):
        from madam.image import combine

        result = combine([jpeg_image_asset, png_image_asset_rgb], 'image/webp')
        assert isinstance(result, madam.core.Asset)

    def test_combine_webp_mime_type(self, jpeg_image_asset, png_image_asset_rgb):
        from madam.image import combine

        result = combine([jpeg_image_asset, png_image_asset_rgb], 'image/webp')
        assert result.mime_type == 'image/webp'

    def test_combine_webp_frame_count(self):
        # Use visually distinct solid-color frames so the WebP encoder
        # does not collapse them into a static (single-frame) image.
        from madam.image import combine

        red = _make_solid_asset((255, 0, 0))
        blue = _make_solid_asset((0, 0, 255))
        result = combine([red, blue], 'image/webp')
        assert result.frame_count == 2

    def test_combine_default_duration_is_100ms(self, jpeg_image_asset, png_image_asset_rgb):
        from madam.image import combine

        result = combine([jpeg_image_asset, png_image_asset_rgb], 'image/gif')
        img = PIL.Image.open(result.essence)
        img.seek(0)
        assert img.info.get('duration') == 100

    def test_combine_custom_duration(self, jpeg_image_asset, png_image_asset_rgb):
        from madam.image import combine

        result = combine([jpeg_image_asset, png_image_asset_rgb], 'image/gif', duration=200)
        img = PIL.Image.open(result.essence)
        img.seek(0)
        assert img.info.get('duration') == 200

    def test_combine_empty_raises_value_error(self):
        from madam.image import combine

        with pytest.raises(ValueError):
            combine([], 'image/gif')

    def test_combine_unsupported_mime_type_raises(self, jpeg_image_asset):
        from madam.image import combine

        with pytest.raises(madam.core.UnsupportedFormatError):
            combine([jpeg_image_asset], 'image/png')

    def test_combine_accepts_generator(self):
        from madam.image import combine

        red = _make_solid_asset((255, 0, 0))
        blue = _make_solid_asset((0, 0, 255))

        def gen():
            yield red
            yield blue

        result = combine(gen(), 'image/gif')
        assert result.frame_count == 2

    def test_combine_rgba_frames_in_gif(self, jpeg_image_asset, png_image_asset_rgb_alpha):
        from madam.image import combine

        result = combine([jpeg_image_asset, png_image_asset_rgb_alpha], 'image/gif')
        assert result.mime_type == 'image/gif'

    def test_combine_palette_frames_in_gif(self, jpeg_image_asset, png_image_asset_palette):
        from madam.image import combine

        result = combine([jpeg_image_asset, png_image_asset_palette], 'image/gif')
        assert result.mime_type == 'image/gif'
