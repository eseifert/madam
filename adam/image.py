from adam.core import Asset, supports_mime_types

@supports_mime_types('image/jpeg')
def read_jpeg(jpeg_file):
    asset = Asset()
    asset.mime_type = 'image/jpeg'
    asset.essence = 0
    return asset
