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

supported_mime_types = []
reader_classes_by_mime_type = {}
class AssetReaderRegistry(type):
    def __init__(cls, name, bases, dict):
        super(AssetReaderRegistry, cls).__init__(name, bases, dict)
        for mime_type in cls.supported_mime_types:
            supported_mime_types.append(mime_type)
            reader_classes_by_mime_type[mime_type] = cls

class UnknownMimeTypeError(ValueError):
    pass

mimetypes.init()
def read(file_path):
    format,encoding = mimetypes.guess_type(file_path)
    if format not in reader_classes_by_mime_type:
        raise UnknownMimeTypeError('Unable to determine MIME type for file "%s"' % file_path)
    reader_class = reader_classes_by_mime_type[format]
    reader = reader_class()
    return reader.read(file_path)

def readWav(file_path):
    asset = Asset()
    with wave.open(file_path, 'rb') as wave_file:
        asset.mime_type = 'audio/wav'
        asset.channels = wave_file.getnchannels()
        asset.framerate = wave_file.getframerate()
        asset.essence = wave_file.readframes(wave_file.getnframes())
    return asset


def readMp3(file_path):
    asset = Asset()
    asset.mime_type = 'audio/mpeg'

    with tempfile.TemporaryDirectory() as temp_dir:
        filename = os.path.basename(file_path)
        copy_path = os.path.join(temp_dir, filename)
        shutil.copyfile(file_path, copy_path)
    
        mp3 = mutagen.mp3.MP3(copy_path)
        asset.duration = mp3.info.length
        mp3.tags.delete()
        
        with open(copy_path, 'rb') as mp3_file:
            asset.essence = mp3_file.read()
    return asset

class WavReader(metaclass = AssetReaderRegistry):
    supported_mime_types = ['audio/vnd.wave', 'audio/wav', 'audio/wave', 'audio/x-wav']
        
    def read(self, file_path):
        return readWav(file_path)
    
class Mp3Reader(metaclass = AssetReaderRegistry):
    supported_mime_types = ['audio/mpeg']
    
    def read(self, file_path):
        return readMp3(file_path)
