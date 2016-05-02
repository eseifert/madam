from adam.core import Asset, supports_mime_types
import PIL.Image, PIL.ExifTags

@supports_mime_types('image/jpeg')
def read_jpeg(jpeg_file):
    asset = Asset()
    asset.mime_type = 'image/jpeg'
    image = PIL.Image.open(jpeg_file)
    asset.width,asset.height = image.info['jfif_density']
    asset.essence = 0
    return asset
