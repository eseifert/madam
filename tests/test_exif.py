import io
import piexif
import pytest

from assets import jpeg_image_asset, png_image_asset_rgb, png_image_asset_rgb_alpha, png_image_asset_palette, \
    png_image_asset_gray, png_image_asset_gray_alpha, png_image_asset
import madam.exif
from madam.core import UnsupportedFormatError


class TestExifMetadataProcessor:
    @pytest.fixture
    def processor(self):
        return madam.exif.ExifMetadataProcessor()

    def test_stores_configuration(self):
        config = dict(foo='bar')
        processor = madam.exif.ExifMetadataProcessor(config)

        assert processor.config['foo'] == 'bar'

    def test_supports_exif(self, processor):
        assert 'exif' in processor.formats

    def test_read_returns_dicts_when_jpeg_contains_metadata(self, processor, jpeg_image_asset, tmpdir):
        file = tmpdir.join('asset_with_metadata.jpg')
        file.write(jpeg_image_asset.essence.read(), 'wb')
        metadata = piexif.load(str(file))
        metadata['0th'][piexif.ImageIFD.Artist] = 'Test artist'
        piexif.insert(piexif.dump(metadata), str(file))

        metadata = processor.read(io.BytesIO(file.read('rb')))

        assert set(metadata.keys()) == {'exif'}
        assert metadata['exif']['artist'] == 'Test artist'

    def test_read_fails_for_unsupported_format(self, processor, png_image_asset):
        non_jpeg_essence = png_image_asset.essence

        with pytest.raises(UnsupportedFormatError):
            processor.read(non_jpeg_essence)

    def test_read_ignores_unmapped_metadata(self, processor, jpeg_image_asset, tmpdir):
        file = tmpdir.join('asset_with_metadata.jpg')
        file.write(jpeg_image_asset.essence.read(), 'wb')
        metadata = piexif.load(str(file))
        metadata['0th'][piexif.ImageIFD.Artist] = 'Test artist'
        metadata['0th'][piexif.ImageIFD.TargetPrinter] = 'Printer'
        piexif.insert(piexif.dump(metadata), str(file))

        metadata = processor.read(io.BytesIO(file.read('rb')))

        assert set(metadata.keys()) == {'exif'}
        assert len(metadata['exif']) == 1
        assert metadata['exif']['artist'] == 'Test artist'

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
        metadata = piexif.load(str(file))
        metadata['0th'][piexif.ImageIFD.Artist] = 'Test artist'
        piexif.insert(piexif.dump(metadata), str(file))

        essence = processor.strip(file.open('rb'))

        essence_file = tmpdir.join('essence_without_metadata.jpg')
        essence_file.write(essence.read(), 'wb')
        metadata = piexif.load(str(essence_file))
        assert not any(metadata.values())

    def test_strip_raises_error_when_file_format_is_invalid(self, processor):
        junk_data = io.BytesIO(b'abc123')

        with pytest.raises(UnsupportedFormatError):
            processor.strip(junk_data)

    def test_combine_returns_essence_with_metadata(self, processor, jpeg_image_asset, tmpdir):
        metadata_formats = 'exif',
        essence = jpeg_image_asset.essence
        metadata = {k: v for k, v in jpeg_image_asset.metadata.items() if k in metadata_formats}

        essence_with_metadata = processor.combine(essence, metadata)

        essence_file = tmpdir.join('essence_with_metadata')
        essence_file.write(essence_with_metadata.read(), 'wb')
        read_metadata = piexif.load(str(essence_file))
        for metadata_format in metadata_formats:
            for madam_key, madam_value in metadata[metadata_format].items():
                ifd_key, exif_key = processor.metadata_to_exif[madam_key]
                exif_value = read_metadata[ifd_key][exif_key]
                convert_to_madam, _ = processor.converters[madam_key]
                assert convert_to_madam(exif_value) == madam_value

    def test_combine_raises_error_when_essence_format_is_invalid(self, processor, jpeg_image_asset):
        junk_data = io.BytesIO(b'abc123')
        exif = jpeg_image_asset.exif

        with pytest.raises(UnsupportedFormatError):
            processor.combine(junk_data, exif)

    def test_combine_raises_error_when_metadata_format_is_invalid(self, processor, jpeg_image_asset):
        exif = {'123abc': 'Test artist'}

        with pytest.raises(UnsupportedFormatError):
            processor.combine(jpeg_image_asset.essence, exif)  # noqa
