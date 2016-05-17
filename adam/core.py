import abc
import collections
import functools
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
processors = []
metadata_processors = []


@functools.singledispatch
def read(file, mime_type=None):
    if not mime_type:
        raise UnknownMimeTypeError('Unable to determine MIME type for open file')
    processors_supporting_type = (processor for processor in processors if processor.can_read(mime_type))
    processor = next(processors_supporting_type)
    asset = processor.read(file)
    return asset


@read.register(str)
def _read_path(path, mime_type=None):
    if not mime_type:
        mime_type, encoding = mimetypes.guess_type(path)
    if not mime_type:
        raise UnknownMimeTypeError('Unable to determine MIME type for file at "%s"' % path)
    with open(path, 'rb') as file:
        return read(file, mime_type)


class Pipeline:
    def __init__(self):
        self.operators = []

    def process(self, *assets):
        for asset in assets:
            processed_asset = asset
            for operator in self.operators:
                processed_asset = operator(processed_asset)
            yield processed_asset

    def add(self, operator):
        self.operators.append(operator)


class Processor(metaclass=abc.ABCMeta):
    def __init__(self):
        processors.append(self)

    @abc.abstractmethod
    def read(self):
        pass

    @abc.abstractmethod
    def can_read(self, mime_type):
        pass


class MetadataProcessor(metaclass=abc.ABCMeta):
    def __init__(self):
        metadata_processors.append(self)

    @abc.abstractmethod
    def extract(self, file):
        pass
