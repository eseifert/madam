import json
import subprocess

from madam.core import Asset, Processor


class FFmpegProcessor(Processor):
    def can_read(self, file):
        ffprobe_cmd = 'ffprobe -print_format json -show_format -loglevel quiet -'
        with subprocess.Popen(ffprobe_cmd.split(), stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE) as process:
            try:
                stdout, stderr = process.communicate(input=file.read())
            except:
                process.kill()
                process.wait()
                raise ValueError('Error when reading file-like object: %r' % file)
            retcode = process.wait()
            if retcode:
                return False
        string_result = stdout.decode('utf-8')
        json_obj = json.loads(string_result)
        return bool(json_obj)

    def read(self, file):
        return Asset()
