import functools
import io
from enum import Enum

import piexif
import PIL.ExifTags
import PIL.Image

from adam.core import Asset, Processor, MetadataProcessor


class ExifProcessor(MetadataProcessor):
    @property
    def format(self):
        return 'exif'

    def read(self, file):
        data = file.read()
        exif = piexif.load(data)
        exif_stripped_from_empty_entries = {key: value for (key, value) in exif.items() if value}
        return exif_stripped_from_empty_entries

    def remove(self, file):
        data = file.read()
        essence_without_metadata_as_stream = io.BytesIO()
        piexif.remove(data, essence_without_metadata_as_stream)
        return essence_without_metadata_as_stream


class ResizeMode(Enum):
    EXACT = 0
    FIT = 1
    FILL = 2


class FlipOrientation(Enum):
    HORIZONTAL = 0
    VERTICAL = 1


def operator(function):
    @functools.wraps(function)
    def wrapper(self, **kwargs):
        configured_operator = functools.partial(function, self, **kwargs)
        return configured_operator
    return wrapper


class PillowProcessor(Processor):
    def __init__(self, exif_processor):
        super().__init__()
        self.exif_processor = exif_processor

    def read(self, jpeg_file):
        asset = Asset()
        asset['mime_type'] = 'image/jpeg'
        image = PIL.Image.open(jpeg_file)
        asset['width'] = image.width
        asset['height'] = image.height

        jpeg_file.seek(0)
        asset.metadata['exif'] = self.exif_processor.read(jpeg_file)
        jpeg_file.seek(0)
        asset.essence = self.exif_processor.remove(jpeg_file)

        exif_0th = asset.metadata['exif'].get('0th')
        if exif_0th:
            artist = exif_0th.get(piexif.ImageIFD.Artist)
            if artist:
                asset['artist'] = artist.decode('utf-8')
        return asset

    def can_read(self, mime_type):
        return mime_type in ['image/jpeg']

    def write(self, jpeg_asset, jpeg_file):
        jpeg_data = jpeg_asset.essence
        image = PIL.Image.open(jpeg_data)
        image.save(jpeg_file, 'JPEG')

    @operator
    def resize(self, asset, width, height, mode=ResizeMode.EXACT):
        image = PIL.Image.open(asset.essence)
        width_delta = width - image.width
        height_delta = height - image.height
        resized_width = width
        resized_height = height
        if mode in (ResizeMode.FIT, ResizeMode.FILL):
            if mode == ResizeMode.FIT and width_delta < height_delta or \
               mode == ResizeMode.FILL and width_delta > height_delta:
                resize_factor = width/image.width
            else:
                resize_factor = height/image.height
            resized_width = round(resize_factor*image.width)
            resized_height = round(resize_factor*image.height)
        resized_image = image.resize((resized_width, resized_height), resample=PIL.Image.LANCZOS)
        resized_asset = self._image_to_asset(resized_image)
        return resized_asset

    def _image_to_asset(self, image):
        image_buffer = io.BytesIO()
        image.save(image_buffer, 'JPEG')
        asset = self.read(image_buffer)
        return asset

    def _rotate_lossless(self, asset, rotation):
        image = PIL.Image.open(asset.essence)
        transposed_image = image.transpose(rotation)
        transposed_asset = self._image_to_asset(transposed_image)
        return transposed_asset

    @operator
    def transpose(self, asset):
        return self._rotate_lossless(asset, PIL.Image.TRANSPOSE)

    @operator
    def flip(self, asset, orientation):
        flip_orientation = PIL.Image.FLIP_LEFT_RIGHT if orientation == FlipOrientation.HORIZONTAL else PIL.Image.FLIP_TOP_BOTTOM
        return self._rotate_lossless(asset, flip_orientation)

    @operator
    def auto_orient(self, asset):
        orientation = asset.metadata['exif']['0th'][piexif.ImageIFD.Orientation]
        if orientation == 1:
            oriented_asset = Asset()
            oriented_asset.essence = asset.essence
        elif orientation == 2:
            oriented_asset = self.flip(orientation=FlipOrientation.HORIZONTAL)(asset)
        elif orientation == 3:
            oriented_asset = self._rotate_lossless(asset, PIL.Image.ROTATE_180)
        elif orientation == 4:
            oriented_asset = self.flip(orientation=FlipOrientation.VERTICAL)(asset)
        elif orientation == 5:
            oriented_asset = self.flip(orientation=FlipOrientation.VERTICAL)(self._rotate_lossless(asset, PIL.Image.ROTATE_90))
        elif orientation == 6:
            oriented_asset = self._rotate_lossless(asset, PIL.Image.ROTATE_270)
        elif orientation == 7:
            oriented_asset = self.flip(orientation=FlipOrientation.HORIZONTAL)(self._rotate_lossless(asset, PIL.Image.ROTATE_90))
        elif orientation == 8:
            oriented_asset = self._rotate_lossless(asset, PIL.Image.ROTATE_90)
        else:
            raise ValueError('Unable to correct image orientation with value %s' % orientation)

        return oriented_asset
