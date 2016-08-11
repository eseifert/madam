import unittest.mock

import io
import piexif
import pytest

import madam
from madam.core import UnsupportedFormatError
from assets import jpeg_asset, exif


def test_jpeg_asset_essence_does_not_contain_exif_metadata(exif):
    jpeg_data = io.BytesIO()
    piexif.insert(piexif.dump(exif), jpeg_asset().essence.read(), new_file=jpeg_data)
    asset = madam.read(jpeg_data)
    essence_bytes = asset.essence.read()

    essence_exif = piexif.load(essence_bytes)

    for ifd, ifd_data in essence_exif.items():
        assert not ifd_data


@pytest.mark.parametrize('path, mime_type', [
    ('tests/resources/16-bit-mono.wav', None),
    ('tests/resources/64kbits.mp3', None),
])
def test_read_calls_read_method_for_respective_file_type(path, mime_type):
    # When
    with open(path, 'rb') as file:
        data = file.read()
    for processor in madam.core.processors:
        if processor.can_read(io.BytesIO(data)):
            with unittest.mock.patch.object(processor, 'read') as read_method:
                # Then
                madam.read(io.BytesIO(data), mime_type=mime_type)
            # Assert
            assert read_method.called
            break


def test_read_empty_file_raises_error():
    file_data = io.BytesIO()
    with pytest.raises(UnsupportedFormatError):
        madam.read(file_data)
