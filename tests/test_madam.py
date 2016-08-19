import io
import os
import unittest.mock

import piexif
import pytest

import madam
from madam.core import UnsupportedFormatError
from assets import jpeg_asset, png_asset, image_asset


def test_jpeg_asset_essence_does_not_contain_exif_metadata():
    exif = jpeg_asset().metadata['exif']
    data_with_exif = io.BytesIO()
    piexif.insert(piexif.dump(exif), jpeg_asset().essence.read(), new_file=data_with_exif)
    asset = madam.read(data_with_exif)
    essence_bytes = asset.essence.read()

    essence_exif = piexif.load(essence_bytes)

    for ifd, ifd_data in essence_exif.items():
        assert not ifd_data


@pytest.mark.parametrize('path, mime_type', [
    ('tests/resources/1x1-transparent.gif', None),
    ('tests/resources/16-bit-mono.wav', None),
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
    else:
        pytest.fail('No processor found for %r' % path)


def test_read_empty_file_raises_error():
    file_data = io.BytesIO()
    with pytest.raises(UnsupportedFormatError):
        madam.read(file_data)


def test_write_calls_write_method_for_respective_file_type(image_asset):
    with open(os.devnull, 'wb') as file:
        for processor in madam.core.processors:
            if processor.can_write(image_asset):
                with unittest.mock.patch.object(processor, 'write') as write_method:
                    madam.write(image_asset, file)
                assert write_method.called
                break
        else:
            pytest.fail('No processor found for %r' % image_asset)


def test_write_unknown_asset_type_raises_error():
    random_data = b'\x07]>e\x10\n+Y\x07\xd8\xf4\x90%\r\xbbK\xb8+\xf3v%\x0f\x11'
    asset = madam.core.Asset(random_data, metadata={})
    with pytest.raises(UnsupportedFormatError):
        with open(os.devnull) as file:
            madam.write(asset, file)
