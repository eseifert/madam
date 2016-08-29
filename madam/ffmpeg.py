import io
import json
import subprocess
import tempfile

from bidict import bidict

from madam.core import Asset, Processor, operator, OperatorError, UnsupportedFormatError
from madam.future import CalledProcessError, subprocess_run


class FFmpegProcessor(Processor):
    """
    Represents a processor that uses FFmpeg to read audio and video data.

    The minimum version of FFmpeg required is v0.9.
    """

    @staticmethod
    def __probe(file, format=True, streams=False):
        with tempfile.NamedTemporaryFile() as tmp:
            tmp.write(file.read())
            tmp.flush()

            command = 'ffprobe -print_format json -loglevel quiet'.split()
            if format:
                command.append('-show_format')
            if streams:
                command.append('-show_streams')
            command.append(tmp.name)
            result = subprocess_run(command, stdout=subprocess.PIPE)
        string_result = result.stdout.decode('utf-8')
        json_obj = json.loads(string_result)
        return json_obj

    def __init__(self):
        """
        Initializes a new FFmpegProcessor.

        :raises EnvironmentError: if the installed version of ffprobe does not match the minimum version requirement
        """
        super().__init__()

        self._min_version = '0.9'
        command = 'ffprobe -version'.split()
        result = subprocess_run(command, stdout=subprocess.PIPE)
        string_result = result.stdout.decode('utf-8')
        version_string = string_result.split()[2]
        if version_string < self._min_version:
            raise EnvironmentError('Found ffprobe version %s. Requiring at least version %s.'
                                   % (version_string, self._min_version))

        self.__mime_type_to_ffmpeg_type = bidict({
            'audio/mpeg': 'mp3',
            'audio/ogg': 'ogg',
            'audio/wav': 'wav',
            'video/mp4': 'mp4',
            'video/webm': 'webm',
            'video/x-yuv4mpegpipe': 'yuv4mpegpipe'
        })

    def _can_read(self, file):
        if not file:
            raise ValueError('Error when reading file-like object: %r' % file)
        file_info = FFmpegProcessor.__probe(file)
        return bool(file_info)

    def _read(self, file):
        file_info = FFmpegProcessor.__probe(file, streams=True)
        file.seek(0)

        for format_name in file_info['format']['format_name'].split(','):
            mime_type = self.__mime_type_to_ffmpeg_type.inv.get(format_name)
            if mime_type is not None:
                break
        metadata = dict(
            mime_type=mime_type,
            duration=float(file_info['format']['duration'])
        )
        for stream in file_info['streams']:
            stream_type = stream.get('codec_type')
            if stream_type in ('audio', 'video'):
                # Only use first stream
                if stream_type in metadata:
                    break
                metadata[stream_type] = {}
            if 'codec_name' in stream:
                metadata[stream_type]['codec'] = stream['codec_name']
            if 'bit_rate' in stream:
                metadata[stream_type]['bitrate'] = float(stream['bit_rate'])/1000.0

        return Asset(essence=file, **metadata)

    @operator
    def resize(self, asset, width, height):
        if width < 1 or height < 1:
            raise ValueError('Invalid dimensions: %dx%d' % (width, height))
        try:
            ffmpeg_type = self.__mime_type_to_ffmpeg_type[asset.mime_type]
        except KeyError:
            raise UnsupportedFormatError('Unsupported asset type: %s' % asset.mime_type)
        if asset.mime_type.split('/')[0] not in ('image', 'video'):
            raise OperatorError('Cannot resize asset of type %s')
        command = ['ffmpeg', '-loglevel', 'error', '-f', ffmpeg_type, '-i', 'pipe:',
                   '-filter:v', 'scale=%d:%d' % (width, height),
                   '-f', ffmpeg_type, 'pipe:']
        try:
            result = subprocess_run(command, input=asset.essence.read(),
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    check=True)
        except CalledProcessError as ffmpeg_error:
            error_message = ffmpeg_error.stderr.decode('utf-8')
            raise OperatorError('Could not resize video asset: %s' % error_message)
        return Asset(essence=io.BytesIO(result.stdout), width=width, height=height)

    @operator
    def convert(self, asset, mime_type, video=None, audio=None, subtitles=None):
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
        :param mime_type: MIME type of the video container
        :param video: Dictionary with options for video streams.
        :param audio: Dictionary with options for audio streams.
        :param subtitles: Dictionary with the options for subtitle streams.
        :return: New asset with converted essence
        """
        ffmpeg_type = self.__mime_type_to_ffmpeg_type[mime_type]

        command = ['ffmpeg', '-loglevel', 'error', '-i', 'pipe:']
        if video is not None:
            if 'codec' in video: command.extend(['-c:v', video['codec']])
            if 'bitrate' in video: command.extend(['-b:v', '%dk' % video['bitrate']])
        if audio is not None:
            if 'codec' in audio: command.extend(['-c:a', audio['codec']])
            if 'bitrate' in audio: command.extend(['-b:a', '%dk' % audio['bitrate']])
        if subtitles is not None:
            if 'codec' in subtitles: command.extend(['-c:s', subtitles['codec']])
        command.extend(['-f', ffmpeg_type, 'pipe:'])
        try:
            result = subprocess_run(command, input=asset.essence.read(),
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    check=True)
        except CalledProcessError as ffmpeg_error:
            error_message = ffmpeg_error.stderr.decode('utf-8')
            raise OperatorError('Could not convert video asset: %s' % error_message)

        return Asset(essence=io.BytesIO(result.stdout), mime_type=mime_type)
