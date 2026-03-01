import io
import math
import warnings
from collections.abc import Callable, Mapping
from enum import Enum
from typing import IO, Any

import PIL.ExifTags
import PIL.Image
import PIL.ImageEnhance
import PIL.ImageFilter
import PIL.ImageOps
from bidict import bidict

from madam.core import Asset, OperatorError, Processor, operator
from madam.mime import MimeType

_VALID_FORMAT_CONFIG_KEYS: dict[MimeType, frozenset[str]] = {
    MimeType('image/avif'): frozenset({'quality', 'speed'}),
    MimeType('image/jpeg'): frozenset({'quality', 'progressive'}),
    MimeType('image/png'): frozenset({'optimize', 'zopfli', 'zopfli_strategies'}),
    MimeType('image/tiff'): frozenset({'compression'}),
    MimeType('image/webp'): frozenset({'quality', 'method'}),
    MimeType('image/gif'): frozenset({'optimize'}),
}


def _resolve_gravity(
    canvas_width: int,
    canvas_height: int,
    source_width: int,
    source_height: int,
    gravity: str,
) -> tuple[int, int]:
    """
    Return the ``(x, y)`` top-left offset at which to place a source image of
    ``(source_width, source_height)`` inside a canvas of
    ``(canvas_width, canvas_height)`` according to *gravity*.

    Valid gravity values: ``'north_west'``, ``'north'``, ``'north_east'``,
    ``'west'``, ``'center'``, ``'east'``, ``'south_west'``, ``'south'``,
    ``'south_east'``.
    """
    h_offsets = {
        'west': 0,
        'center': (canvas_width - source_width) // 2,
        'east': canvas_width - source_width,
    }
    v_offsets = {
        'north': 0,
        'center': (canvas_height - source_height) // 2,
        'south': canvas_height - source_height,
    }
    gravity_map: dict[str, tuple[int, int]] = {
        'north_west': (h_offsets['west'],   v_offsets['north']),
        'north':      (h_offsets['center'], v_offsets['north']),
        'north_east': (h_offsets['east'],   v_offsets['north']),
        'west':       (h_offsets['west'],   v_offsets['center']),
        'center':     (h_offsets['center'], v_offsets['center']),
        'east':       (h_offsets['east'],   v_offsets['center']),
        'south_west': (h_offsets['west'],   v_offsets['south']),
        'south':      (h_offsets['center'], v_offsets['south']),
        'south_east': (h_offsets['east'],   v_offsets['south']),
    }
    if gravity not in gravity_map:
        raise ValueError(f'Unknown gravity: {gravity!r}')
    return gravity_map[gravity]


class ResizeMode(Enum):
    """
    Represents a behavior for image resize operations.
    """

    #: Image exactly matches the specified dimensions
    EXACT = 0
    #: Image is resized to fit completely into the specified dimensions
    FIT = 1
    #: Image is resized to completely fill the specified dimensions
    FILL = 2


class FlipOrientation(Enum):
    """
    Represents an axis for image flip operations.
    """

    #: Horizontal axis
    HORIZONTAL = 0
    #: Vertical axis
    VERTICAL = 1


