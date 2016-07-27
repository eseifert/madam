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
                madam_metadata = asset.metadata['madam']
                for key, value in kwargs.items():
                    if madam_metadata.get(key, None) == value:
                        matches.append(asset)
        return matches


class Asset:
    """
    Represents a digital asset.

    Assets should not be instantiated directly. Instead, use :func:`~madam.core.read` to retrieve an Asset
    representing your content.
    """
    def __init__(self):
        self.essence_data = b''
        self.metadata = {'madam': {}}
        self.mime_type = None

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return other.__dict__ == self.__dict__
        return False

    def __getitem__(self, item):
        return self.metadata['madam'][item]

    def __setitem__(self, key, value):
        self.metadata['madam'][key] = value

    @property
    def essence(self):
        """
        Represents the actual content of the asset.

        The essence of an MP3 file, for example, is only comprised of the actual audio data,
        whereas metadata such as ID3 tags are stored separately as metadata.
        """
        return io.BytesIO(self.essence_data)

    @essence.setter
    def essence(self, value):
        self.essence_data = value.read()


class UnsupportedFormatError(ValueError):
    """
    Represents an error that is raised whenever file content with unknown type is encountered.
    """
    pass

mimetypes.init()
processors = []
metadata_processors_by_format = {}


def read(file, mime_type=None):
    """
    Reads the specified file and returns its contents as an Asset object.

    :param file: file-like object or file path to be parsed
    :param mime_type: MIME type of the specified file
    :type mime_type: str
    :returns: Asset representing the specified file
    :raises UnsupportedFormatError: if the file format cannot be recognized or is not supported

    :Example:

    >>> import madam
    >>> madam.read('path/to/file.jpg')
    """
    processors_supporting_type = (processor for processor in processors if processor.can_read(file))
    processor = next(processors_supporting_type, None)
    if not processor:
        raise UnsupportedFormatError()
    asset = processor.read(file)
    for metadata_format, metadata_processor in metadata_processors_by_format.items():
        file.seek(0)
        try:
            asset.metadata[metadata_format] = metadata_processor.read(file)
        except:
            pass
    return asset


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
    def read(self, file):
        pass

    @abc.abstractmethod
    def can_read(self, mime_type):
        pass


class MetadataProcessor(metaclass=abc.ABCMeta):
    def __init__(self):
        metadata_processors_by_format[self.format] = self

    @property
    @abc.abstractmethod
    def format(self):
        pass

    @abc.abstractmethod
    def read(self, file):
        pass

    @abc.abstractmethod
    def remove(self, file):
        pass
