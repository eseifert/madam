import PIL.Image
import io
import piexif

import madam.core


def image_rgb(width=4, height=3, transpositions=None):
    if not transpositions:
        transpositions = []
    image = PIL.Image.new('RGB', (width, height))
    # Fill the image with a shape which is (probably) not invariant towards
    # rotations or flips as long as the image has a size of (2, 2) or greater
    for y in range(0, height):
        for x in range(0, width):
            color = (255, 255, 255) if y == 0 or x == 0 else (0, 0, 0)
            image.putpixel((x, y), color)
    for transposition in transpositions:
        image = image.transpose(transposition)
    return image


def jpeg_rgb(width=4, height=3, transpositions=None):
    if not transpositions:
        transpositions = []
    image = image_rgb(width=width, height=height, transpositions=transpositions)
    image_data = io.BytesIO()
    image.save(image_data, 'JPEG', quality=100)
    image_data.seek(0)
    return image_data


def png_rgb():
    image = image_rgb()
    image_data = io.BytesIO()
    image.save(image_data, 'PNG')
    image_data.seek(0)
    return image_data


def add_exif_to_jpeg(exif, image_data):
    exif_bytes = piexif.dump(exif)
    image_with_exif_metadata = io.BytesIO()
    piexif.insert(exif_bytes, image_data.read(), image_with_exif_metadata)
    return image_with_exif_metadata


def jpeg_asset(width=4, height=3, transpositions=None):
    if not transpositions:
        transpositions = []
    asset = madam.core.Asset()
    asset.essence = jpeg_rgb(width=width, height=height, transpositions=transpositions)
    asset.metadata['exif'] = {'0th': {piexif.ImageIFD.Artist: b'Test artist'}}
    asset.metadata['madam'] = {'width': width, 'height': height}
    return asset


def png_asset():
    asset = madam.core.Asset()
    asset.essence = png_rgb()
    return asset
