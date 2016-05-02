import collections
import io
import mimetypes

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
        self.essence_data = b''
        self.metadata = {'adam': {}}
        self.mime_type = None

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return other.__dict__ == self.__dict__
        return False

    def __getitem__(self, item):
        return self.metadata['adam'][item]

    @property
    def essence(self):
        essence_file = io.BytesIO()
        essence_file.write(self.essence_data)
        essence_file.seek(0)
        return essence_file

    @essence.setter
    def essence(self, value):
        self.essence_data = value.read()

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
