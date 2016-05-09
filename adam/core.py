import collections
import io
import mimetypes


class AssetStorage:
    def __init__(self):
        self.assets = collections.defaultdict(list)
        
    def __setitem__(self, asset_id, asset):
        self.assets[asset_id].append(asset)
        
    def __getitem__(self, asset_id):
        return self.assets[asset_id][-1]
    
    def __contains__(self, asset_id):
        return asset_id in self.assets
    
    def __delitem__(self, key):
        del self.assets[key]
    
    def versions_of(self, asset_id):
        return self.assets[asset_id]
    
    def get(self, **kwargs):
        matches = []
        for asset_versions in self.assets.values():
            for asset in asset_versions:
                adam_metadata = asset.metadata['adam']
                for key, value in kwargs.items():
                    if adam_metadata.get(key, None) == value:
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

    def __setitem__(self, key, value):
        self.metadata['adam'][key] = value

    @property
    def essence(self):
        essence_file = io.BytesIO()
        essence_file.write(self.essence_data)
        essence_file.seek(0)
        return essence_file

    @essence.setter
    def essence(self, value):
        self.essence_data = value.read()


class UnknownMimeTypeError(ValueError):
    pass

mimetypes.init()
read_method_by_mime_type = {}


def read(file_path):
    file_format, encoding = mimetypes.guess_type(file_path)
    if file_format not in read_method_by_mime_type:
        raise UnknownMimeTypeError('Unable to determine MIME type for file "%s"' % file_path)
    read_method = read_method_by_mime_type[file_format]
    with open(file_path, 'rb') as file:
        asset = read_method(file)
    return asset


def supports_mime_types(*mime_types):
    def wrap(f):
        for mime_type in mime_types:
            read_method_by_mime_type[mime_type] = f
        return f
    return wrap


class Pipeline:
    def __init__(self):
        self.operators = []

    def process(self, *assets):
        yield from assets

    def add(self, operator):
        self.operators.append(operator)