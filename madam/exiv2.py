import tempfile

import pyexiv2


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
            metadata.read()
        exif = {}
        for key in metadata.exif_keys:
            exif[key] = metadata[key]
        return metadata
