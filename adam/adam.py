import collections
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
        
class Asset:
    def __init__(self):
        pass

class WavReader:
    def read(self, file_path):
        asset = Asset()
        with wave.open(file_path, 'rb') as wave_file:
            asset.mime_type = 'audio/wav'
            asset.channels = wave_file.getnchannels()
            asset.framerate = wave_file.getframerate()
            asset.essence = wave_file.readframes(wave_file.getnframes())
        return asset