import io
import json
import multiprocessing
import os
import shutil
import subprocess
import tempfile
from collections import namedtuple
from math import ceil, cos, pi, radians, sin
from typing import Any, IO, Iterable, Mapping, MutableMapping, Optional, Sequence, Tuple, Union

from bidict import bidict

from madam.core import Asset, MetadataProcessor, Processor, operator, OperatorError, UnsupportedFormatError
from madam.mime import MimeType


def _probe(file: IO) -> Any:
    with tempfile.NamedTemporaryFile(mode='wb') as temp_in:
        shutil.copyfileobj(file, temp_in.file)
        temp_in.flush()
        file.seek(0)

        command = 'ffprobe -loglevel error -print_format json -show_format -show_streams'.split()
        command.append(temp_in.name)
        result = subprocess.run(command, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, check=True)

    string_result = result.stdout.decode('utf-8')
    json_obj = json.loads(string_result)

    return json_obj


def _combine_metadata(asset, *cloned_keys: str, **additional_metadata: Any) -> MutableMapping[str, Any]:
    metadata = {key: asset.metadata[key] for key in cloned_keys if key in asset.metadata}
    metadata.update(additional_metadata)
    return metadata


_FFmpegMode = namedtuple('_FFmpegMode', 'name, component_count, bits_per_pixel, readable, writeable, '
                                        'hw_accelerated, paletted, bitstream')


def _get_decoder_and_stream_type(probe_data: Mapping[str, Any]) -> Tuple[str, str]:
    decoder_name = probe_data['format']['format_name']

    stream_types = {stream['codec_type'] for stream in probe_data['streams']}
    if 'video' in stream_types:
        stream_type = 'video'
    elif 'audio' in stream_types:
        stream_type = 'audio'
    elif 'subtitle' in stream_types:
        stream_type = 'subtitle'
    else:
        stream_type = ''

    return decoder_name, stream_type


def _param_map_to_seq(param_mapping: Mapping[str, Any]) -> Sequence[str]:
    params = []
    for param, value in param_mapping.items():
        params.append('-{}'.format(param))
        if value is not None:
            params.append(str(value))
    return params


class _FFmpegContext(tempfile.TemporaryDirectory):
    def __init__(self, source: IO, result: IO) -> None:
        super().__init__(prefix='madam')
        self.__source = source
        self.__result = result

    def __enter__(self) -> '_FFmpegContext':
        tmpdir_path = super().__enter__()
        self.input_path = os.path.join(tmpdir_path, 'input_file')
        self.output_path = os.path.join(tmpdir_path, 'output_file')

        with open(self.input_path, 'wb') as temp_in:
            shutil.copyfileobj(self.__source, temp_in)
            self.__source.seek(0)

        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if os.path.exists(self.output_path):
            with open(self.output_path, 'rb') as temp_out:
                shutil.copyfileobj(temp_out, self.__result)
                self.__result.seek(0)

        super().__exit__(exc_type, exc_val, exc_tb)


