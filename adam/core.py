import collections
import os
import shutil
import mimetypes
import mutagen.mp3
import tempfile
import wave

class AssetStorage:
    def __init__(self):
        self.assets = collections.defaultdict(list)
        
    def __setitem__(self, id, asset):
        self.assets[id].append(asset)
        
    def __getitem__(self, id):
        return self.assets[id][-1]
    
    def __contains__(self, id):
        return id in self.assets
    
    def __delitem__(self, key):
        del self.assets[key]
    
    def versions_of(self, id):
        return self.assets[id]
    
    def get(self, **kwargs):
        matches = []
        for asset_versions in self.assets.values():
            for asset in asset_versions:
                for key,value in kwargs.items():
                    if hasattr(asset, key) and getattr(asset, key) == value:
                        matches.append(asset)
        return matches
        
class Asset:
    def __init__(self):
        self.essence = None
        self.mime_type = None
        
    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return other.__dict__ == self.__dict__
        return False

read_method_by_mime_type = {}

class UnknownMimeTypeError(ValueError):
    pass

mimetypes.init()
def read(file_path):
    format,encoding = mimetypes.guess_type(file_path)
    if format not in read_method_by_mime_type:
        raise UnknownMimeTypeError('Unable to determine MIME type for file "%s"' % file_path)
    read_method = read_method_by_mime_type[format]
    with open(file_path, 'rb') as file:
        asset = read_method(file)
    return asset

def supports_mime_types(*types):
    def wrap(f):
        for type in types:
            read_method_by_mime_type[type] = f
        return f
    return wrap

@supports_mime_types('audio/vnd.wave', 'audio/wav', 'audio/wave', 'audio/x-wav')
def readWav(wave_file):
    asset = Asset()
    asset.mime_type = 'audio/wav'
    with wave.open(wave_file) as wave_data:
        asset.channels = wave_data.getnchannels()
        asset.framerate = wave_data.getframerate()
        asset.essence = wave_data.readframes(wave_data.getnframes())
    return asset

@supports_mime_types('audio/mpeg')
def readMp3(mp3_file):
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

@supports_mime_types('image/jpeg')
def readJpeg(jpeg_file):
    asset = Asset()
    asset.mime_type = 'image/jpeg'
    asset.essence = 0
    return asset
