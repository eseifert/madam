import io
import json
import subprocess

from madam.core import Processor


class FFmpegProcessor(Processor):
    def can_read(self, file):
        ffprobe_call = subprocess.run(['ffprobe', '-print_format', 'json', '-show_format', '-loglevel', 'quiet', '-'],
                                      input=file.read(), stdout=subprocess.PIPE)
        string_result = ffprobe_call.stdout.decode('utf-8')
        json_obj = json.loads(string_result)
        return json_obj is not None

    def read(self, file):
        pass
