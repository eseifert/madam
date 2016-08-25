from madam.core import Asset, Processor
import io
import mutagen.mp3
import os
import shutil
import tempfile
import wave


class WaveProcessor(Processor):
    def read(self, wave_file):
        with wave.open(wave_file) as wave_data:
            essence_bytes = wave_data.readframes(wave_data.getnframes())
            essence_stream = io.BytesIO()
            essence_stream.write(essence_bytes)
            essence_stream.seek(0)
            metadata = dict(
                mime_type='audio/wav',
                channels=wave_data.getnchannels(),
                framerate=wave_data.getframerate(),
            )
            asset = Asset(essence_stream.read(), **metadata)
        return asset

    def can_read(self, file):
        try:
            wave.open(file, 'rb')
            return True
        except:
            return False

    def can_write(self, asset, **options):
        # TODO: Implement
        return False

    def write(self, asset, file, **options):
        # TODO: Implement
        raise NotImplementedError()


class MutagenProcessor(Processor):
    def read(self, mp3_file):
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = mp3_file.name
            filename = os.path.basename(file_path)
            copy_path = os.path.join(temp_dir, filename)
            shutil.copyfile(file_path, copy_path)

            mp3 = mutagen.mp3.MP3(copy_path)
            metadata = dict(mime_type='audio/mpeg', duration=mp3.info.length)
            mp3.tags.delete(copy_path)

            with open(copy_path, 'rb') as mp3_file_copy:
                essence = mp3_file_copy.read()
                asset = Asset(essence, **metadata)
        return asset

    def can_read(self, file):
        with tempfile.NamedTemporaryFile() as temp_file:
            temp_file.write(file.read())
            if mutagen.File(temp_file.name):
                return True
        return False

    def can_write(self, asset, **options):
        # TODO: Implement
        return False

    def write(self, asset, file, **options):
        # TODO: Implement
        raise NotImplementedError()