class FFmpegProcessor(Processor):
    """
    Represents a processor that uses FFmpeg to read audio and video data.

    The minimum version of FFmpeg required is v3.3.
    """

    __decoder_and_stream_type_to_mime_type = {
        ('matroska,webm', 'video'): MimeType('video/x-matroska'),
        ('mov,mp4,m4a,3gp,3g2,mj2', 'video'): MimeType('video/quicktime'),
        ('avi', 'video'): MimeType('video/x-msvideo'),
        ('mpegts', 'video'): MimeType('video/mp2t'),
        ('nut', 'video'): MimeType('video/x-nut'),
        ('ogg', 'video'): MimeType('video/ogg'),
        ('mp3', 'audio'): MimeType('audio/mpeg'),
        ('nut', 'audio'): MimeType('audio/x-nut'),
        ('ogg', 'audio'): MimeType('audio/ogg'),
        ('wav', 'audio'): MimeType('audio/wav'),
        ('webvtt', 'subtitle'): MimeType('text/vtt'),
    }

    __mime_type_to_encoder = {
        MimeType('video/x-matroska'): 'matroska',
        MimeType('video/quicktime'): 'mov',
        MimeType('video/x-msvideo'): 'avi',
        MimeType('video/mp2t'): 'mpegts',
        MimeType('video/x-nut'): 'nut',
        MimeType('video/ogg'): 'ogg',
        MimeType('audio/mpeg'): 'mp3',
        MimeType('audio/x-nut'): 'nut',
        MimeType('audio/ogg'): 'ogg',
        MimeType('audio/wav'): 'wav',
        MimeType('image/bmp'): 'image2',
        MimeType('image/gif'): 'gif',
        MimeType('image/jpeg'): 'image2',
        MimeType('image/png'): 'image2',
        MimeType('image/tiff'): 'image2',
        MimeType('image/webp'): 'image2',
        MimeType('text/vnd.dvb.subtitle'): 'dvbsub',
        MimeType('text/vtt'): 'webvtt',
    }

    __mime_type_to_codec = {
        MimeType('image/bmp'): 'bmp',
        MimeType('image/gif'): 'gif',
        MimeType('image/jpeg'): 'mjpeg',
        MimeType('image/png'): 'png',
        MimeType('image/tiff'): 'tiff',
        MimeType('image/webp'): 'libwebp',
    }

    __codec_options = {
        'video': {
            'libx264': {
                'preset': 'slow',
                'crf': 23,
            },
            'libx265': {
                'preset': 'slow',
                'crf': 28,
            },
            'libvpx': {
                'speed': 1,
                'crf': 10,
            },
            'libvpx-vp9': {
                'speed': 1,
                'row-mt': 1,
                'crf': 32,
            },
            'opus': {
                'strict': -2
            },
            'vorbis': {
                'ac': 2,
                'strict': -2
            },
            'vp9': {
                'speed': 1,
                'tile-columns': 6,
                'crf': 32,
            },
        }
    }

    __container_options = {
        MimeType('video/x-matroska'): [
            '-avoid_negative_ts', 'make_zero',
        ],
    }

    __ffmpeg_pix_fmt_to_color_mode = {
        # Luminance
        'gray': ('LUMA', 8, 'uint'),
        'gray9be': ('LUMA', 9, 'uint'),
        'gray9le': ('LUMA', 9, 'uint'),
        'gray10be': ('LUMA', 10, 'uint'),
        'gray10le': ('LUMA', 10, 'uint'),
        'gray12be': ('LUMA', 12, 'uint'),
        'gray12le': ('LUMA', 12, 'uint'),
        'gray16be': ('LUMA', 16, 'uint'),
        'gray16le': ('LUMA', 16, 'uint'),
        # Luminance, alpha
        'monob': ('LUMA', 1, 'uint'),
        'monow': ('LUMA', 1, 'uint'),
        'ya8': ('LUMAA', 8, 'uint'),
        'ya16be': ('LUMAA', 16, 'uint'),
        'ya16le': ('LUMAA', 16, 'uint'),
        # Palette
        'pal8': ('PALETTE', 8, 'uint'),
        # Red, green, blue
        'bayer_bggr8': ('RGB', 8, 'uint'),
        'bayer_bggr16be': ('RGB', 16, 'uint'),
        'bayer_bggr16le': ('RGB', 16, 'uint'),
        'bayer_gbrg8': ('RGB', 8, 'uint'),
        'bayer_gbrg16be': ('RGB', 16, 'uint'),
        'bayer_gbrg16le': ('RGB', 16, 'uint'),
        'bayer_grbg8': ('RGB', 8, 'uint'),
        'bayer_grbg16be': ('RGB', 16, 'uint'),
        'bayer_grbg16le': ('RGB', 16, 'uint'),
        'bayer_rggb8': ('RGB', 8, 'uint'),
        'bayer_rggb16be': ('RGB', 16, 'uint'),
        'bayer_rggb16le': ('RGB', 16, 'uint'),
        'bgr4': ('RGB', 8, 'uint'),
        'bgr4_byte': ('RGB', 8, 'uint'),
        'bgr24': ('RGB', 8, 'uint'),
        'bgr48be': ('RGB', 16, 'uint'),
        'bgr48le': ('RGB', 16, 'uint'),
        'bgr444be': ('RGB', 8, 'uint'),
        'bgr444le': ('RGB', 8, 'uint'),
        'bgr555be': ('RGB', 8, 'uint'),
        'bgr555le': ('RGB', 8, 'uint'),
        'bgr565be': ('RGB', 8, 'uint'),
        'bgr565le': ('RGB', 8, 'uint'),
        'bgr8': ('RGB', 8, 'uint'),
        'gbrp': ('RGB', 8, 'uint'),
        'gbrp9be': ('RGB', 9, 'uint'),
        'gbrp9le': ('RGB', 9, 'uint'),
        'gbrp10be': ('RGB', 10, 'uint'),
        'gbrp10le': ('RGB', 10, 'uint'),
        'gbrp12be': ('RGB', 12, 'uint'),
        'gbrp12le': ('RGB', 12, 'uint'),
        'gbrp14be': ('RGB', 14, 'uint'),
        'gbrp14le': ('RGB', 14, 'uint'),
        'gbrp16be': ('RGB', 16, 'uint'),
        'gbrp16le': ('RGB', 16, 'uint'),
        'gbrpf32be': ('RGB', 32, 'float'),
        'gbrpf32le': ('RGB', 32, 'float'),
        'rgb4': ('RGB', 8, 'uint'),
        'rgb4_byte': ('RGB', 8, 'uint'),
        'rgb24': ('RGB', 8, 'uint'),
        'rgb48be': ('RGB', 16, 'uint'),
        'rgb48le': ('RGB', 16, 'uint'),
        'rgb444be': ('RGB', 8, 'uint'),
        'rgb444le': ('RGB', 8, 'uint'),
        'rgb555be': ('RGB', 8, 'uint'),
        'rgb555le': ('RGB', 8, 'uint'),
        'rgb565be': ('RGB', 8, 'uint'),
        'rgb565le': ('RGB', 8, 'uint'),
        'rgb8': ('RGB', 8, 'uint'),
        # Red, green, blue, alpha
        'abgr': ('RGBA', 8, 'uint'),
        'argb': ('RGBA', 8, 'uint'),
        'bgra': ('RGBA', 8, 'uint'),
        'bgra64be': ('RGBA', 16, 'uint'),
        'bgra64le': ('RGBA', 16, 'uint'),
        'gbrap': ('RGBA', 8, 'uint'),
        'gbrap10be': ('RGBA', 16, 'uint'),
        'gbrap10le': ('RGBA', 16, 'uint'),
        'gbrap12be': ('RGBA', 16, 'uint'),
        'gbrap12le': ('RGBA', 16, 'uint'),
        'gbrap16be': ('RGBA', 16, 'uint'),
        'gbrap16le': ('RGBA', 16, 'uint'),
        'gbrapf32be': ('RGBA', 32, 'float'),
        'gbrapf32le': ('RGBA', 32, 'float'),
        'rgba': ('RGBA', 8, 'uint'),
        'rgba64be': ('RGBA', 16, 'uint'),
        'rgba64le': ('RGBA', 16, 'uint'),
        # Red, green, blue, padding
        '0bgr': ('RGBX', 8, 'uint'),
        '0rgb': ('RGBX', 8, 'uint'),
        'bgr0': ('RGBX', 8, 'uint'),
        'rgb0': ('RGBX', 8, 'uint'),
        # X, Y, Z
        'xyz12be': ('XYZ', 12, 'uint'),
        'xyz12le': ('XYZ', 12, 'uint'),
        # Luminance, blue-difference chrominance, red-difference chrominance
        'nv12': ('YUV', 8, 'uint'),
        'nv16': ('YUV', 8, 'uint'),
        'nv20be': ('YUV', 8, 'uint'),
        'nv20le': ('YUV', 8, 'uint'),
        'nv21': ('YUV', 8, 'uint'),
        'p010be': ('YUV', 10, 'uint'),
        'p010le': ('YUV', 10, 'uint'),
        'p016be': ('YUV', 16, 'uint'),
        'p016le': ('YUV', 16, 'uint'),
        'uyvy422': ('YUV', 8, 'uint'),
        'uyyvyy411': ('YUV', 8, 'uint'),
        'yuv410p': ('YUV', 8, 'uint'),
        'yuv411p': ('YUV', 8, 'uint'),
        'yuv420p': ('YUV', 8, 'uint'),
        'yuv420p9be': ('YUV', 9, 'uint'),
        'yuv420p9le': ('YUV', 9, 'uint'),
        'yuv420p10be': ('YUV', 10, 'uint'),
        'yuv420p10le': ('YUV', 10, 'uint'),
        'yuv420p12be': ('YUV', 12, 'uint'),
        'yuv420p12le': ('YUV', 12, 'uint'),
        'yuv420p14be': ('YUV', 14, 'uint'),
        'yuv420p14le': ('YUV', 14, 'uint'),
        'yuv420p16be': ('YUV', 16, 'uint'),
        'yuv420p16le': ('YUV', 16, 'uint'),
        'yuv422p': ('YUV', 8, 'uint'),
        'yuv422p9be': ('YUV', 9, 'uint'),
        'yuv422p9le': ('YUV', 9, 'uint'),
        'yuv422p10be': ('YUV', 10, 'uint'),
        'yuv422p10le': ('YUV', 10, 'uint'),
        'yuv422p12be': ('YUV', 12, 'uint'),
        'yuv422p12le': ('YUV', 12, 'uint'),
        'yuv422p14be': ('YUV', 14, 'uint'),
        'yuv422p14le': ('YUV', 14, 'uint'),
        'yuv422p16be': ('YUV', 16, 'uint'),
        'yuv422p16le': ('YUV', 16, 'uint'),
        'yuv440p': ('YUV', 8, 'uint'),
        'yuv440p10be': ('YUV', 10, 'uint'),
        'yuv440p10le': ('YUV', 10, 'uint'),
        'yuv440p12be': ('YUV', 12, 'uint'),
        'yuv440p12le': ('YUV', 12, 'uint'),
        'yuv444p': ('YUV', 8, 'uint'),
        'yuv444p9be': ('YUV', 9, 'uint'),
        'yuv444p9le': ('YUV', 9, 'uint'),
        'yuv444p10be': ('YUV', 10, 'uint'),
        'yuv444p10le': ('YUV', 10, 'uint'),
        'yuv444p12be': ('YUV', 12, 'uint'),
        'yuv444p12le': ('YUV', 12, 'uint'),
        'yuv444p14be': ('YUV', 14, 'uint'),
        'yuv444p14le': ('YUV', 14, 'uint'),
        'yuv444p16be': ('YUV', 16, 'uint'),
        'yuv444p16le': ('YUV', 16, 'uint'),
        'yuvj411p': ('YUV', 8, 'uint'),
        'yuvj420p': ('YUV', 8, 'uint'),
        'yuvj422p': ('YUV', 8, 'uint'),
        'yuvj440p': ('YUV', 8, 'uint'),
        'yuvj444p': ('YUV', 8, 'uint'),
        'yuyv422': ('YUV', 8, 'uint'),
        'yvyu422': ('YUV', 8, 'uint'),
        # Luminance, blue-difference chrominance, red-difference chrominance, alpha
        'ayuv64be': ('YUVA', 16, 'uint'),
        'ayuv64le': ('YUVA', 16, 'uint'),
        'yuva420p': ('YUVA', 8, 'uint'),
        'yuva420p9be': ('YUVA', 9, 'uint'),
        'yuva420p9le': ('YUVA', 9, 'uint'),
        'yuva420p10be': ('YUVA', 10, 'uint'),
        'yuva420p10le': ('YUVA', 10, 'uint'),
        'yuva420p16be': ('YUVA', 16, 'uint'),
        'yuva420p16le': ('YUVA', 16, 'uint'),
        'yuva422p': ('YUVA', 8, 'uint'),
        'yuva422p9be': ('YUVA', 9, 'uint'),
        'yuva422p9le': ('YUVA', 9, 'uint'),
        'yuva422p10be': ('YUVA', 10, 'uint'),
        'yuva422p10le': ('YUVA', 10, 'uint'),
        'yuva422p16be': ('YUVA', 16, 'uint'),
        'yuva422p16le': ('YUVA', 16, 'uint'),
        'yuva444p': ('YUVA', 8, 'uint'),
        'yuva444p9be': ('YUVA', 9, 'uint'),
        'yuva444p9le': ('YUVA', 9, 'uint'),
        'yuva444p10be': ('YUVA', 10, 'uint'),
        'yuva444p10le': ('YUVA', 10, 'uint'),
        'yuva444p16be': ('YUVA', 16, 'uint'),
        'yuva444p16le': ('YUVA', 16, 'uint'),
    }

    __color_mode_to_ffmpeg_pix_fmt = {
        ('LUMA', 1, 'uint'): 'monob',
        ('LUMA', 8, 'uint'): 'gray',
        ('LUMA', 9, 'uint'): 'gray9le',
        ('LUMA', 10, 'uint'): 'gray10le',
        ('LUMA', 12, 'uint'): 'gray12le',
        ('LUMA', 16, 'uint'): 'gray16le',
        ('LUMAA', 8, 'uint'): 'ya8',
        ('LUMAA', 16, 'uint'): 'ya16le',
        ('PALETTE', 8, 'uint'): 'pal8',
        ('RGB', 8, 'uint'): 'rgb24',
        ('RGB', 9, 'uint'): 'gbrp9le',
        ('RGB', 10, 'uint'): 'gbrp10le',
        ('RGB', 12, 'uint'): 'gbrp12le',
        ('RGB', 16, 'uint'): 'rgb48le',
        ('RGB', 32, 'float'): 'gbrpf32le',
        ('RGBA', 8, 'uint'): 'rgba',
        ('RGBA', 16, 'uint'): 'rgba64le',
        ('RGBA', 32, 'float'): 'gbrapf32le',
        ('RGBX', 8, 'uint'): 'rgb0',
        ('XYZ', 12, 'uint'): 'xyz12le',
        ('YUV', 8, 'uint'): 'yuv420p',
        ('YUV', 9, 'uint'): 'yuv420p9le',
        ('YUV', 10, 'uint'): 'yuv420p10le',
        ('YUV', 12, 'uint'): 'yuv420p12le',
        ('YUV', 14, 'uint'): 'yuv420p14le',
        ('YUV', 16, 'uint'): 'yuv420p16le',
        ('YUVA', 8, 'uint'): 'yuva420p',
        ('YUVA', 9, 'uint'): 'yuva420p9le',
        ('YUVA', 10, 'uint'): 'yuva420p10le',
        ('YUVA', 16, 'uint'): 'yuva420p16le',
    }

    def __init__(self, config: Optional[Mapping[str, Any]] = None) -> None:
        """
        Initializes a new `FFmpegProcessor`.

        :param config: Mapping with settings.
        :raises EnvironmentError: if the installed version of ffprobe does not match the minimum version requirement
        """
        super().__init__(config)

        self._min_version = '3.3'
        command = 'ffprobe -version'.split()
        result = subprocess.run(command, stdout=subprocess.PIPE)
        string_result = result.stdout.decode('utf-8')
        version_string = string_result.split()[2]
        if version_string < self._min_version:
            raise EnvironmentError('Found ffprobe version %s. Requiring at least version %s.'
                                   % (version_string, self._min_version))

        self.__threads = multiprocessing.cpu_count()

    def can_read(self, file: IO) -> bool:
        try:
            probe_data = _probe(file)
            decoder_and_stream_type = _get_decoder_and_stream_type(probe_data)
            mime_type = self.__decoder_and_stream_type_to_mime_type.get(decoder_and_stream_type)
            return bool(mime_type)
        except subprocess.CalledProcessError:
            return False

    def read(self, file: IO) -> Asset:
        try:
            probe_data = _probe(file)
        except subprocess.CalledProcessError:
            raise UnsupportedFormatError('Unsupported file format.')

        decoder_and_stream_type = _get_decoder_and_stream_type(probe_data)
        mime_type = self.__decoder_and_stream_type_to_mime_type.get(decoder_and_stream_type)
        if not mime_type:
            raise UnsupportedFormatError('Unsupported metadata source.')

        metadata = dict(
            mime_type=str(mime_type),
        )

        if 'duration' in probe_data['format']:
            metadata['duration'] = float(probe_data['format']['duration'])

        for stream in probe_data['streams']:
            stream_type = stream.get('codec_type')
            if stream_type in {'video', 'audio', 'subtitle'}:
                # Only use first stream
                if stream_type in metadata:
                    break
                metadata[stream_type] = {}
            if 'width' in stream:
                metadata['width'] = max(stream['width'], metadata.get('width', 0))
            if 'height' in stream:
                metadata['height'] = max(stream['height'], metadata.get('height', 0))
            if stream_type not in metadata:
                continue
            if 'codec_name' in stream:
                metadata[stream_type]['codec'] = stream['codec_name']
            if 'bit_rate' in stream:
                metadata[stream_type]['bitrate'] = float(stream['bit_rate'])/1000.0
            if 'pix_fmt' in stream:
                color_space, depth, data_type = FFmpegProcessor.__ffmpeg_pix_fmt_to_color_mode[stream['pix_fmt']]
                metadata[stream_type]['color_space'] = color_space
                metadata[stream_type]['depth'] = depth
                metadata[stream_type]['data_type'] = data_type

        return Asset(essence=file, **metadata)

    @operator
    def resize(self, asset: Asset, width: int, height: int) -> Asset:
        """
        Creates a new image or video asset of the specified width and height
        from the essence of the specified image or video asset.

        Width and height must be positive numbers.

        :param asset: Video asset that will serve as the source for the frame
        :type asset: Asset
        :param width: Width of the resized asset
        :type width: int
        :param height: Height of the resized asset
        :type height: int
        :return: New asset with specified width and height
        :rtype: Asset
        """
        if width < 1 or height < 1:
            raise ValueError('Invalid dimensions: %dx%d' % (width, height))

        mime_type = MimeType(asset.mime_type)
        encoder_name = self.__mime_type_to_encoder.get(mime_type)
        if not encoder_name:
            raise UnsupportedFormatError('Unsupported asset type: %s' % mime_type)
        if mime_type.type not in ('image', 'video'):
            raise OperatorError('Cannot resize asset of type %s')

        result = io.BytesIO()
        with _FFmpegContext(asset.essence, result) as ctx:
            with open(ctx.input_path, 'wb') as temp_in:
                shutil.copyfileobj(asset.essence, temp_in)
                temp_in.flush()

            command = ['ffmpeg', '-loglevel', 'error',
                       '-f', encoder_name, '-i', ctx.input_path,
                       '-filter:v', 'scale=%d:%d' % (width, height),
                       '-threads', str(self.__threads),
                       '-f', encoder_name, '-y', ctx.output_path]

            try:
                subprocess.run(command, stderr=subprocess.PIPE, check=True)
            except subprocess.CalledProcessError as ffmpeg_error:
                error_message = ffmpeg_error.stderr.decode('utf-8')
                raise OperatorError('Could not resize asset: %s' % error_message)

        metadata = _combine_metadata(asset,
                                     'mime_type', 'duration', 'video', 'audio', 'subtitle',
                                     width=width, height=height)

        return Asset(essence=result, **metadata)

    @operator
    def convert(self, asset: Asset, mime_type: Union[MimeType, str],
                video: Optional[Mapping[str, Any]] = None,
                audio: Optional[Mapping[str, Any]] = None,
                subtitle: Optional[Mapping[str, Any]] = None) -> Asset:
        """
        Creates a new asset of the specified MIME type from the essence of the
        specified asset.

        Additional options can be specified for video, audio, and subtitle streams.
        Options are passed as dictionary instances and can contain various keys for
        each stream type.

        **Options for video streams:**

        - **codec** – Processor-specific name of the video codec as string
        - **bitrate** – Target bitrate in kBit/s as float number

        **Options for audio streams:**

        - **codec** – Processor-specific name of the audio codec as string
        - **bitrate** – Target bitrate in kBit/s as float number

        **Options for subtitle streams:**

        - **codec** – Processor-specific name of the subtitle format as string

        :param asset: Asset whose contents will be converted
        :type asset: Asset
        :param mime_type: MIME type of the video container
        :type mime_type: MimeType or str
        :param video: Dictionary with options for video streams.
        :type video: dict or None
        :param audio: Dictionary with options for audio streams.
        :type audio: dict or None
        :param subtitle: Dictionary with the options for subtitle streams.
        :type subtitle: dict or None
        :return: New asset with converted essence
        :rtype: Asset
        """
        mime_type = MimeType(mime_type)
        encoder_name = self.__mime_type_to_encoder.get(mime_type)
        if not encoder_name:
            raise UnsupportedFormatError('Unsupported asset type: %s' % mime_type)

        result = io.BytesIO()
        with _FFmpegContext(asset.essence, result) as ctx:
            command = ['ffmpeg', '-loglevel', 'error',
                       '-i', ctx.input_path]
            if video:
                if 'codec' in video:
                    if video['codec']:
                        command.extend(['-c:v', video['codec']])
                        codec_options = dict(FFmpegProcessor.__codec_options.get('video', {}).get(video['codec'], []))
                        codec_config = self.config.get('codec/{}'.format(video['codec']), {})
                        if 'crf' in codec_config:
                            codec_options['crf'] = int(codec_config['crf'])
                        command.extend(_param_map_to_seq(codec_options))
                    else:
                        command.extend(['-vn'])
                if video.get('bitrate'):
                    # Set minimum at 50% of bitrate and maximum at 145% of bitrate
                    # (see https://developers.google.com/media/vp9/settings/vod/)
                    command.extend(['-minrate', '%dk' % round(0.5*video['bitrate']),
                                    '-b:v', '%dk' % video['bitrate'],
                                    '-maxrate', '%dk' % round(1.45*video['bitrate'])])
                if video.get('color_space') or video.get('depth') or video.get('data_type'):
                    color_mode = (
                        video.get('color_space', asset.video.get('color_space', 'YUV')),
                        video.get('depth', asset.video.get('depth', 8)),
                        video.get('data_type', asset.video.get('data_type', 'uint')),
                    )
                    ffmpeg_pix_fmt = FFmpegProcessor.__color_mode_to_ffmpeg_pix_fmt.get(color_mode)
                    if ffmpeg_pix_fmt:
                        command.extend(['-pix_fmt', ffmpeg_pix_fmt])
            if audio:
                if 'codec' in audio:
                    if audio['codec']:
                        command.extend(['-c:a', audio['codec']])
                        codec_options = FFmpegProcessor.__codec_options.get('audio', {}).get(audio['codec'], [])
                        command.extend(codec_options)
                    else:
                        command.extend(['-an'])
                if audio.get('bitrate'):
                    command.extend(['-b:a', '%dk' % audio['bitrate']])
            if subtitle:
                if 'codec' in subtitle:
                    if subtitle['codec']:
                        command.extend(['-c:s', subtitle['codec']])
                        codec_options = FFmpegProcessor.__codec_options.get('subtitles', {})
                        command.extend(codec_options.get(subtitle['codec'], []))
                    else:
                        command.extend(['-sn'])

            container_options = FFmpegProcessor.__container_options.get(mime_type, [])
            container_config = self.config.get(mime_type, {})
            if mime_type == 'video/quicktime':
                use_faststart = container_config.get('faststart', True)
                if use_faststart:
                    container_options.extend(['-movflags', '+faststart'])
            command.extend(container_options)

            command.extend(['-threads', str(self.__threads),
                            '-f', encoder_name, '-y', ctx.output_path])

            try:
                subprocess.run(command, stderr=subprocess.PIPE, check=True)
            except subprocess.CalledProcessError as ffmpeg_error:
                error_message = ffmpeg_error.stderr.decode('utf-8')
                raise OperatorError('Could not convert asset: %s' % error_message)

        return self.read(result)

    @operator
    def trim(self, asset: Asset, from_seconds: float = 0, to_seconds: float = 0) -> Asset:
        """
        Creates a trimmed audio or video asset that only contains the data
        between from_seconds and to_seconds.

        :param asset: Audio or video asset, which will serve as the source
        :type asset: Asset
        :param from_seconds: Start time of the clip in seconds
        :type from_seconds: float
        :param to_seconds: End time of the clip in seconds
        :type to_seconds: float
        :return: New asset with trimmed essence
        :rtype: Asset
        """
        mime_type = MimeType(asset.mime_type)
        encoder_name = self.__mime_type_to_encoder.get(mime_type)
        if not encoder_name or mime_type.type not in ('audio', 'video'):
            raise UnsupportedFormatError('Unsupported source asset type: %s' % mime_type)

        if to_seconds <= 0:
            to_seconds = asset.duration + to_seconds

        duration = float(to_seconds) - float(from_seconds)

        if duration <= 0:
            raise ValueError('Start time must be before end time')

        result = io.BytesIO()
        with _FFmpegContext(asset.essence, result) as ctx:
            command = ['ffmpeg', '-v', 'error',
                       '-ss', str(float(from_seconds)), '-t', str(duration),
                       '-i', ctx.input_path, '-codec', 'copy',
                       '-f', encoder_name, '-y', ctx.output_path]

            try:
                subprocess.run(command, stderr=subprocess.PIPE, check=True)
            except subprocess.CalledProcessError as ffmpeg_error:
                error_message = ffmpeg_error.stderr.decode('utf-8')
                raise OperatorError('Could not trim asset: %s' % error_message)

        metadata = _combine_metadata(asset,
                                     'mime_type', 'width', 'height', 'video', 'audio', 'subtitle',
                                     duration=duration)

        return Asset(essence=result, **metadata)

    @operator
    def extract_frame(self, asset: Asset, mime_type: Union[MimeType, str], seconds: float = 0) -> Asset:
        """
        Creates a new image asset of the specified MIME type from the essence
        of the specified video asset.

        :param asset: Video asset which will serve as the source for the frame
        :type asset: Asset
        :param mime_type: MIME type of the destination image
        :type mime_type: MimeType or str
        :param seconds: Offset of the frame in seconds
        :type seconds: float
        :return: New image asset with converted essence
        :rtype: Asset
        """
        source_mime_type = MimeType(asset.mime_type)
        if source_mime_type.type != 'video':
            raise UnsupportedFormatError('Unsupported source asset type: %s' % source_mime_type)

        mime_type = MimeType(mime_type)
        encoder_name = self.__mime_type_to_encoder.get(mime_type)
        codec_name = self.__mime_type_to_codec.get(mime_type)
        if not (encoder_name and codec_name):
            raise UnsupportedFormatError('Unsupported target asset type: %s' % mime_type)

        result = io.BytesIO()
        with _FFmpegContext(asset.essence, result) as ctx:
            command = ['ffmpeg', '-v', 'error',
                       '-i', ctx.input_path,
                       '-ss', str(float(seconds)),
                       '-codec:v', codec_name, '-vframes', '1',
                       '-f', encoder_name, '-y', ctx.output_path]

            try:
                subprocess.run(command, stderr=subprocess.PIPE, check=True)
            except subprocess.CalledProcessError as ffmpeg_error:
                error_message = ffmpeg_error.stderr.decode('utf-8')
                raise OperatorError('Could not extract frame from asset: %s' % error_message)

        metadata = _combine_metadata(asset,
                                     'width', 'height',
                                     mime_type=mime_type)
        if 'video' in asset.metadata:
            metadata['depth'] = asset.metadata['video']['depth']

        return Asset(essence=result, **metadata)

    @operator
    def crop(self, asset: Asset, x: int, y: int, width: int, height: int) -> Asset:
        """
        Creates a cropped video asset whose essence is cropped to the specified
        rectangular area.

        :param asset: Video asset whose contents will be cropped
        :type asset: Asset
        :param x: Horizontal offset of the cropping area from left
        :type x: int
        :param y: Vertical offset of the cropping area from top
        :type y: int
        :param width: Width of the cropping area
        :type width: int
        :param height: Height of the cropping area
        :type height: int
        :return: New asset with cropped essence
        :rtype: Asset
        """
        mime_type = MimeType(asset.mime_type)
        encoder_name = self.__mime_type_to_encoder.get(mime_type)
        if not encoder_name or mime_type.type != 'video':
            raise UnsupportedFormatError('Unsupported source asset type: %s' % mime_type)

        if x == 0 and y == 0 and width == asset.width and height == asset.height:
            return asset

        max_x = max(0, min(asset.width, width + x))
        max_y = max(0, min(asset.height, height + y))
        min_x = max(0, min(asset.width, x))
        min_y = max(0, min(asset.height, y))

        if min_x == asset.width or min_y == asset.height or max_x <= min_x or max_y <= min_y:
            raise OperatorError('Invalid cropping area: <x=%r, y=%r, width=%r, height=%r>' % (x, y, width, height))

        width = max_x - min_x
        height = max_y - min_y

        result = io.BytesIO()
        with _FFmpegContext(asset.essence, result) as ctx:
            command = ['ffmpeg', '-v', 'error',
                       '-i', ctx.input_path, '-codec', 'copy',
                       '-f:v', 'crop=w=%d:h=%d:x=%d:y=%d' % (width, height, x, y),
                       '-f', encoder_name, '-y', ctx.output_path]

            try:
                subprocess.run(command, stderr=subprocess.PIPE, check=True)
            except subprocess.CalledProcessError as ffmpeg_error:
                error_message = ffmpeg_error.stderr.decode('utf-8')
                raise OperatorError('Could not crop asset: %s' % error_message)

        metadata = _combine_metadata(asset,
                                     'mime_type', 'duration', 'video', 'audio', 'subtitle',
                                     width=width, height=height)

        return Asset(essence=result, **metadata)

    @operator
    def rotate(self, asset: Asset, angle: float, expand: bool = False) -> Asset:
        """
        Creates an asset whose essence is rotated by the specified angle in
        degrees.

        :param asset: Asset whose contents will be rotated
        :type asset: Asset
        :param angle: Angle in degrees, counter clockwise
        :type angle: float
        :param expand: If true, changes the dimensions of the new asset so it
            can hold the entire rotated essence, otherwise the dimensions of
            the original asset will be used.
        :type expand: bool
        :return: New asset with rotated essence
        :rtype: Asset
        """
        mime_type = MimeType(asset.mime_type)
        encoder_name = self.__mime_type_to_encoder.get(mime_type)
        if not encoder_name or mime_type.type != 'video':
            raise UnsupportedFormatError('Unsupported source asset type: %s' % mime_type)

        if angle % 360.0 == 0.0:
            return asset

        angle_rad = radians(angle)
        width = asset.width
        height = asset.height

        if expand:
            if angle % 180 < 90:
                width_ = asset.width
                height_ = asset.height
                angle_rad_ = angle_rad % pi
            else:
                width_ = asset.height
                height_ = asset.width
                angle_rad_ = angle_rad % pi - pi/2
            cos_a = cos(angle_rad_)
            sin_a = sin(angle_rad_)
            width = ceil(round(width_ * cos_a + height_ * sin_a, 7))
            height = ceil(round(width_ * sin_a + height_ * cos_a, 7))

        result = io.BytesIO()
        with _FFmpegContext(asset.essence, result) as ctx:
            command = ['ffmpeg', '-v', 'error',
                       '-i', ctx.input_path, '-codec', 'copy',
                       '-f:v', 'rotate=a=%(a)f:ow=%(w)d:oh=%(h)d)' % dict(a=angle_rad, w=width, h=height),
                       '-f', encoder_name, '-y', ctx.output_path]

            try:
                subprocess.run(command, stderr=subprocess.PIPE, check=True)
            except subprocess.CalledProcessError as ffmpeg_error:
                error_message = ffmpeg_error.stderr.decode('utf-8')
                raise OperatorError('Could not rotate asset: %s' % error_message)

        metadata = _combine_metadata(asset,
                                     'mime_type', 'duration', 'video', 'audio', 'subtitle',
                                     width=width, height=height)

        return Asset(essence=result, **metadata)


