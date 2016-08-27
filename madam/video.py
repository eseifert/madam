import collections
import json
import subprocess
import tempfile

from madam.core import Asset, Processor


_CompletedProcess = collections.namedtuple('_CompletedProcess', ['args', 'retcode', 'stdout', 'stderr'])


def _run(command, stdin=None, input=None, stdout=None, stderr=None):
    with subprocess.Popen(command, stdin=stdin,
                          stdout=stdout, stderr=stderr) as process:
        try:
            stdout, stderr = process.communicate(input=input)
        except:
            process.kill()
            process.wait()
            raise
        retcode = process.poll()
    return _CompletedProcess(args=process.args, retcode=retcode, stdout=stdout, stderr=stderr)


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
                result = _run(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
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
