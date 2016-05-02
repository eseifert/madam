from adam.core import Asset, supports_mime_types
import PIL.Image, PIL.ExifTags


@supports_mime_types('image/jpeg')
def read_jpeg(jpeg_file):
    asset = Asset()
    asset.mime_type = 'image/jpeg'
    image = PIL.Image.open(jpeg_file)
    asset.width = image.width
    asset.height = image.height
    jpeg_file.seek(0)
    asset.essence = jpeg_file.read()
    return asset
