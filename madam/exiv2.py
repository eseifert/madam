import io
import shutil
import tempfile

import pyexiv2
from bidict import bidict

from madam.core import MetadataProcessor, UnsupportedFormatError


class Exiv2MetadataProcessor(MetadataProcessor):
    """
    Represents a metadata processor using the exiv2 library.
    """
    __metadata_key_to_exiv2_key = bidict({
        # Exif
        'image.artist': 'Exif.Image.Artist',
        # IPTC
        'bylines': 'Iptc.Application2.Byline',
        'byline_titles': 'Iptc.Application2.BylineTitle',
        'caption': 'Iptc.Application2.Caption',
        'contacts': 'Iptc.Application2.Contact',
        'copyright': 'Iptc.Application2.Copyright',
        'creation_date': 'Iptc.Application2.DateCreated',
        'creation_time': 'Iptc.Application2.TimeCreated',
        'credit': 'Iptc.Application2.Credit',
        'expiration_date': 'Iptc.Application2.ExpirationDate',
        'expiration_time': 'Iptc.Application2.ExpirationTime',
        'headline': 'Iptc.Application2.Headline',
        'image_orientation': 'Iptc.Application2.ImageOrientation',
        'keywords': 'Iptc.Application2.Keywords',
        'language': 'Iptc.Application2.Language',
        'release_date': 'Iptc.Application2.ReleaseDate',
        'release_time': 'Iptc.Application2.ReleaseTime',
        'source': 'Iptc.Application2.Source',
        'subjects': 'Iptc.Application2.Subject',
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
        metadata_by_format = {}
        for format in self.formats:
            format_metadata = {}
            for key in getattr(metadata, format + '_keys'):
                madam_key = Exiv2MetadataProcessor.__metadata_key_to_exiv2_key.inv.get(key)
                if madam_key is not None:
                    format_metadata[madam_key] = metadata[key].value
            if format_metadata:
                metadata_by_format[format] = format_metadata
        return metadata_by_format

    def strip(self, file):
        result = io.BytesIO()
        with tempfile.NamedTemporaryFile() as tmp:
            tmp.write(file.read())
            tmp.flush()
            metadata = pyexiv2.ImageMetadata(tmp.name)
            try:
                metadata.read()
            except OSError:
                raise UnsupportedFormatError('Unknown file format.')
            metadata.clear()
            try:
                metadata.write()
            except OSError:
                raise UnsupportedFormatError('Unknown file format.')
            tmp.seek(0)

            shutil.copyfileobj(tmp, result)
            result.seek(0)

        return result

    def combine(self, essence, metadata_by_type):
        result = io.BytesIO()
        with tempfile.NamedTemporaryFile() as tmp:
            tmp.write(essence.read())
            tmp.flush()
            exiv2_metadata = pyexiv2.ImageMetadata(tmp.name)
            try:
                exiv2_metadata.read()
            except OSError:
                raise UnsupportedFormatError('Unknown essence format.')
            for metadata_type, metadata in metadata_by_type.items():
                for key in metadata:
                    try:
                        exiv2_key = Exiv2MetadataProcessor.__metadata_key_to_exiv2_key[key]
                        value_list = metadata[key] if isinstance(metadata[key], list) else [metadata[key]]
                        exiv2_metadata[exiv2_key] = value_list
                    except KeyError:
                        raise UnsupportedFormatError('Invalid metadata to be combined with essence: %s=%s' %
                                                     (metadata_type, metadata))
            exiv2_metadata.write()
            tmp.flush()
            tmp.seek(0)

            shutil.copyfileobj(tmp, result)
            result.seek(0)

        return result
