import json
import subprocess
import tempfile

from madam.core import Asset, Processor
from madam.future import subprocess_run


class FFmpegProcessor(Processor):
    """
    Represents a processor that uses FFmpeg to read audio and video data.
    """

    class _FFprobe:
        def show_format(self, file):
            with tempfile.NamedTemporaryFile() as tmp:
                tmp.write(file.read())
                command = 'ffprobe -print_format json -loglevel quiet -show_format'.split()
                command.append(tmp.name)
                result = subprocess_run(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
            string_result = result.stdout.decode('utf-8')
            json_obj = json.loads(string_result)
            return json_obj.get('format', None)

    def __init__(self):
        self._ffprobe = self._FFprobe()

    def can_read(self, file):
        if not file:
            raise ValueError('Error when reading file-like object: %r' % file)
        json_result = self._ffprobe.show_format(file)
        return bool(json_result)

    def read(self, file):
        json_result = self._ffprobe.show_format(file)
        file.seek(0)
        return Asset(essence=file, duration=float(json_result['duration']))
