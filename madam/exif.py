import datetime
import io
import shutil
import tempfile
from fractions import Fraction
from typing import Any, Callable, IO, Iterable, Mapping, Optional, Tuple

import piexif
from bidict import bidict

from madam.core import MetadataProcessor, UnsupportedFormatError
from madam.mime import MimeType


def _convert_sequence(dec_enc: Tuple[Callable, Callable]) -> Tuple[Callable, Callable]:
    return lambda exif_values: tuple(map(dec_enc[0], exif_values)), \
           lambda values: list(map(dec_enc[1], values))


def _convert_first(dec_enc: Tuple[Callable, Callable]) -> Tuple[Callable, Callable]:
    return lambda exif_values: dec_enc[0](exif_values[0]), \
           lambda value: [dec_enc[1](value)]


def _convert_mapping(mapping: Mapping) -> Tuple[Callable, Callable]:
    bidi = bidict(mapping)
    return lambda exif_value: bidi[exif_value], \
           lambda value: bidi.inv[value]


class ExifMetadataProcessor(MetadataProcessor):
    """
    Represents a metadata processor for Exif metadata.
    """
    supported_mime_types = {
        MimeType('image/jpeg'),
        MimeType('image/webp'),
    }

    metadata_to_exif = bidict({
        'aperture': ('Exif', piexif.ExifIFD.ApertureValue),
        'artist': ('0th', piexif.ImageIFD.Artist),
        'brightness': ('Exif', piexif.ExifIFD.BrightnessValue),
        'camera.manufacturer': ('0th', piexif.ImageIFD.Make),
        'camera.model': ('0th', piexif.ImageIFD.Model),
        'description': ('0th', piexif.ImageIFD.ImageDescription),
        'exposure_time': ('Exif', piexif.ExifIFD.ExposureTime),
        'firmware': ('0th', piexif.ImageIFD.Software),
        'fnumber': ('Exif', piexif.ExifIFD.FNumber),
        'focal_length': ('Exif', piexif.ExifIFD.FocalLength),
        'focal_length_35mm': ('Exif', piexif.ExifIFD.FocalLengthIn35mmFilm),
        'gps.altitude': ('GPS', piexif.GPSIFD.GPSAltitude),
        'gps.altitude_ref': ('GPS', piexif.GPSIFD.GPSAltitudeRef),
        'gps.latitude': ('GPS', piexif.GPSIFD.GPSLatitude),
        'gps.latitude_ref': ('GPS', piexif.GPSIFD.GPSLatitudeRef),
        'gps.longitude': ('GPS', piexif.GPSIFD.GPSLongitude),
        'gps.longitude_ref': ('GPS', piexif.GPSIFD.GPSLongitudeRef),
        'gps.map_datum': ('GPS', piexif.GPSIFD.GPSMapDatum),
        'gps.speed': ('GPS', piexif.GPSIFD.GPSSpeed),
        'gps.speed_ref': ('GPS', piexif.GPSIFD.GPSSpeedRef),
        'gps.date_stamp': ('GPS', piexif.GPSIFD.GPSDateStamp),
        'gps.time_stamp': ('GPS', piexif.GPSIFD.GPSTimeStamp),
        'lens.manufacturer': ('Exif', piexif.ExifIFD.LensMake),
        'lens.model': ('Exif', piexif.ExifIFD.LensModel),
        'orientation': ('0th', piexif.ImageIFD.Orientation),
        'shutter_speed': ('Exif', piexif.ExifIFD.ShutterSpeedValue),
        'software': ('0th', piexif.ImageIFD.ProcessingSoftware),
    })

    __STRING = lambda exif_val: exif_val.decode('utf-8'), lambda value: value.encode('utf-8')
    __INT = int, int
    __RATIONAL = lambda exif_val: float(Fraction(*exif_val)), \
                 lambda value: (Fraction(value).limit_denominator().numerator,
                                Fraction(value).limit_denominator().denominator)
    __DATE = lambda exif_val: datetime.datetime.strptime(exif_val.decode('utf-8'), '%Y:%m:%d').date(), \
             lambda value: value.strftime('%Y:%m:%d')
    __TIME = lambda exif_val: datetime.time(*map(lambda v: round(float(Fraction(*v))), exif_val)), \
             lambda value: ((value.hour, 1), (value.minute, 1), (value.second, 1))

    converters = {
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
        'gps.altitude_ref': _convert_mapping({0: 'm_above_sea_level', 1: 'm_below_sea_level'}),
        'gps.latitude': _convert_sequence(__RATIONAL),
        'gps.latitude_ref': _convert_mapping({b'N': 'north', b'S': 'south'}),
        'gps.longitude': _convert_sequence(__RATIONAL),
        'gps.longitude_ref': _convert_mapping({b'E': 'east', b'W': 'west'}),
        'gps.map_datum': __STRING,
        'gps.speed': __RATIONAL,
        'gps.speed_ref': _convert_mapping({b'K': 'km/h', b'M': 'mph', b'N': 'kn'}),
        'gps.date_stamp': __DATE,
        'gps.time_stamp': __TIME,
        'lens.manufacturer': __STRING,
        'lens.model': __STRING,
        'orientation': __INT,
        'shutter_speed': __RATIONAL,
        'software': __STRING,
    }

    def __init__(self, config: Optional[Mapping[str, Any]] = None) -> None:
        """
        Initializes a new `ExifMetadataProcessor`.

        :param config: Mapping with settings
        """
        super().__init__(config)

    @property
    def formats(self) -> Iterable[str]:
        return {'exif'}

    def read(self, file: IO) -> Mapping[str, Mapping]:
        with tempfile.NamedTemporaryFile(mode='wb') as tmp:
            tmp.write(file.read())
            tmp.flush()

            try:
                metadata = piexif.load(tmp.name)
            except (piexif.InvalidImageDataError, ValueError):
                raise UnsupportedFormatError('Unsupported file format.')

        metadata_by_format = {}
        for metadata_format in self.formats:
            format_metadata = {}
            for ifd_key, ifd_values in metadata.items():
                if not isinstance(ifd_values, dict):
                    continue
                for exif_key, exif_value in ifd_values.items():
                    madam_key = ExifMetadataProcessor.metadata_to_exif.inv.get((ifd_key, exif_key))
                    if madam_key is None:
                        continue
                    convert_to_madam, _ = ExifMetadataProcessor.converters[madam_key]
                    format_metadata[madam_key] = convert_to_madam(exif_value)
            if format_metadata:
                metadata_by_format[metadata_format] = format_metadata
        return metadata_by_format

    def strip(self, file: IO) -> IO:
        result = io.BytesIO()
        with tempfile.NamedTemporaryFile(mode='w+b') as tmp:
            tmp.write(file.read())
            tmp.flush()

            try:
                metadata = piexif.load(tmp.name)
                if any(metadata.values()):
                    open(tmp.name, 'rb').read()
                    piexif.remove(tmp.name)
            except (piexif.InvalidImageDataError, ValueError, UnboundLocalError):
                raise UnsupportedFormatError('Unsupported file format.')

            tmp.seek(0)
            shutil.copyfileobj(tmp, result)
            result.seek(0)

        return result

    def combine(self, essence: IO, metadata_by_format: Mapping[str, Mapping]) -> IO:
        result = io.BytesIO()
        with tempfile.NamedTemporaryFile(mode='w+b') as tmp:
            tmp.write(essence.read())
            tmp.flush()

            try:
                exif_metadata = piexif.load(tmp.name)
            except (piexif.InvalidImageDataError, ValueError):
                raise UnsupportedFormatError('Unsupported essence format.')

            for metadata_format, metadata in metadata_by_format.items():
                if metadata_format not in self.formats:
                    raise UnsupportedFormatError('Metadata format %r is not supported.' % metadata_format)
                for madam_key, madam_value in metadata.items():
                    if madam_key not in ExifMetadataProcessor.metadata_to_exif:
                        continue
                    ifd_key, exif_key = ExifMetadataProcessor.metadata_to_exif[madam_key]
                    if ifd_key not in exif_metadata:
                        exif_metadata[ifd_key] = {}
                    _, convert_to_exif = ExifMetadataProcessor.converters[madam_key]
                    exif_metadata[ifd_key][exif_key] = convert_to_exif(madam_value)

            try:
                piexif.insert(piexif.dump(exif_metadata), tmp.name)
            except (piexif.InvalidImageDataError, ValueError):
                raise UnsupportedFormatError('Could not write metadata: %r' % metadata_by_format)

            tmp.seek(0)
            shutil.copyfileobj(tmp, result)
            result.seek(0)

        return result
