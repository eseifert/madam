import io
import tempfile

from bidict import bidict
import pyexiv2

from madam.core import MetadataProcessor, UnsupportedFormatError


class Exiv2Processor(MetadataProcessor):
    """
    Represents a metadata processor using the exiv2 library.
    """
    __metadata_key_to_exiv2_key = bidict({
        # Exif
        'image.artist': 'Exif.Image.Artist',
        # IPTC
        'caption': 'Iptc.Application2.Caption',
    })

    @property
    def formats(self):
        return 'exif', 'iptc'

    def read(self, file):
        with tempfile.NamedTemporaryFile() as tmp:
            tmp.write(file.read())
            tmp.flush()
            metadata = pyexiv2.ImageMetadata(tmp.name)
            try:
                metadata.read()
            except OSError:
                raise UnsupportedFormatError('Unknown file format.')
        exif = {}
        for key in metadata.exif_keys:
            madam_key = Exiv2Processor.__metadata_key_to_exiv2_key.inv[key]
            exif[madam_key] = metadata[key].value
        return exif

    def strip(self, file):
        with tempfile.NamedTemporaryFile() as tmp:
            tmp.write(file.read())
            tmp.flush()
            metadata = pyexiv2.ImageMetadata(tmp.name)
            try:
                metadata.read()
            except OSError:
                raise UnsupportedFormatError('Unknown file format.')
            metadata.clear()
            metadata.write()
            tmp.seek(0)
            return io.BytesIO(tmp.read())

    def combine(self, essence, metadata):
        with tempfile.NamedTemporaryFile() as tmp:
            tmp.write(essence.read())
            tmp.flush()
            exiv2_metadata = pyexiv2.ImageMetadata(tmp.name)
            try:
                exiv2_metadata.read()
            except OSError:
                raise UnsupportedFormatError('Unknown essence format.')
            for key in metadata.keys():
                try:
                    exiv2_key = Exiv2Processor.__metadata_key_to_exiv2_key[key]
                    exiv2_metadata[exiv2_key] = [metadata[key]]
                except KeyError:
                    raise UnsupportedFormatError('Invalid metadata to be combined with essence: %s' % metadata)
            exiv2_metadata.write()
            tmp.flush()
            tmp.seek(0)
            return io.BytesIO(tmp.read())
