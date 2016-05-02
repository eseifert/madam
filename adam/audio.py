from adam.core import Asset, supports_mime_types
import mutagen.mp3
import os
import shutil
import tempfile
import wave


@supports_mime_types('audio/vnd.wave', 'audio/wav', 'audio/wave', 'audio/x-wav')
def read_wav(wave_file):
    asset = Asset()
    asset.mime_type = 'audio/wav'
    with wave.open(wave_file) as wave_data:
        asset.channels = wave_data.getnchannels()
        asset.framerate = wave_data.getframerate()
        asset.essence = wave_data.readframes(wave_data.getnframes())
    return asset

@supports_mime_types('audio/mpeg')
def read_mp3(mp3_file):
    asset = Asset()
    asset.mime_type = 'audio/mpeg'

    with tempfile.TemporaryDirectory() as temp_dir:
        file_path = mp3_file.name
        filename = os.path.basename(file_path)
        copy_path = os.path.join(temp_dir, filename)
        shutil.copyfile(file_path, copy_path)
    
        mp3 = mutagen.mp3.MP3(copy_path)
        asset.duration = mp3.info.length
        mp3.tags.delete()
        
        with open(copy_path, 'rb') as mp3_file_copy:
            asset.essence = mp3_file_copy.read()
    return asset


