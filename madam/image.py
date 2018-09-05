import io
from enum import Enum

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
    def __init__(self):
        """
        Initializes a new `PillowProcessor`.
        """
        super().__init__()
        self.__mime_type_to_pillow_type = bidict({
            MimeType('image/gif'): 'GIF',
            MimeType('image/jpeg'): 'JPEG',
            MimeType('image/png'): 'PNG'
        })

    def read(self, file):
        image = PIL.Image.open(file)
        mime_type = self.__mime_type_to_pillow_type.inv[image.format]
        metadata = dict(
            mime_type=str(mime_type),
            width=image.width,
            height=image.height
        )
        file.seek(0)
        asset = Asset(file, **metadata)
        return asset

    def can_read(self, file):
        try:
            PIL.Image.open(file)
            file.seek(0)
            return True
        except IOError:
            return False

    @operator
    def resize(self, asset, width, height, mode=ResizeMode.EXACT):
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
        width_delta = width - image.width
        height_delta = height - image.height
        resized_width = width
        resized_height = height
        if mode in (ResizeMode.FIT, ResizeMode.FILL):
            if mode == ResizeMode.FIT and width_delta < height_delta or \
               mode == ResizeMode.FILL and width_delta > height_delta:
                resize_factor = width / image.width
            else:
                resize_factor = height / image.height
            resized_width = round(resize_factor * image.width)
            resized_height = round(resize_factor * image.height)
        resized_image = image.resize((resized_width, resized_height),
                                     resample=PIL.Image.LANCZOS)
        resized_asset = self._image_to_asset(resized_image, mime_type=mime_type)
        return resized_asset

    def _image_to_asset(self, image, mime_type):
        mime_type = MimeType(mime_type)
        pil_format = self.__mime_type_to_pillow_type[mime_type]
        image_buffer = io.BytesIO()
        image.save(image_buffer, pil_format)
        image_buffer.seek(0)
        asset = self.read(image_buffer)
        return asset

    def _rotate(self, asset, rotation):
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
    def transpose(self, asset):
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
    def flip(self, asset, orientation):
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
    def auto_orient(self, asset):
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

        flip_horizontally = self.flip(orientation=FlipOrientation.HORIZONTAL)
        flip_vertically = self.flip(orientation=FlipOrientation.VERTICAL)

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
    def convert(self, asset, mime_type):
        """
        Creates a new asset of the specified MIME type from the essence of the
        specified asset.

        :param asset: Asset whose contents will be converted
        :type asset: Asset
        :param mime_type: Target MIME type
        :type mime_type: MimeType or str
        :return: New asset with converted essence
        :rtype: Asset
        """
        mime_type = MimeType(mime_type)
        try:
            image = PIL.Image.open(asset.essence)
            converted_asset = self._image_to_asset(image, mime_type)
        except (IOError, KeyError) as pil_error:
            raise OperatorError('Could not convert image to %s: %s' %
                                (mime_type, pil_error))

        return converted_asset

    @operator
    def crop(self, asset, x, y, width, height):
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
    def rotate(self, asset, angle, expand=False):
        """
        Creates an asset whose essence is rotated by the specified angle in
        degrees.

        .. warning:: The color model will be changed to RGB when applying
            this operation

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

        image = PIL.Image.open(asset.essence).convert('RGB')
        rotated_image = image.rotate(angle=angle, resample=PIL.Image.BICUBIC, expand=expand)
        rotated_asset = self._image_to_asset(rotated_image, mime_type=asset.mime_type)

        return rotated_asset
