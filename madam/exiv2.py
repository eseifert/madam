import tempfile

import pyexiv2

from core import UnsupportedFormatError

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