class FFmpegMetadataProcessor(MetadataProcessor):
    """
    Represents a metadata processor that uses FFmpeg.
    """
    __decoder_and_stream_type_to_mime_type = {
        ('matroska,webm', 'video'): MimeType('video/x-matroska'),
        ('mov,mp4,m4a,3gp,3g2,mj2', 'video'): MimeType('video/quicktime'),
        ('avi', 'video'): MimeType('video/x-msvideo'),
        ('mpegts', 'video'): MimeType('video/mp2t'),
        ('ogg', 'video'): MimeType('video/ogg'),
        ('mp3', 'audio'): MimeType('audio/mpeg'),
        ('ogg', 'audio'): MimeType('audio/ogg'),
        ('wav', 'audio'): MimeType('audio/wav'),
    }

    __mime_type_to_encoder = {
        MimeType('video/x-matroska'): 'matroska',
        MimeType('video/quicktime'): 'mov',
        MimeType('video/x-msvideo'): 'avi',
        MimeType('video/mp2t'): 'mpegts',
        MimeType('video/ogg'): 'ogg',
        MimeType('audio/mpeg'): 'mp3',
        MimeType('audio/ogg'): 'ogg',
        MimeType('audio/wav'): 'wav',
    }

    # See https://wiki.multimedia.cx/index.php?title=FFmpeg_Metadata
    metadata_keys_by_mime_type = {
        MimeType('video/x-matroska'): bidict({}),
        MimeType('video/x-msvideo'): bidict({}),
        MimeType('video/mp2t'): bidict({}),
        MimeType('video/quicktime'): bidict({}),
        MimeType('video/ogg'): bidict({}),
        MimeType('audio/mpeg'): bidict({
            'album': 'album',                   # TALB Album
            'album_artist': 'album_artist',     # TPE2 Band/orchestra/accompaniment
            'album_sort': 'album-sort',         # TSOA Album sort order
            'artist': 'artist',                 # TPE1 Lead performer(s)/Soloist(s)
            'artist_sort': 'artist-sort',       # TSOP Performer sort order
            'bpm': 'TBPM',                      # TBPM BPM (beats per minute)
            'composer': 'composer',             # TCOM Composer
            'performer': 'performer',           # TPE3 Conductor/performer refinement
            'content_group': 'TIT1',            # TIT1 Content group description
            'copyright': 'copyright',           # TCOP (Copyright message)
            'date': 'date',                     # TDRC Recording time
            'disc': 'disc',                     # TPOS Part of a set
            'disc_subtitle': 'TSST',            # TSST Set subtitle
            'encoded_by': 'encoded_by',         # TENC Encoded by
            'encoder': 'encoder',               # TSSE Software/Hardware and settings used for encoding
            'encoding_time': 'TDEN',            # TDEN Encoding time
            'file_type': 'TFLT',                # TFLT File type
            'genre': 'genre',                   # TCON (Content type)
            'isrc': 'TSRC',                     # TSRC ISRC (international standard recording code)
            'initial_key': 'TKEY',              # TKEY Musical key in which the sound starts
            'involved_people': 'TIPL',          # TIPL Involved people list
            'language': 'language',             # TLAN Language(s)
            'length': 'TLEN',                   # TLEN Length of the audio file in milliseconds
            'lyricist': 'TEXT',                 # TEXT Lyricist/Text writer
            'lyrics': 'lyrics',                 # USLT Unsychronized lyric/text transcription
            'media_type': 'TMED',               # TMED Media type
            'mood': 'TMOO',                     # TMOO Mood
            'original_album': 'TOAL',           # TOAL Original album/movie/show title
            'original_artist': 'TOPE',          # TOPE Original artist(s)/performer(s)
            'original_date': 'TDOR',            # TDOR Original release time
            'original_filename': 'TOFN',        # TOFN Original filename
            'original_lyricist': 'TOLY',        # TOLY Original lyricist(s)/text writer(s)
            'owner': 'TOWN',                    # TOWN File owner/licensee
            'credits': 'TMCL',                  # TMCL Musician credits list
            'playlist_delay': 'TDLY',           # TDLY Playlist delay
            'produced_by': 'TPRO',              # TPRO Produced notice
            'publisher': 'publisher',           # TPUB Publisher
            'radio_station_name': 'TRSN',       # TRSN Internet radio station name
            'radio_station_owner': 'TRSO',      # TRSO Internet radio station owner
            'remixed_by': 'TP4',                # TPE4 Interpreted, remixed, or otherwise modified by
            'tagging_date': 'TDTG',             # TDTG Tagging time
            'title': 'title',                   # TIT2 Title/songname/content description
            'title_sort': 'title-sort',         # TSOT Title sort order
            'track': 'track',                   # TRCK Track number/Position in set
            'version': 'TIT3',                  # TIT3 Subtitle/Description refinement

            # Release time (TDRL) can be written, but it collides with
            # recording time (TDRC) when reading;

            # AENC, APIC, ASPI, COMM, COMR, ENCR, EQU2, ETCO, GEOB, GRID, LINK,
            # MCDI, MLLT, OWNE, PRIV, PCNT, POPM, POSS, RBUF, RVA2, RVRB, SEEK,
            # SIGN, SYLT, SYTC, UFID, USER, WCOM, WCOP, WOAF, WOAR, WOAS, WORS,
            # WPAY, WPUB, and WXXX will be written as TXXX tag
        }),
        MimeType('audio/ogg'): bidict({
            'album': 'ALBUM',                   # Collection name
            'album_artist': 'album_artist',     # Band/orchestra/accompaniment
            'artist': 'ARTIST',                 # Band or singer, composer, author, etc.
            'comment': 'comment',               # Short text description of the contents
            'composer': 'COMPOSER',             # Composer
            'contact': 'CONTACT',               # Contact information for the creators or distributors
            'copyright': 'COPYRIGHT',           # Copyright attribution
            'date': 'DATE',                     # Date the track was recorded
            'disc': 'disc',                     # Collection number
            'encoded_by': 'ENCODED-BY',         # Encoded by
            'encoder': 'ENCODER',               # Software/Hardware and settings used for encoding
            'genre': 'GENRE',                   # Short text indication of music genre
            'isrc': 'ISRC',                     # ISRC number
            'license': 'LICENSE',               # License information
            'location': 'LOCATION',             # Location where track was recorded
            'performer': 'PERFORMER',           # Artist(s) who performed the work (conductor, orchestra, etc.)
            'produced_by': 'ORGANIZATION',      # Organization producing the track (i.e. the 'record label')
            'title': 'TITLE',                   # Track/Work name
            'track': 'track',                   # Track number if part of a collection or album
            'tracks': 'TRACKTOTAL',             # Total number of track number in a collection or album
            'version': 'VERSION',               # Version of the track (e.g. remix info)
        }),
        MimeType('audio/wav'): bidict({}),
    }

    def __init__(self, config: Optional[Mapping[str, Any]] = None) -> None:
        """
        Initializes a new `FFmpegMetadataProcessor`.

        :param config: Mapping with settings.
        """
        super().__init__(config)

    @property
    def formats(self) -> Iterable[str]:
        return {'ffmetadata'}

    def read(self, file: IO) -> Mapping[str, Mapping]:
        try:
            probe_data = _probe(file)
        except subprocess.CalledProcessError:
            raise UnsupportedFormatError('Unsupported file format.')

        decoder_and_stream_type = _get_decoder_and_stream_type(probe_data)
        mime_type = self.__decoder_and_stream_type_to_mime_type.get(decoder_and_stream_type)
        if not mime_type:
            raise UnsupportedFormatError('Unsupported metadata source.')

        # Extract metadata (tags) from ffprobe information
        ffmetadata = probe_data['format'].get('tags', {})
        for stream in probe_data['streams']:
            ffmetadata.update(stream.get('tags', {}))

        # Convert FFMetadata items to metadata items
        metadata = {}
        metadata_keys = self.metadata_keys_by_mime_type[mime_type]
        for ffmetadata_key, value in ffmetadata.items():
            metadata_key = metadata_keys.inv.get(ffmetadata_key)
            if metadata_key is not None:
                metadata[metadata_key] = value

        return {'ffmetadata': metadata}

    def strip(self, file: IO) -> IO:
        try:
            probe_data = _probe(file)
        except subprocess.CalledProcessError:
            raise UnsupportedFormatError('Unsupported file format.')

        decoder_and_stream_type = _get_decoder_and_stream_type(probe_data)
        mime_type = self.__decoder_and_stream_type_to_mime_type.get(decoder_and_stream_type)
        if not mime_type:
            raise UnsupportedFormatError('Unsupported metadata source.')

        # Strip metadata
        result = io.BytesIO()
        with _FFmpegContext(file, result) as ctx:
            encoder_name = self.__mime_type_to_encoder[mime_type]
            command = ['ffmpeg', '-loglevel', 'error',
                       '-i', ctx.input_path,
                       '-map_metadata', '-1', '-codec', 'copy',
                       '-y', '-f', encoder_name, ctx.output_path]
            try:
                subprocess.run(command, stderr=subprocess.PIPE, check=True)
            except subprocess.CalledProcessError as ffmpeg_error:
                error_message = ffmpeg_error.stderr.decode('utf-8')
                raise OperatorError('Could not strip metadata: %s' % error_message)

        return result

    def combine(self, file: IO, metadata_by_type: Mapping[str, Mapping]) -> IO:
        try:
            probe_data = _probe(file)
        except subprocess.CalledProcessError:
            raise UnsupportedFormatError('Unsupported file format.')

        decoder_and_stream_type = _get_decoder_and_stream_type(probe_data)
        mime_type = self.__decoder_and_stream_type_to_mime_type.get(decoder_and_stream_type)
        if not mime_type:
            raise UnsupportedFormatError('Unsupported metadata source.')

        # Validate provided metadata
        if not metadata_by_type:
            raise ValueError('No metadata provided')
        if 'ffmetadata' not in metadata_by_type:
            raise UnsupportedFormatError('Invalid metadata to be combined with essence: %r' %
                                         (metadata_by_type.keys(),))
        if not metadata_by_type['ffmetadata']:
            raise ValueError('No metadata provided')

        # Add metadata to file
        result = io.BytesIO()
        with _FFmpegContext(file, result) as ctx:
            encoder_name = self.__mime_type_to_encoder[mime_type]
            command = ['ffmpeg', '-loglevel', 'error',
                       '-f', encoder_name, '-i', ctx.input_path]

            ffmetadata = metadata_by_type['ffmetadata']
            metadata_keys = self.metadata_keys_by_mime_type[mime_type]
            for metadata_key, value in ffmetadata.items():
                ffmetadata_key = metadata_keys.get(metadata_key)
                if ffmetadata_key is None:
                    raise ValueError('Unsupported metadata key: %r' % metadata_key)
                command.append('-metadata')
                command.append('%s=%s' % (ffmetadata_key, value))

            command.extend(['-codec', 'copy',
                            '-y', '-f', encoder_name, ctx.output_path])

            try:
                subprocess.run(command, stderr=subprocess.PIPE, check=True)
            except subprocess.CalledProcessError as ffmpeg_error:
                error_message = ffmpeg_error.stderr.decode('utf-8')
                raise OperatorError('Could not add metadata: %s' % error_message)

        return result
