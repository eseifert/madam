import tempfile

import pyexiv2

from madam.core import UnsupportedFormatError

class Exiv2Processor:
    """
    Represents a metadata processor using the exiv2 library.
    """
    @property
    def format(self):
        return 'exif'

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
            exif[key] = metadata[key]
        return metadata

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
            return tmp.read()

    def combine(self, essence, metadata):
        with tempfile.NamedTemporaryFile() as tmp:
            tmp.write(essence.read())
            tmp.flush()
            exiv2 = pyexiv2.ImageMetadata(tmp.name)
            try:
                exiv2.read()
            except OSError:
                raise UnsupportedFormatError('Unknown essence format.')
            exiv2['Exif.Image.Artist'] = metadata['Exif.Image.Artist']
            exiv2.write()
            tmp.flush()
            tmp.seek(0)
            return tmp.read()
