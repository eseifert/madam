import abc
import io
import itertools
import mimetypes
import os
import shelve


class AssetStorage(metaclass=abc.ABCMeta):
    @abc.abstractmethod
    def add(self, asset):
        pass

    @abc.abstractmethod
    def remove(self, asset):
        pass

    @abc.abstractmethod
    def __contains__(self, asset_id):
        pass

    @abc.abstractmethod
    def __iter__(self):
        pass

    @abc.abstractmethod
    def filter_by_tags(self, *tags):
        """
        Returns all assets in this storage that have at least the specified tags.

        :param tags: Mandatory tags of an asset to be included in result
        :return: Assets whose tags are a superset of the specified tags
        """
        pass


class InMemoryStorage(AssetStorage):
    def __init__(self):
        self.assets = []

    def add(self, asset):
        self.assets.append(asset)

    def remove(self, asset):
        return self.assets.remove(asset)

    def __contains__(self, asset):
        return asset in self.assets

    def get(self, **kwargs):
        matches = []
        for asset in self.assets:
            madam_metadata = asset.metadata['madam']
            for key, value in kwargs.items():
                if madam_metadata.get(key, None) == value:
                    matches.append(asset)
        return matches

    def __iter__(self):
        return iter(list(self.assets))

    def filter_by_tags(self, *tags):
        tag_set = set(tags)
        assets_by_tags = [asset for asset in self.assets if tag_set.issubset(asset.tags)]
        return iter(assets_by_tags)


class FileStorage(AssetStorage):
    """
    Represents a persistent storage backend for assets.

    FileStorage uses a directory on the file system to serialize Assets.
    """
    def __init__(self, path):
        """
        Initializes a new FileStorage with the specified path.

        :param path: File system path where the data should go
        """
        if os.path.isfile(path):
            raise FileExistsError('The storage path "%s" is a file not a directory.' % path)
        if not os.path.isdir(path):
            os.mkdir(path)
        self.path = path

        self._shelf_path = os.path.join(self.path, 'shelf')
        with shelve.open(self._shelf_path) as assets:
            max_stored_asset_id = max(map(int, assets.keys())) if assets.keys() else 0
            self._asset_id_sequence = itertools.count(start=max_stored_asset_id + 1)

    def __contains__(self, asset):
        with shelve.open(self._shelf_path) as assets:
            return asset in assets.values()

    def add(self, asset):
        with shelve.open(self._shelf_path) as assets:
            asset_id = next(self._asset_id_sequence)
            assets[str(asset_id)] = asset

    def remove(self, asset):
        with shelve.open(self._shelf_path) as assets:
            for key, value in assets.items():
                if value == asset:
                    del assets[key]
                    return
        raise ValueError('Unable to remove unknown asset %s', asset)

    def __iter__(self):
        with shelve.open(self._shelf_path) as assets:
            return iter(list(assets.values()))

    def filter_by_tags(self, *tags):
        with shelve.open(self._shelf_path) as assets:
            return iter([asset for asset in assets.values() if set(tags) <= asset.tags])


class Asset:
    """
    Represents a digital asset.

    Assets should not be instantiated directly. Instead, use :func:`~madam.core.read` to retrieve an Asset
    representing your content.

    :param essence: The essence of the asset as a byte string
    """
    def __init__(self, essence):
        self.essence_data = essence
        self.metadata = {'madam': {'tags': set(), 'mime_type': None}}

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return other.__dict__ == self.__dict__
        return False

    def __getattr__(self, item):
        if item in self.metadata:
            return self.metadata[item]
        elif item in self.metadata['madam']:
            return self.metadata['madam'][item]
        raise AttributeError('%r object has no attribute %r' % (self.__class__, item))

    def __setstate__(self, state):
        """
        Sets this objects __dict__ to the specified state.

        Required for Asset to be unpicklable. If this is absent, pickle will not
        set the __dict__ correctly due to the presence of :func:`~madam.core.Asset.__getattr__`.
        :param state: The state passed by pickle
        """
        self.__dict__ = state

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

    def __hash__(self):
        return hash(self.essence_data)


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

    :param file: file-like object to be parsed
    :param mime_type: MIME type of the specified file
    :type mime_type: str
    :returns: Asset representing the specified file
    :raises UnsupportedFormatError: if the file format cannot be recognized or is not supported

    :Example:

    >>> import madam
    >>> with open('path/to/file.jpg', 'rb') as file:
    ...     madam.read(file)
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
            stripped_essence = metadata_processor.strip(asset.essence)
            clean_asset = Asset(stripped_essence.read())
            clean_asset.metadata = asset.metadata
            asset = clean_asset
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
    def can_read(self, mime_type):
        pass

    @abc.abstractmethod
    def read(self, file):
        pass

    @abc.abstractmethod
    def can_write(self, asset, **options):
        pass

    @abc.abstractmethod
    def write(self, asset, file, **options):
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
    def strip(self, file):
        pass

    @abc.abstractmethod
    def combine(self, file, metadata):
        """
        Returns a byte stream whose contents represent the specified file where the specified metadata was added.

        :param metadata: Metadata information to be added
        :param file: Container file
        :return: File-like object with combined content
        """
        pass
