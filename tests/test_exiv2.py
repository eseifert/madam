import io
import pyexiv2
import pytest

from assets import jpeg_image_asset, png_image_asset_rgb, png_image_asset_rgb_alpha, png_image_asset_palette, \
    png_image_asset_gray, png_image_asset_gray_alpha, png_image_asset
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

    def test_read_returns_dicts_when_jpeg_contains_metadata(self, processor, jpeg_image_asset, tmpdir):
        file = tmpdir.join('asset_with_metadata.jpg')
        file.write(jpeg_image_asset.essence.read(), 'wb')
        metadata = pyexiv2.metadata.ImageMetadata(str(file))
        metadata.read()
        metadata['Exif.Image.Artist'] = 'Test artist'
        metadata['Iptc.Application2.Caption'] = ['Foo bar']
        metadata.write()

        metadata = processor.read(io.BytesIO(file.read('rb')))

        assert metadata['exif']['artist'] == 'Test artist'
        assert metadata['iptc']['caption'] == 'Foo bar'
        assert set(metadata.keys()) == {'exif', 'iptc'}

    def test_read_fails_for_unsupported_format(self, processor, png_image_asset):
        non_jpeg_essence = png_image_asset.essence

        with pytest.raises(UnsupportedFormatError):
            processor.read(non_jpeg_essence)

    def test_read_ignores_unmapped_metadata(self, processor, jpeg_image_asset, tmpdir):
        file = tmpdir.join('asset_with_metadata.jpg')
        file.write(jpeg_image_asset.essence.read(), 'wb')
        metadata = pyexiv2.metadata.ImageMetadata(str(file))
        metadata.read()
        metadata['Exif.Image.Artist'] = 'Test artist'
        metadata['Exif.Image.TargetPrinter'] = 'Printer'
        metadata.write()

        metadata = processor.read(io.BytesIO(file.read('rb')))

        assert metadata['exif']['artist'] == 'Test artist'
        assert len(metadata['exif']) == 1
        assert set(metadata.keys()) == {'exif'}

    def test_read_raises_error_when_file_format_is_invalid(self, processor):
        junk_data = io.BytesIO(b'abc123')

        with pytest.raises(UnsupportedFormatError):
            processor.read(junk_data)

    def test_read_returns_empty_dict_when_jpeg_contains_no_metadata(self, processor, jpeg_image_asset):
        data_without_exif = jpeg_image_asset.essence

        metadata = processor.read(data_without_exif)

        assert not metadata

    def test_strip_returns_essence_without_metadata(self, processor, jpeg_image_asset, tmpdir):
        file = tmpdir.join('asset_with_metadata.jpg')
        file.write(jpeg_image_asset.essence.read(), 'wb')
        metadata = pyexiv2.metadata.ImageMetadata(str(file))
        metadata.read()
        metadata['Exif.Image.Artist'] = b'Test artist'
        metadata['Iptc.Application2.Caption'] = ['Foo bar']
        metadata.write()

        essence = processor.strip(file.open('rb'))

        essence_file = tmpdir.join('essence_without_metadata.jpg')
        essence_file.write(essence.read(), 'wb')
        metadata = pyexiv2.metadata.ImageMetadata(str(essence_file))
        metadata.read()
        assert not metadata.keys()

    def test_strip_raises_error_when_file_format_is_invalid(self, processor):
        junk_data = io.BytesIO(b'abc123')

        with pytest.raises(UnsupportedFormatError):
            processor.strip(junk_data)

    def test_combine_returns_essence_with_metadata(self, processor, jpeg_image_asset, tmpdir):
        metadata_formats = ('exif', 'iptc')
        essence = jpeg_image_asset.essence
        metadata = {k: v for k, v in jpeg_image_asset.metadata.items() if k in metadata_formats}

        essence_with_metadata = processor.combine(essence, metadata)

        essence_file = tmpdir.join('essence_with_metadata')
        essence_file.write(essence_with_metadata.read(), 'wb')
        read_metadata = pyexiv2.metadata.ImageMetadata(str(essence_file))
        read_metadata.read()
        for metadata_format in metadata_formats:
            for madam_key, madam_value in metadata[metadata_format].items():
                exiv2_key = processor.metadata_to_exiv2[madam_key]
                exiv2_value = read_metadata[exiv2_key].value
                convert_to_madam, _ = processor.converters[madam_key]
                assert convert_to_madam(exiv2_value) == madam_value

    def test_combine_raises_error_when_essence_format_is_invalid(self, processor, jpeg_image_asset):
        junk_data = io.BytesIO(b'abc123')
        exif = jpeg_image_asset.exif

        with pytest.raises(UnsupportedFormatError):
            processor.combine(junk_data, exif)

    def test_combine_raises_error_when_metadata_format_is_invalid(self, processor, jpeg_image_asset):
        exif = {'123abc': 'Test artist'}

        with pytest.raises(UnsupportedFormatError):
            processor.combine(jpeg_image_asset.essence, exif)
