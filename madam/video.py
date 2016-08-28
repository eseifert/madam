import io
import json
import subprocess
import tempfile

from bidict import bidict

from madam.core import Asset, Processor, operator, OperatorError
from madam.future import CalledProcessError, subprocess_run


class FFmpegProcessor(Processor):
    """
    Represents a processor that uses FFmpeg to read audio and video data.
    """

    class _FFprobe:
        def show_format(self, file):
            with tempfile.NamedTemporaryFile() as tmp:
                tmp.write(file.read())
                tmp.flush()

                command = 'ffprobe -print_format json -loglevel quiet -show_format'.split()
                command.append(tmp.name)
                result = subprocess_run(command, stdout=subprocess.PIPE)
            string_result = result.stdout.decode('utf-8')
            json_obj = json.loads(string_result)
            return json_obj.get('format')

    def __init__(self):
        super().__init__()
        self._ffprobe = self._FFprobe()
        self.__mime_type_to_ffmpeg_type = bidict({
            'video/webm': 'webm',
            'video/x-yuv4mpegpipe': 'yuv4mpegpipe'
        })

    def _can_read(self, file):
        if not file:
            raise ValueError('Error when reading file-like object: %r' % file)
        json_result = self._ffprobe.show_format(file)
        return bool(json_result)

    def _read(self, file):
        json_result = self._ffprobe.show_format(file)
        file.seek(0)
        mime_type = self.__mime_type_to_ffmpeg_type.inv[json_result['format_name']]
        duration = float(json_result['duration'])
        return Asset(essence=file, mime_type=mime_type, duration=duration)

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
