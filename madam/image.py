import io
from enum import Enum
from typing import Any, Callable, IO, Mapping, Optional, Union

from bidict import bidict
import PIL.ExifTags
import PIL.Image

from madam.core import operator, OperatorError
from madam.core import Asset, Processor
from madam.mime import MimeType


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
    __mime_type_to_pillow_type = bidict({
        MimeType('image/bmp'): 'BMP',
        MimeType('image/gif'): 'GIF',
        MimeType('image/jpeg'): 'JPEG',
        MimeType('image/png'): 'PNG',
        MimeType('image/tiff'): 'TIFF',
        MimeType('image/webp'): 'WEBP',
    })

    __format_defaults = {
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

    __pillow_mode_to_color_mode = bidict({
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
    })

    def __init__(self, config: Optional[Mapping[str, Any]] = None) -> None:
        """
        Initializes a new `PillowProcessor`.

        :param config: Mapping with settings.
        """
        super().__init__(config)

    def read(self, file: IO) -> Asset:
        image = PIL.Image.open(file)
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
            file.seek(0)
            return True
        except IOError:
            return False

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
        image = PIL.Image.open(asset.essence)
        mime_type = MimeType(asset.mime_type)
        if mode == ResizeMode.EXACT:
            resized_width = width
            resized_height = height
        else:
            aspect = asset.width / asset.height
            aspect_target = width / height
            if mode == ResizeMode.FIT and aspect >= aspect_target or \
               mode == ResizeMode.FILL and aspect <= aspect_target:
                resize_factor = width / image.width
            else:
                resize_factor = height / image.height
            resized_width = max(1, round(resize_factor * image.width))
            resized_height = max(1, round(resize_factor * image.height))
        # Pillow supports resampling only for 8-bit images
        resampling_method = PIL.Image.LANCZOS if asset.depth == 8 else PIL.Image.NEAREST
        resized_image = image.resize((resized_width, resized_height),
                                     resample=resampling_method)
        resized_asset = self._image_to_asset(resized_image, mime_type=mime_type)
        return resized_asset

    def _image_to_asset(self, image: PIL.Image.Image, mime_type: Union[MimeType, str]) -> Asset:
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
        format_config = dict(self.config.get(mime_type.type, {}))
        format_config.update(self.config.get(str(mime_type), {}))

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
        elif mime_type == MimeType('image/webp'):
            pil_options['method'] = int(format_config.get('method', pil_options['method']))
            pil_options['quality'] = int(format_config.get('quality', pil_options['quality']))
            image.save(image_buffer, pil_format, **pil_options)
        else:
            image.save(image_buffer, pil_format, **pil_options)

        image_buffer.seek(0)

        asset = self.read(image_buffer)
        return asset

    def _rotate(self, asset: Asset, rotation: int) -> Asset:
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
        image = PIL.Image.open(asset.essence)
        mime_type = MimeType(asset.mime_type)
        transposed_image = image.transpose(rotation)
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
        return self._rotate(asset, PIL.Image.TRANSPOSE)

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
            flip_orientation = PIL.Image.FLIP_LEFT_RIGHT
        else:
            flip_orientation = PIL.Image.FLIP_TOP_BOTTOM
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

        flip_horizontally = self.flip(orientation=FlipOrientation.HORIZONTAL)  # type: Callable[[Asset], Asset]
        flip_vertically = self.flip(orientation=FlipOrientation.VERTICAL)  # type: Callable[[Asset], Asset]

        if orientation == 2:
            oriented_asset = flip_horizontally(asset)
        elif orientation == 3:
            oriented_asset = self._rotate(asset, PIL.Image.ROTATE_180)
        elif orientation == 4:
            oriented_asset = flip_vertically(asset)
        elif orientation == 5:
            oriented_asset = flip_vertically(self._rotate(asset, PIL.Image.ROTATE_90))
        elif orientation == 6:
            oriented_asset = self._rotate(asset, PIL.Image.ROTATE_270)
        elif orientation == 7:
            oriented_asset = flip_horizontally(self._rotate(asset, PIL.Image.ROTATE_90))
        elif orientation == 8:
            oriented_asset = self._rotate(asset, PIL.Image.ROTATE_90)
        else:
            raise OperatorError('Unable to correct image orientation with value %s' % orientation)

        return oriented_asset

    @operator
    def convert(self, asset: Asset, mime_type: Union[MimeType, str],
                color_space: Optional[str] = None, depth: Optional[int] = None,
                data_type: Optional[str] = None):
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
            image = PIL.Image.open(asset.essence)
            color_mode = color_space or asset.color_space, depth or asset.depth, data_type or asset.data_type
            pil_mode = PillowProcessor.__pillow_mode_to_color_mode.inv.get(color_mode)
            if pil_mode is not None and pil_mode != image.mode:
                image = image.convert(pil_mode)
            converted_asset = self._image_to_asset(image, mime_type)
        except (IOError, KeyError) as pil_error:
            raise OperatorError('Could not convert image to %s: %s' %
                                (mime_type, pil_error))

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
            raise OperatorError('Invalid cropping area: <x=%r, y=%r, width=%r, height=%r>' % (x, y, width, height))

        image = PIL.Image.open(asset.essence)
        cropped_image = image.crop(box=(min_x, min_y, max_x, max_y))
        cropped_asset = self._image_to_asset(cropped_image, mime_type=asset.mime_type)

        return cropped_asset

    @operator
    def rotate(self, asset: Asset, angle: float, expand: bool = False):
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

        image = PIL.Image.open(asset.essence)
        rotated_image = image.rotate(angle=angle, resample=PIL.Image.BICUBIC, expand=expand)
        rotated_asset = self._image_to_asset(rotated_image, mime_type=asset.mime_type)

        return rotated_asset