class PillowProcessor(Processor):
    """
    Represents a processor that uses Pillow as a backend.
    """

    __mime_type_to_pillow_type = bidict(
        {
            MimeType('image/avif'): 'AVIF',
            MimeType('image/bmp'): 'BMP',
            MimeType('image/gif'): 'GIF',
            MimeType('image/jpeg'): 'JPEG',
            MimeType('image/png'): 'PNG',
            MimeType('image/tiff'): 'TIFF',
            MimeType('image/webp'): 'WEBP',
        }
    )

    __format_defaults = {
        MimeType('image/avif'): dict(
            quality=80,
            speed=6,
        ),
        MimeType('image/gif'): dict(
            optimize=True,
        ),
        MimeType('image/jpeg'): dict(
            optimize=True,
            progressive=True,
            quality=80,
        ),
        MimeType('image/png'): dict(
            optimize=True,
        ),
        MimeType('image/tiff'): dict(
            compression='tiff_deflate',
        ),
        MimeType('image/webp'): dict(
            method=6,
            quality=80,
        ),
    }

    __pillow_mode_to_color_mode = bidict(
        {
            '1': ('LUMA', 1, 'uint'),
            'L': ('LUMA', 8, 'uint'),
            'LA': ('LUMAA', 8, 'uint'),
            'P': ('PALETTE', 8, 'uint'),
            'RGB': ('RGB', 8, 'uint'),
            'RGBA': ('RGBA', 8, 'uint'),
            'RGBX': ('RGBX', 8, 'uint'),
            'CMYK': ('CMYK', 8, 'uint'),
            'YCbCr': ('YCbCr', 8, 'uint'),
            'LAB': ('LAB', 8, 'uint'),
            'HSV': ('HSV', 8, 'uint'),
            'I;16': ('LUMA', 16, 'uint'),
            'I': ('LUMA', 32, 'uint'),
            'F': ('LUMA', 32, 'float'),
        }
    )

    def __init__(self, config: Mapping[str, Any] | None = None) -> None:
        """
        Initializes a new `PillowProcessor`.

        :param config: Mapping with settings.
        """
        super().__init__(config)

    def read(self, file: IO) -> Asset:
        with PIL.Image.open(file) as image:
            mime_type = PillowProcessor.__mime_type_to_pillow_type.inv[image.format]
            color_space, bit_depth, data_type = PillowProcessor.__pillow_mode_to_color_mode[image.mode]
            metadata = dict(
                mime_type=str(mime_type),
                width=image.width,
                height=image.height,
                color_space=color_space,
                depth=bit_depth,
                data_type=data_type,
            )
        file.seek(0)
        asset = Asset(file, **metadata)
        return asset

    def can_read(self, file: IO) -> bool:
        try:
            PIL.Image.open(file)
            return True
        except IOError:
            return False
        finally:
            file.seek(0)

    @operator
    def resize(self, asset: Asset, width: int, height: int, mode: ResizeMode = ResizeMode.EXACT) -> Asset:
        """
        Creates a new Asset whose essence is resized according to the specified parameters.

        :param asset: Asset to be resized
        :type asset: Asset
        :param width: target width
        :type width: int
        :param height: target height
        :type height: int
        :param mode: resize behavior
        :type mode: ResizeMode
        :return: Asset with resized essence
        :rtype: Asset
        """
        mime_type = MimeType(asset.mime_type)
        with PIL.Image.open(asset.essence) as image:
            if mode == ResizeMode.EXACT:
                resized_width = width
                resized_height = height
            else:
                aspect = asset.width / asset.height
                aspect_target = width / height
                if (
                    mode == ResizeMode.FIT
                    and aspect >= aspect_target
                    or mode == ResizeMode.FILL
                    and aspect <= aspect_target
                ):
                    resize_factor = width / image.width
                else:
                    resize_factor = height / image.height
                resized_width = max(1, round(resize_factor * image.width))
                resized_height = max(1, round(resize_factor * image.height))
            # Pillow supports resampling only for 8-bit images
            resampling_method = PIL.Image.Resampling.LANCZOS if asset.depth == 8 else PIL.Image.Resampling.NEAREST
            resized_image = image.resize((resized_width, resized_height), resample=resampling_method)
        with resized_image:
            resized_asset = self._image_to_asset(resized_image, mime_type=mime_type)
        return resized_asset

    def _image_to_asset(self, image: PIL.Image.Image, mime_type: MimeType | str) -> Asset:
        """
        Converts an PIL image to a MADAM asset. The conversion can also include
        a change in file type.

        :param image: PIL image
        :type image: PIL.Image.Image
        :param mime_type: MIME type of the target asset
        :type mime_type: MimeType or str
        :return: MADAM asset with the specified MIME type
        :rtype: Asset
        """
        mime_type = MimeType(mime_type)

        pil_format = PillowProcessor.__mime_type_to_pillow_type[mime_type]
        pil_options = dict(PillowProcessor.__format_defaults.get(mime_type, {}))
        format_config = dict(self.config.get(mime_type.type or '', {}))
        format_config.update(self.config.get(str(mime_type), {}))

        valid_keys = _VALID_FORMAT_CONFIG_KEYS.get(mime_type, frozenset())
        for key in format_config:
            if key not in valid_keys:
                warnings.warn(
                    f'Unknown config key {key!r} for format {mime_type}. '
                    f'Valid keys: {sorted(valid_keys)}',
                    UserWarning,
                    stacklevel=4,
                )

        image_buffer = io.BytesIO()

        if mime_type == MimeType('image/png') and image.mode != 'P':
            use_zopfli = format_config.get('zopfli', False)
            if use_zopfli:
                import zopfli

                zopfli_png = zopfli.ZopfliPNG()
                # Convert 16-bit per channel images to 8-bit per channel
                zopfli_png.lossy_8bit = False
                # Allow altering hidden colors of fully transparent pixels
                zopfli_png.lossy_transparent = True
                # Use all available optimization strategies
                zopfli_png.filter_strategies = format_config.get('zopfli_strategies', '0me')

                pil_options.pop('optimize', False)
                essence = io.BytesIO()
                image.save(essence, 'PNG', optimize=False, **pil_options)
                essence.seek(0)
                optimized_data = zopfli_png.optimize(essence.read())
                image_buffer.write(optimized_data)
            else:
                image.save(image_buffer, pil_format, **pil_options)
        elif mime_type == MimeType('image/jpeg'):
            pil_options['progressive'] = int(format_config.get('progressive', pil_options['progressive']))
            pil_options['quality'] = int(format_config.get('quality', pil_options['quality']))
            image.save(image_buffer, pil_format, **pil_options)
        elif mime_type == MimeType('image/tiff') and image.mode == 'P':
            pil_options.pop('compression', '')
            image.save(image_buffer, pil_format, **pil_options)
        elif mime_type == MimeType('image/avif'):
            pil_options['quality'] = int(format_config.get('quality', pil_options['quality']))
            pil_options['speed'] = int(format_config.get('speed', pil_options['speed']))
            image.save(image_buffer, pil_format, **pil_options)
        elif mime_type == MimeType('image/webp'):
            pil_options['method'] = int(format_config.get('method', pil_options['method']))
            pil_options['quality'] = int(format_config.get('quality', pil_options['quality']))
            image.save(image_buffer, pil_format, **pil_options)
        else:
            image.save(image_buffer, pil_format, **pil_options)

        image_buffer.seek(0)

        asset = self.read(image_buffer)
        return asset

    def _rotate(self, asset: Asset, rotation: PIL.Image.Transpose) -> Asset:
        """
        Creates a new image asset from specified asset whose essence is rotated
        by the specified rotation.

        :param asset: Image asset to be rotated
        :type asset: Asset
        :param rotation: One of `PIL.Image.FLIP_LEFT_RIGHT`,
        `PIL.Image.FLIP_TOP_BOTTOM`, `PIL.Image.ROTATE_90`,
        `PIL.Image.ROTATE_180`, `PIL.Image.ROTATE_270`, or
        `PIL.Image.TRANSPOSE`
        :return: New image asset with rotated essence
        :rtype: Asset
        """
        mime_type = MimeType(asset.mime_type)
        with PIL.Image.open(asset.essence) as image:
            transposed_image = image.transpose(rotation)
        with transposed_image:
            transposed_asset = self._image_to_asset(transposed_image, mime_type=mime_type)
        return transposed_asset

    @operator
    def transpose(self, asset: Asset) -> Asset:
        """
        Creates a new image asset whose essence is the transpose of the
        specified asset's essence.

        :param asset: Image asset whose essence is to be transposed
        :type asset: Asset
        :return: New image asset with transposed essence
        :rtype: Asset
        """
        return self._rotate(asset, PIL.Image.Transpose.TRANSPOSE)

    @operator
    def flip(self, asset: Asset, orientation: FlipOrientation) -> Asset:
        """
        Creates a new asset whose essence is flipped according the specified orientation.

        :param asset: Asset whose essence is to be flipped
        :type asset: Asset
        :param orientation: axis of the flip operation
        :type orientation: FlipOrientation
        :return: Asset with flipped essence
        :rtype: Asset
        """
        if orientation == FlipOrientation.HORIZONTAL:
            flip_orientation = PIL.Image.Transpose.FLIP_LEFT_RIGHT
        else:
            flip_orientation = PIL.Image.Transpose.FLIP_TOP_BOTTOM
        return self._rotate(asset, flip_orientation)

    @operator
    def auto_orient(self, asset: Asset) -> Asset:
        """
        Creates a new asset whose essence is rotated according to the Exif
        orientation. If no orientation metadata exists or asset is not rotated,
        an identical asset object is returned.

        :param asset: Asset with orientation metadata
        :type asset: Asset
        :return: Asset with rotated essence
        :rtype: Asset
        """
        orientation = asset.metadata.get('exif', {}).get('orientation')
        if orientation is None or orientation == 1:
            return asset

        flip_horizontally: Callable[[Asset], Asset] = self.flip(orientation=FlipOrientation.HORIZONTAL)
        flip_vertically: Callable[[Asset], Asset] = self.flip(orientation=FlipOrientation.VERTICAL)

        if orientation == 2:
            oriented_asset = flip_horizontally(asset)
        elif orientation == 3:
            oriented_asset = self._rotate(asset, PIL.Image.Transpose.ROTATE_180)
        elif orientation == 4:
            oriented_asset = flip_vertically(asset)
        elif orientation == 5:
            oriented_asset = flip_vertically(self._rotate(asset, PIL.Image.Transpose.ROTATE_90))
        elif orientation == 6:
            oriented_asset = self._rotate(asset, PIL.Image.Transpose.ROTATE_270)
        elif orientation == 7:
            oriented_asset = flip_horizontally(self._rotate(asset, PIL.Image.Transpose.ROTATE_90))
        elif orientation == 8:
            oriented_asset = self._rotate(asset, PIL.Image.Transpose.ROTATE_90)
        else:
            raise OperatorError(f'Unable to correct image orientation with value {orientation}')

        return oriented_asset

    @operator
    def convert(
        self,
        asset: Asset,
        mime_type: MimeType | str,
        color_space: str | None = None,
        depth: int | None = None,
        data_type: str | None = None,
    ) -> Asset:
        """
        Creates a new asset of the specified MIME type from the essence of the
        specified asset.

        :param asset: Asset whose contents will be converted
        :type asset: Asset
        :param mime_type: Target MIME type
        :type mime_type: MimeType or str
        :param color_space: Name of color space
        :type color_space: str or None
        :param depth: Bit depth per channel
        :type depth: int or None
        :param data_type: Data type of the pixels, e.g. 'uint' or 'float'
        :type data_type: str or None
        :return: New asset with converted essence
        :rtype: Asset
        """
        mime_type = MimeType(mime_type)
        try:
            with PIL.Image.open(asset.essence) as image:
                color_mode = color_space or asset.color_space, depth or asset.depth, data_type or asset.data_type
                pil_mode = PillowProcessor.__pillow_mode_to_color_mode.inv.get(color_mode)
                if pil_mode is not None and pil_mode != image.mode:
                    image = image.convert(pil_mode)
                converted_asset = self._image_to_asset(image, mime_type)
        except (IOError, KeyError) as pil_error:
            raise OperatorError(f'Could not convert image to {mime_type}: {pil_error}')

        return converted_asset

    @operator
    def crop(self, asset: Asset, x: int, y: int, width: int, height: int) -> Asset:
        """
        Creates a new asset whose essence is cropped to the specified
        rectangular area.

        :param asset: Asset whose contents will be cropped
        :type asset: Asset
        :param x: horizontal offset of the cropping area from left
        :type x: int
        :param y: vertical offset of the cropping area from top
        :type y: int
        :param width: width of the cropping area
        :type width: int
        :param height: height of the cropping area
        :type height: int
        :return: New asset with cropped essence
        :rtype: Asset
        """
        if x == 0 and y == 0 and width == asset.width and height == asset.height:
            return asset

        max_x = max(0, min(asset.width, width + x))
        max_y = max(0, min(asset.height, height + y))
        min_x = max(0, min(asset.width, x))
        min_y = max(0, min(asset.height, y))

        if min_x == asset.width or min_y == asset.height or max_x <= min_x or max_y <= min_y:
            raise OperatorError(f'Invalid cropping area: <x={x!r}, y={y!r}, width={width!r}, height={height!r}>')

        with PIL.Image.open(asset.essence) as image:
            cropped_image = image.crop(box=(min_x, min_y, max_x, max_y))
        with cropped_image:
            cropped_asset = self._image_to_asset(cropped_image, mime_type=asset.mime_type)

        return cropped_asset

    @operator
    def fill_background(self, asset: Asset, color: tuple[int, int, int]) -> Asset:
        """
        Creates a new asset whose alpha channel is merged into a solid colour
        background.

        Transparent and semi-transparent pixels are composited over the
        specified background colour. If the source image has no alpha channel,
        the pixels are returned unchanged. The output is always an opaque RGB
        image in the same format as the input.

        :param asset: Asset whose essence will have its background filled
        :type asset: Asset
        :param color: Background colour as an ``(red, green, blue)`` tuple
            with values in the range ``[0, 255]``
        :type color: tuple[int, int, int]
        :return: Asset with alpha composited over the fill colour
        :rtype: Asset
        """
        mime_type = MimeType(asset.mime_type)
        with PIL.Image.open(asset.essence) as image:
            if image.mode not in ('RGBA', 'LA', 'PA'):
                return self._image_to_asset(image, mime_type=mime_type)
            background = PIL.Image.new('RGB', image.size, color)
            background.paste(image.convert('RGBA'), mask=image.convert('RGBA'))
        with background:
            return self._image_to_asset(background, mime_type=mime_type)

    @operator
    def pad(
        self,
        asset: Asset,
        width: int,
        height: int,
        color: tuple[int, int, int] | tuple[int, int, int, int] = (0, 0, 0, 0),
        gravity: str = 'center',
    ) -> Asset:
        """
        Creates a new asset whose essence is placed on a larger canvas.

        The source image is pasted onto a canvas of size ``(width, height)``
        filled with ``color``. The position on the canvas is determined by
        ``gravity``.

        Valid gravity values: ``'north_west'``, ``'north'``, ``'north_east'``,
        ``'west'``, ``'center'``, ``'east'``, ``'south_west'``, ``'south'``,
        ``'south_east'``.

        :param asset: Asset whose essence will be padded
        :type asset: Asset
        :param width: Canvas width; must be >= the source image width
        :type width: int
        :param height: Canvas height; must be >= the source image height
        :type height: int
        :param color: Fill color for the added area as an RGB or RGBA tuple
        :type color: tuple
        :param gravity: Anchor position of the source image on the canvas
        :type gravity: str
        :return: Asset with padded essence
        :rtype: Asset
        :raises OperatorError: If the canvas is smaller than the source image
        """
        if width < asset.width or height < asset.height:
            raise OperatorError(
                f'Canvas ({width}×{height}) is smaller than source ({asset.width}×{asset.height})'
            )
        mime_type = MimeType(asset.mime_type)
        with PIL.Image.open(asset.essence) as image:
            canvas_mode = 'RGBA' if len(color) == 4 else 'RGB'
            canvas = PIL.Image.new(canvas_mode, (width, height), color)
            x, y = _resolve_gravity(width, height, image.width, image.height, gravity)
            if image.mode in ('RGBA', 'LA'):
                canvas.paste(image, (x, y), mask=image)
            else:
                canvas.paste(image, (x, y))
        with canvas:
            return self._image_to_asset(canvas, mime_type=mime_type)

    @operator
    def vignette(self, asset: Asset, strength: float = 0.5) -> Asset:
        """
        Creates a new asset whose essence has a radial vignette applied.

        The vignette darkens the edges of the image while leaving the center
        unaffected. ``strength`` controls how much darkening is applied at the
        corners: ``0.0`` leaves the image unchanged; ``1.0`` makes the corners
        completely black.

        :param asset: Asset whose essence will receive the vignette
        :type asset: Asset
        :param strength: Vignette intensity in the range ``[0.0, 1.0]``
        :type strength: float
        :return: Asset with vignette applied
        :rtype: Asset
        """
        mime_type = MimeType(asset.mime_type)
        with PIL.Image.open(asset.essence) as image:
            rgb = image.convert('RGB')
            w, h = rgb.size
            cx, cy = w / 2.0, h / 2.0
            max_dist = math.sqrt(cx * cx + cy * cy)
            mask_pixels = []
            for y in range(h):
                for x in range(w):
                    dist = math.sqrt((x - cx) ** 2 + (y - cy) ** 2)
                    brightness = max(0.0, 1.0 - strength * dist / max_dist) if max_dist > 0 else 1.0
                    mask_pixels.append(round(brightness * 255))
            mask = PIL.Image.new('L', (w, h))
            mask.putdata(mask_pixels)
            black = PIL.Image.new('RGB', (w, h), (0, 0, 0))
            vignetted = PIL.Image.composite(rgb, black, mask)
        with vignetted:
            return self._image_to_asset(vignetted, mime_type=mime_type)

    @operator
    def tint(self, asset: Asset, color: tuple[int, int, int], opacity: float = 0.5) -> Asset:
        """
        Creates a new asset whose essence is tinted with the specified color.

        The tint is blended over the image at the given opacity. An ``opacity``
        of ``0.0`` leaves the image unchanged; ``1.0`` fills it entirely with
        ``color``. The output is always an RGB image in the same format as the
        input.

        :param asset: Asset whose essence will be tinted
        :type asset: Asset
        :param color: RGB tint color as a ``(red, green, blue)`` tuple with
            values in the range ``[0, 255]``
        :type color: tuple[int, int, int]
        :param opacity: Tint opacity in the range ``[0.0, 1.0]``
        :type opacity: float
        :return: Asset with tinted essence
        :rtype: Asset
        """
        mime_type = MimeType(asset.mime_type)
        with PIL.Image.open(asset.essence) as image:
            base = image.convert('RGB')
            tint_layer = PIL.Image.new('RGB', base.size, color)
            alpha = round(opacity * 255)
            tinted = PIL.Image.blend(base, tint_layer, alpha / 255)
        with tinted:
            return self._image_to_asset(tinted, mime_type=mime_type)

    @operator
    def sepia(self, asset: Asset) -> Asset:
        """
        Creates a new asset whose essence has a sepia tone applied.

        The image is first converted to greyscale, then colorised with warm
        brown tones characteristic of historical photographs. The output is
        always an RGB image in the same format as the input.

        :param asset: Asset whose essence will be toned
        :type asset: Asset
        :return: Asset with sepia-toned essence
        :rtype: Asset
        """
        mime_type = MimeType(asset.mime_type)
        with PIL.Image.open(asset.essence) as image:
            grey = image.convert('L')
            sepia_image = PIL.ImageOps.colorize(grey, black=(112, 66, 20), white=(255, 245, 210))
        with sepia_image:
            return self._image_to_asset(sepia_image, mime_type=mime_type)

    @operator
    def sharpen(self, asset: Asset, radius: float = 2, percent: int = 150, threshold: int = 3) -> Asset:
        """
        Creates a new asset whose essence is sharpened using an unsharp mask.

        The unsharp mask works by subtracting a blurred version of the image
        from itself. Higher ``percent`` values produce stronger sharpening;
        ``threshold`` controls which pixel differences are sharpened.

        :param asset: Asset whose essence will be sharpened
        :type asset: Asset
        :param radius: Blur radius for the unsharp mask
        :type radius: float
        :param percent: Strength of the sharpening effect as a percentage
        :type percent: int
        :param threshold: Minimum brightness difference to sharpen
        :type threshold: int
        :return: Asset with sharpened essence
        :rtype: Asset
        """
        mime_type = MimeType(asset.mime_type)
        with PIL.Image.open(asset.essence) as image:
            sharpened = image.filter(PIL.ImageFilter.UnsharpMask(radius, percent, threshold))
        with sharpened:
            return self._image_to_asset(sharpened, mime_type=mime_type)

    @operator
    def blur(self, asset: Asset, radius: float = 2) -> Asset:
        """
        Creates a new asset whose essence is blurred using a Gaussian kernel.

        Higher ``radius`` values produce stronger blur. A ``radius`` of ``0``
        leaves the image unchanged.

        :param asset: Asset whose essence will be blurred
        :type asset: Asset
        :param radius: Blur radius in pixels; ``0`` means no blur
        :type radius: float
        :return: Asset with blurred essence
        :rtype: Asset
        """
        mime_type = MimeType(asset.mime_type)
        with PIL.Image.open(asset.essence) as image:
            blurred = image.filter(PIL.ImageFilter.GaussianBlur(radius))
        with blurred:
            return self._image_to_asset(blurred, mime_type=mime_type)

    @operator
    def adjust_sharpness(self, asset: Asset, factor: float) -> Asset:
        """
        Creates a new asset whose essence has adjusted sharpness.

        A factor of ``0.0`` produces a blurred (smoothed) image. A factor of
        ``1.0`` returns an image identical to the input. Values above ``1.0``
        sharpen the image; values between ``0.0`` and ``1.0`` blur it.

        :param asset: Asset whose sharpness will be adjusted
        :type asset: Asset
        :param factor: Sharpness enhancement factor; ``1.0`` means no change
        :type factor: float
        :return: Asset with adjusted sharpness
        :rtype: Asset
        """
        mime_type = MimeType(asset.mime_type)
        with PIL.Image.open(asset.essence) as image:
            enhanced = PIL.ImageEnhance.Sharpness(image).enhance(factor)
        with enhanced:
            return self._image_to_asset(enhanced, mime_type=mime_type)

    @operator
    def adjust_saturation(self, asset: Asset, factor: float) -> Asset:
        """
        Creates a new asset whose essence has adjusted color saturation.

        A factor of ``0.0`` produces a greyscale image. A factor of ``1.0``
        returns an image identical to the input. Values above ``1.0`` increase
        saturation; values between ``0.0`` and ``1.0`` decrease it.

        :param asset: Asset whose saturation will be adjusted
        :type asset: Asset
        :param factor: Saturation enhancement factor; ``1.0`` means no change
        :type factor: float
        :return: Asset with adjusted saturation
        :rtype: Asset
        """
        mime_type = MimeType(asset.mime_type)
        with PIL.Image.open(asset.essence) as image:
            enhanced = PIL.ImageEnhance.Color(image).enhance(factor)
        with enhanced:
            return self._image_to_asset(enhanced, mime_type=mime_type)

    @operator
    def adjust_contrast(self, asset: Asset, factor: float) -> Asset:
        """
        Creates a new asset whose essence has adjusted contrast.

        A factor of ``0.0`` produces a solid gray image (the mean color of
        the original). A factor of ``1.0`` returns an image identical to the
        input. Values above ``1.0`` increase contrast; values between ``0.0``
        and ``1.0`` decrease it.

        :param asset: Asset whose contrast will be adjusted
        :type asset: Asset
        :param factor: Contrast enhancement factor; ``1.0`` means no change
        :type factor: float
        :return: Asset with adjusted contrast
        :rtype: Asset
        """
        mime_type = MimeType(asset.mime_type)
        with PIL.Image.open(asset.essence) as image:
            enhanced = PIL.ImageEnhance.Contrast(image).enhance(factor)
        with enhanced:
            return self._image_to_asset(enhanced, mime_type=mime_type)

    @operator
    def adjust_brightness(self, asset: Asset, factor: float) -> Asset:
        """
        Creates a new asset whose essence has adjusted brightness.

        A factor of ``0.0`` produces a black image. A factor of ``1.0``
        returns an image identical to the input. Values above ``1.0``
        increase brightness; values between ``0.0`` and ``1.0`` decrease it.

        :param asset: Asset whose brightness will be adjusted
        :type asset: Asset
        :param factor: Brightness enhancement factor; ``1.0`` means no change
        :type factor: float
        :return: Asset with adjusted brightness
        :rtype: Asset
        """
        mime_type = MimeType(asset.mime_type)
        with PIL.Image.open(asset.essence) as image:
            enhanced = PIL.ImageEnhance.Brightness(image).enhance(factor)
        with enhanced:
            return self._image_to_asset(enhanced, mime_type=mime_type)

    @operator
    def rotate(self, asset: Asset, angle: float, expand: bool = False) -> Asset:
        """
        Creates an asset whose essence is rotated by the specified angle in
        degrees.

        :param asset: Asset whose contents will be rotated
        :type asset: Asset
        :param angle: Angle in degrees, counter clockwise
        :type angle: float
        :param expand: If true, changes the dimensions of the new asset so it
            can hold the entire rotated essence, otherwise the dimensions of
            the original asset will be used.
        :type expand: bool
        :return: New asset with rotated essence
        :rtype: Asset
        """
        if angle % 360.0 == 0.0:
            return asset

        with PIL.Image.open(asset.essence) as image:
            rotated_image = image.rotate(angle=angle, resample=PIL.Image.Resampling.BICUBIC, expand=expand)
        with rotated_image:
            rotated_asset = self._image_to_asset(rotated_image, mime_type=asset.mime_type)

        return rotated_asset
