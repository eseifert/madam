import io
import pyexiv2
import pytest

from assets import jpeg_asset
from madam.core import UnsupportedFormatError
from madam.exiv2 import Exiv2Processor


class TestExiv2Processor:
    @pytest.fixture(name='processor')
    def exiv2_processor(self):
        return Exiv2Processor()

    def test_format_is_exif(self, processor):
        assert processor.format == 'exif'

    def test_read_returns_exif_dict_when_jpeg_contains_exif(self, processor, jpeg_asset, tmpdir):
        file = tmpdir.join('asset_with_exif.jpg')
        file.write(jpeg_asset.essence.read(), 'wb')
        metadata = pyexiv2.metadata.ImageMetadata(str(file))
        metadata.read()
        metadata['Exif.Image.Artist'] = b'Test artist'
        metadata.write()

        exif = processor.read(io.BytesIO(file.read('rb')))

        assert exif

    def test_read_raises_error_when_file_format_is_invalid(self, processor):
        junk_data = io.BytesIO(b'abc123')

        with pytest.raises(UnsupportedFormatError):
            processor.read(junk_data)

    def test_read_returns_empty_dict_when_jpeg_contains_no_exif(self, processor, jpeg_asset):
        data_without_exif = jpeg_asset.essence

        exif = processor.read(data_without_exif)

        assert not exif

    def test_strip_returns_essence_without_metadata(self, processor, jpeg_asset, tmpdir):
        file = tmpdir.join('asset_with_exif.jpg')
        file.write(jpeg_asset.essence.read(), 'wb')
        metadata = pyexiv2.metadata.ImageMetadata(str(file))
        metadata.read()
        metadata['Exif.Image.Artist'] = b'Test artist'
        metadata.write()

        essence = processor.strip(file.open('rb'))

        essence_file = tmpdir.join('essence_without_exif')
        essence_file.write(essence, 'wb')
        metadata = pyexiv2.metadata.ImageMetadata(str(essence_file))
        metadata.read()
        assert not metadata.keys()
