import datetime
import io
import shutil
import tempfile
from fractions import Fraction

import pyexiv2
from bidict import bidict

from madam.core import MetadataProcessor, UnsupportedFormatError


def _convert_sequence(dec_enc):
    return lambda exiv2_values: tuple(map(dec_enc[0], exiv2_values)), \
           lambda values: list(map(dec_enc[1], values))


def _convert_first(dec_enc):
    return lambda exiv2_values: dec_enc[0](exiv2_values[0]), \
           lambda value: [dec_enc[1](value)]


def _convert_mapping(mapping):
    bidi = bidict(mapping)
    return lambda exiv2_value: bidi[exiv2_value], \
           lambda value: bidi.inv[value]


class Exiv2MetadataProcessor(MetadataProcessor):
    """
    Represents a metadata processor using the exiv2 library.
    """
    metadata_to_exiv2 = bidict({
        # Exif
        'aperture': 'Exif.Photo.ApertureValue',
        'artist': 'Exif.Image.Artist',
        'brightness': 'Exif.Photo.BrightnessValue',
        'camera.manufacturer': 'Exif.Image.Make',
        'camera.model': 'Exif.Image.Model',
        'description': 'Exif.Image.ImageDescription',
        'exposure_time': 'Exif.Photo.ExposureTime',
        'firmware': 'Exif.Image.Software',
        'fnumber': 'Exif.Photo.FNumber',
        'focal_length': 'Exif.Photo.FocalLength',
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
        'shutter_speed': 'Exif.Photo.ShutterSpeedValue',
        'software': 'Exif.Image.ProcessingSoftware',
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

    __STRING = str, str
    __INT = int, int
    __RATIONAL = float, lambda value: Fraction(value).limit_denominator()
    __DATE = lambda exiv2_value: exiv2_value, lambda value: value
    __TIME = lambda exiv2_value: exiv2_value.replace(tzinfo=None), lambda value: value

    converters = {
        # Exif
        'aperture': __RATIONAL,
        'artist': __STRING,
        'brightness': __RATIONAL,
        'camera.manufacturer': __STRING,
        'camera.model': __STRING,
        'description': __STRING,
        'exposure_time': __RATIONAL,
        'firmware': __STRING,
        'fnumber': __RATIONAL,
        'focal_length': __RATIONAL,
        'focal_length_35mm': __INT,
        'gps.altitude': __RATIONAL,
        'gps.altitude_ref': _convert_mapping({'0': 'm_above_sea_level', '1': 'm_below_sea_level'}),
        'gps.latitude': _convert_sequence(__RATIONAL),
        'gps.latitude_ref': _convert_mapping({'N': 'north', 'S': 'south'}),
        'gps.longitude': _convert_sequence(__RATIONAL),
        'gps.longitude_ref': _convert_mapping({'E': 'east', 'W': 'west'}),
        'gps.map_datum': __STRING,
        'gps.speed': __RATIONAL,
        'gps.speed_ref': _convert_mapping({'K': 'km/h', 'M': 'mph', 'N': 'kn'}),
        'gps.date_stamp': __DATE,
        'gps.time_stamp':
            (lambda exiv2_val: datetime.time(*map(round, exiv2_val)),
             lambda val: [Fraction(val.hour), Fraction(val.minute), Fraction(val.second)]),
        'lens.manufacturer': __STRING,
        'lens.model': __STRING,
        'shutter_speed': __RATIONAL,
        'software': __STRING,
        # IPTC
        'bylines': _convert_sequence(__STRING),
        'byline_titles': _convert_sequence(__STRING),
        'caption': _convert_first(__STRING),
        'contacts': _convert_sequence(__STRING),
        'copyright': _convert_first(__STRING),
        'creation_date': _convert_first(__DATE),
        'creation_time': _convert_first(__TIME),
        'credit': _convert_first(__STRING),
        'expiration_date': _convert_first(__DATE),
        'expiration_time': _convert_first(__TIME),
        'headline': _convert_first(__STRING),
        'image_orientation': _convert_first(__STRING),
        'keywords': _convert_sequence(__STRING),
        'language': _convert_first(__STRING),
        'release_date': _convert_first(__DATE),
        'release_time': _convert_first(__TIME),
        'source': _convert_first(__STRING),
        'subjects': _convert_sequence(__STRING),
    }

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
            for exiv2_key in getattr(metadata, metadata_format + '_keys'):
                madam_key = Exiv2MetadataProcessor.metadata_to_exiv2.inv.get(exiv2_key)
                if madam_key is None:
                    continue
                exiv2_value = metadata[exiv2_key].value
                convert_to_madam, _ = Exiv2MetadataProcessor.converters[madam_key]
                format_metadata[madam_key] = convert_to_madam(exiv2_value)
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
                for madam_key, madam_value in metadata.items():
                    exiv2_key = Exiv2MetadataProcessor.metadata_to_exiv2.get(madam_key)
                    if exiv2_key is None:
                        continue
                    _, convert_to_exiv2 = Exiv2MetadataProcessor.converters[madam_key]
                    exiv2_metadata[exiv2_key] = convert_to_exiv2(madam_value)

            try:
                exiv2_metadata.write()
                tmp.flush()
                tmp.seek(0)
            except OSError:
                raise UnsupportedFormatError('Could not write metadata: %r' % metadata_by_format)

            shutil.copyfileobj(tmp, result)
            result.seek(0)

        return result
