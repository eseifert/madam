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
    metadata_to_exiv2 = bidict({
        # Exif
        'aperture': 'Exif.Image.ApertureValue',
        'artist': 'Exif.Image.Artist',
        'brightness': 'Exif.Image.BrightnessValue',
        'camera.manufacturer': 'Exif.Image.Make',
        'camera.model': 'Exif.Image.Model',
        'description': 'Exif.Image.ImageDescription',
        'exposure_time': 'Exif.Photo.ExposureTime',
        'fnumber': 'Exif.Image.FNumber',
        'focal_length': 'Exif.Image.FocalLength',
        'focal_length_35mm': 'Exif.Photo.FocalLengthIn35mmFilm',
        'gps.altitude': 'Exif.GPSInfo.GPSAltitude',
        'gps.altitude_ref': 'Exif.GPSInfo.GPSAltitudeRef',
        'gps.latitude': 'Exif.GPSInfo.GPSLatitude',
        'gps.latitude_ref': 'Exif.GPSInfo.GPSLatitudeRef',
        'gps.longitude': 'Exif.GPSInfo.GPSLongitude',
        'gps.longitude_ref': 'Exif.GPSInfo.GPSLongitudeRef',
        'gps.map_datum': 'Exif.GPSInfo.GPSMapDatum',
        'gps.speed': 'Exif.GPSInfo.GPSSpeed',
        'gps.speed_ref': 'Exif.GPSInfo.GPSSpeedRef',
        'gps.date_stamp': 'Exif.GPSInfo.GPSDateStamp',
        'gps.time_stamp': 'Exif.GPSInfo.GPSTimeStamp',
        'lens.manufacturer': 'Exif.Photo.LensMake',
        'lens.model': 'Exif.Photo.LensModel',
        'shutter_speed': 'Exif.Image.ShutterSpeedValue',
        'software': 'Exif.Image.Software',
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
        for metadata_format in self.formats:
            format_metadata = {}
            for key in getattr(metadata, metadata_format + '_keys'):
                madam_key = Exiv2MetadataProcessor.metadata_to_exiv2.inv.get(key)
                if madam_key is None:
                    continue
                value = metadata[key].value
                if isinstance(value, pyexiv2.utils.NotifyingList):
                    value = tuple(value)
                format_metadata[madam_key] = value
            if format_metadata:
                metadata_by_format[metadata_format] = format_metadata
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

            try:
                metadata.clear()
                metadata.write()
            except OSError:
                raise UnsupportedFormatError('Unknown file format.')
            tmp.seek(0)

            shutil.copyfileobj(tmp, result)
            result.seek(0)

        return result

    def combine(self, essence, metadata_by_format):
        result = io.BytesIO()
        with tempfile.NamedTemporaryFile() as tmp:
            tmp.write(essence.read())
            tmp.flush()
            exiv2_metadata = pyexiv2.ImageMetadata(tmp.name)

            try:
                exiv2_metadata.read()
            except OSError:
                raise UnsupportedFormatError('Unknown essence format.')

            for metadata_format, metadata in metadata_by_format.items():
                if metadata_format not in self.formats:
                    raise UnsupportedFormatError('Metadata format %r is not supported.' % metadata_format)
                for key, value in metadata.items():
                    exiv2_key = Exiv2MetadataProcessor.metadata_to_exiv2.get(key)
                    if exiv2_key is None:
                        continue
                    try:
                        exiv2_metadata[exiv2_key] = value
                    except TypeError as e:
                        raise TypeError('Could not set key %r: %s' % (key, e))

            try:
                exiv2_metadata.write()
                tmp.flush()
                tmp.seek(0)
            except OSError:
                raise UnsupportedFormatError('Could not write metadata: %r' % metadata_by_format)

            shutil.copyfileobj(tmp, result)
            result.seek(0)

        return result
