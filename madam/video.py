import io
import json
import subprocess

from madam.core import Asset, Processor


class FFmpegProcessor(Processor):
    def can_read(self, file):
        with subprocess.Popen(['ffprobe', '-print_format', 'json', '-show_format', '-loglevel', 'quiet', '-'],
                              stdout=subprocess.PIPE) as process:
            try:
                stdout, stderr = process.communicate(input)
            except:
                process.kill()
                process.wait()
                raise
        string_result = stdout.decode('utf-8')
        json_obj = json.loads(string_result)
        return json_obj is not None

    def read(self, file):
        return Asset()
