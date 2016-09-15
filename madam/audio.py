import io
import os
import shutil
import tempfile
import wave

import mutagen.mp3

from madam.core import Asset, Processor
from madam.ffmpeg import FFmpegProcessor, FFmpegMetadataProcessor


class MutagenProcessor(Processor):
    """
    Represents a processor that uses *Mutagen* to read audio data.
    """
    def _read(self, mp3_file):
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = mp3_file.name
            filename = os.path.basename(file_path)
            copy_path = os.path.join(temp_dir, filename)
            shutil.copyfile(file_path, copy_path)

            mp3 = mutagen.mp3.MP3(copy_path)
            metadata = dict(mime_type='audio/mpeg', duration=mp3.info.length)
            mp3.tags.delete(copy_path)

            with open(copy_path, 'rb') as mp3_file_copy:
                asset = Asset(essence=mp3_file_copy, **metadata)
        return asset

    def _can_read(self, file):
        with tempfile.NamedTemporaryFile() as temp_file:
            temp_file.write(file.read())
            if mutagen.File(temp_file.name):
                return True
        return False
