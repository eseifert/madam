from adam.core import Asset, Processor
import io
import mutagen.mp3
import os
import shutil
import tempfile
import wave


class WaveProcessor(Processor):
    supported_read_types = ['audio/vnd.wave', 'audio/wav', 'audio/wave', 'audio/x-wav']

    def read(self, wave_file):
        asset = Asset()
        asset['mime_type'] = 'audio/wav'
        with wave.open(wave_file) as wave_data:
            asset['channels'] = wave_data.getnchannels()
            asset['framerate'] = wave_data.getframerate()
            essence_bytes = wave_data.readframes(wave_data.getnframes())
            essence_stream = io.BytesIO()
            essence_stream.write(essence_bytes)
            essence_stream.seek(0)
            asset.essence = essence_stream
        return asset

    def can_read(self):
        return ['audio/vnd.wave', 'audio/wav', 'audio/wave', 'audio/x-wav']


class MutagenProcessor(Processor):
    supported_read_types = ['audio/mpeg']

    def read(self, mp3_file):
        asset = Asset()
        asset['mime_type'] = 'audio/mpeg'

        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = mp3_file.name
            filename = os.path.basename(file_path)
            copy_path = os.path.join(temp_dir, filename)
            shutil.copyfile(file_path, copy_path)

            mp3 = mutagen.mp3.MP3(copy_path)
            asset['duration'] = mp3.info.length
            mp3.tags.delete()

            with open(copy_path, 'rb') as mp3_file_copy:
                asset.essence = mp3_file_copy
        return asset

    def can_read(self):
        return ['audio/mpeg']

