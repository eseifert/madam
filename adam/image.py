from adam.core import Asset, supports_mime_types
import io
import piexif
import PIL.ExifTags
import PIL.Image


@supports_mime_types('image/jpeg')
def read_jpeg(jpeg_file):
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


def _separate_exif_from_image(image_file):
    essence_data_with_metadata = image_file.read()
    exif = piexif.load(essence_data_with_metadata)
    exif_stripped_from_empty_entries = {key: value for (key, value) in exif.items() if value}
    essence_without_metadata_as_stream = io.BytesIO()
    piexif.remove(essence_data_with_metadata, essence_without_metadata_as_stream)
    return exif_stripped_from_empty_entries, essence_without_metadata_as_stream
