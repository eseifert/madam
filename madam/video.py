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
    def can_read(self, file):
        if not file:
            raise ValueError('Error when reading file-like object: %r' % file)
        ffprobe = _run('ffprobe -print_format json -show_format -loglevel quiet -'.split(),
                       stdin=subprocess.PIPE, input=file.read(), stdout=subprocess.PIPE)
        string_result = ffprobe.stdout.decode('utf-8')
        json_obj = json.loads(string_result)
        return bool(json_obj)

    def read(self, file):
        with tempfile.NamedTemporaryFile() as tmp:
            tmp.write(file.read())
            ffprobe = _run(('ffprobe -print_format json -show_entries format=duration -loglevel quiet %s' % tmp.name).split(),
                           stdout=subprocess.PIPE, stdin=subprocess.PIPE, input=file.read())
        string_result = ffprobe.stdout.decode('utf-8')
        json_obj = json.loads(string_result)
        file.seek(0)
        return Asset(essence=file, duration=float(json_obj['format']['duration']))
