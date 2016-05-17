import functools
import io
from enum import Enum

import piexif
import PIL.ExifTags
import PIL.Image

from adam.core import Asset, Processor


def _separate_exif_from_image(image_file):
    essence_data_with_metadata = image_file.read()
    exif = piexif.load(essence_data_with_metadata)
    exif_stripped_from_empty_entries = {key: value for (key, value) in exif.items() if value}
    essence_without_metadata_as_stream = io.BytesIO()
    piexif.remove(essence_data_with_metadata, essence_without_metadata_as_stream)
    return exif_stripped_from_empty_entries, essence_without_metadata_as_stream


class ResizeMode(Enum):
    EXACT = 0
    FIT = 1
    FILL = 2


def operator(function):
    @functools.wraps(function)
    def wrapper(self, **kwargs):
        configured_operator = functools.partial(function, self, **kwargs)
        return configured_operator
    return wrapper


class PillowProcessor(Processor):
    supported_read_types = ['image/jpeg']

    def read(self, jpeg_file):
        asset = Asset()
        asset['mime_type'] = 'image/jpeg'
        image = PIL.Image.open(jpeg_file)
        asset['width'] = image.width
        asset['height'] = image.height

        jpeg_file.seek(0)
        asset.metadata['exif'], asset.essence = _separate_exif_from_image(jpeg_file)

        exif_0th = asset.metadata['exif'].get('0th')
        if exif_0th:
            artist = exif_0th.get(piexif.ImageIFD.Artist)
            if artist:
                asset['artist'] = artist.decode('utf-8')
        return asset

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
        resized_image_buffer = io.BytesIO()
        resized_image.save(resized_image_buffer, 'JPEG')
        resized_asset = self.read(resized_image_buffer)
        return resized_asset

    @operator
    def transpose(self, asset):
        image = PIL.Image.open(asset.essence)
        transposed_image = image.transpose(PIL.Image.TRANSPOSE)
        transposed_image_buffer = io.BytesIO()
        transposed_image.save(transposed_image_buffer, 'JPEG')
        transposed_asset = self.read(transposed_image_buffer)
        return transposed_asset
