import io
import json
import subprocess
import tempfile

from bidict import bidict

from madam.core import Asset, Processor, operator
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
                result = subprocess_run(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
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

    def read(self, file):
        json_result = self._ffprobe.show_format(file)
        file.seek(0)
        mime_type = self.__mime_type_to_ffmpeg_type.inv[json_result['format_name']]
        duration = float(json_result['duration'])
        return Asset(essence=file, mime_type=mime_type, duration=duration)

    @operator
    def convert(self, asset, mime_type):
        """
        Creates a new asset of the specified MIME type from the essence of the
        specified asset.

        :param asset: Asset whose contents will be converted
        :param mime_type: Target MIME type
        :return: New asset with converted essence
        """
        ffmpeg_type = self.__mime_type_to_ffmpeg_type[mime_type]

        command = ['ffmpeg', '-loglevel', 'error', '-i', 'pipe:', '-f', ffmpeg_type, 'pipe:']
        try:
            result = subprocess_run(command, input=asset.essence.read(),
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    check=True)
        except CalledProcessError as e:
            raise IOError('Could not convert video asset: %r' % e.stderr)

        return Asset(essence=io.BytesIO(result.stdout), mime_type=mime_type)
