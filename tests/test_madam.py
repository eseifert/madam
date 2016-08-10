import io
import piexif

import madam
from assets import jpeg_asset, exif


def test_jpeg_asset_essence_does_not_contain_exif_metadata(exif):
    jpeg_data = io.BytesIO()
    piexif.insert(piexif.dump(exif), jpeg_asset().essence.read(), new_file=jpeg_data)
    asset = madam.read(jpeg_data)
    essence_bytes = asset.essence.read()

    essence_exif = piexif.load(essence_bytes)

    for ifd, ifd_data in essence_exif.items():
        assert not ifd_data
