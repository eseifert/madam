from adam.core import Asset, supports_mime_types
import io
import piexif
import PIL.Image, PIL.ExifTags


@supports_mime_types('image/jpeg')
def read_jpeg(jpeg_file):
    asset = Asset()
    asset.mime_type = 'image/jpeg'
    image = PIL.Image.open(jpeg_file)
    asset.width = image.width
    asset.height = image.height

    jpeg_file.seek(0)
    essence_data_with_metadata = jpeg_file.read()
    exif = piexif.load(essence_data_with_metadata)
    asset.artist = exif['0th'][piexif.ImageIFD.Artist].decode('utf-8')
    essence_without_metadata_as_stream = io.BytesIO()
    piexif.remove(essence_data_with_metadata, essence_without_metadata_as_stream)
    asset.essence = essence_without_metadata_as_stream
    return asset
