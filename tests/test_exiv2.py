import io
import pyexiv2
import pytest

from assets import jpeg_asset
from madam.core import UnsupportedFormatError
from madam.exiv2 import Exiv2MetadataProcessor


class TestExiv2MetadataProcessor:
    @pytest.fixture(name='processor')
    def exiv2_metadata_processor(self):
        return Exiv2MetadataProcessor()

    def test_supports_exif(self, processor):
        assert 'exif' in processor.formats

    def test_supports_iptc(self, processor):
        assert 'iptc' in processor.formats

    def test_read_returns_exif_dict_when_jpeg_contains_metadata(self, processor, jpeg_asset, tmpdir):
        file = tmpdir.join('asset_with_exif.jpg')
        file.write(jpeg_asset.essence.read(), 'wb')
        metadata = pyexiv2.metadata.ImageMetadata(str(file))
        metadata.read()
        metadata['Exif.Image.Artist'] = 'Test artist'
        metadata.write()

        metadata = processor.read(io.BytesIO(file.read('rb')))

        assert metadata['exif']['image.artist'] == 'Test artist'
        assert len(metadata.keys()) == 1

    def test_read_raises_error_when_file_format_is_invalid(self, processor):
        junk_data = io.BytesIO(b'abc123')

        with pytest.raises(UnsupportedFormatError):
            processor.read(junk_data)

    def test_read_returns_empty_dict_when_jpeg_contains_no_metadata(self, processor, jpeg_asset):
        data_without_exif = jpeg_asset.essence

        metadata = processor.read(data_without_exif)

        assert not metadata

    def test_strip_returns_essence_without_metadata(self, processor, jpeg_asset, tmpdir):
        file = tmpdir.join('asset_with_exif.jpg')
        file.write(jpeg_asset.essence.read(), 'wb')
        metadata = pyexiv2.metadata.ImageMetadata(str(file))
        metadata.read()
        metadata['Exif.Image.Artist'] = b'Test artist'
        metadata.write()

        essence = processor.strip(file.open('rb'))

        essence_file = tmpdir.join('essence_without_exif')
        essence_file.write(essence.read(), 'wb')
        metadata = pyexiv2.metadata.ImageMetadata(str(essence_file))
        metadata.read()
        assert not metadata.keys()

    def test_strip_raises_error_when_file_format_is_invalid(self, processor):
        junk_data = io.BytesIO(b'abc123')

        with pytest.raises(UnsupportedFormatError):
            processor.strip(junk_data)

    def test_combine_returns_essence_with_metadata(self, processor, jpeg_asset, tmpdir):
        essence = jpeg_asset.essence
        metadata = {'exif': jpeg_asset.exif}

        essence_with_metadata = processor.combine(essence, metadata)

        essence_file = tmpdir.join('essence_with_metadata')
        essence_file.write(essence_with_metadata.read(), 'wb')
        read_metadata = pyexiv2.metadata.ImageMetadata(str(essence_file))
        read_metadata.read()
        for key in metadata['exif'].keys():
            assert read_metadata['Exif.'+key.title()].value == metadata['exif'][key]

    def test_combine_raises_error_when_essence_format_is_invalid(self, processor, jpeg_asset):
        junk_data = io.BytesIO(b'abc123')
        exif = jpeg_asset.exif

        with pytest.raises(UnsupportedFormatError):
            processor.combine(junk_data, exif)

    def test_combine_raises_error_when_metadata_format_is_invalid(self, processor, jpeg_asset):
        exif = {'123abc': 'Test artist'}

        with pytest.raises(UnsupportedFormatError):
            processor.combine(jpeg_asset.essence, exif)
