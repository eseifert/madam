import abc
import collections
import io
import itertools
import mimetypes
import os
import shelve


class AssetStorage(metaclass=abc.ABCMeta):
    @abc.abstractmethod
    def add(self, asset):
        raise NotImplementedError()

    @abc.abstractmethod
    def remove(self, asset):
        raise NotImplementedError()

    @abc.abstractmethod
    def __contains__(self, asset_id):
        raise NotImplementedError()

    @abc.abstractmethod
    def __iter__(self):
        raise NotImplementedError()

    @abc.abstractmethod
    def filter_by_tags(self, *tags):
        """
        Returns all assets in this storage that have at least the specified tags.

        :param tags: Mandatory tags of an asset to be included in result
        :return: Assets whose tags are a superset of the specified tags
        """
        raise NotImplementedError()


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
            for key, value in kwargs.items():
                if asset.metadata.get(key, None) == value:
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


class _FrozenDict(collections.Mapping):
    def __init__(self, dictionary):
        """
        Initializes a read-only dictionary with the contents of the specified dict.

        :param dictionary: Contents of the read-only dictionary
        """
        self.entries = self._dict_to_frozenset_with_tuples(dictionary)

    def _dict_to_frozenset_with_tuples(self, dictionary):
        """
        Creates a read-only dictionary from the specified dictionary.

        If the dictionary contains a value which is a dictionary, this dict
        is recursively transformed into a read-only dict.

        :param dictionary: Dict to be transformed into a read-only dict
        :return: Read-only dictionary
        """
        tuples = set()
        for key, value in dictionary.items():
            if isinstance(value, dict):
                value = _FrozenDict(value)
            if isinstance(value, set):
                value = frozenset(value)
            tuples.add((key, value))
        return frozenset(tuples)

    def __getitem__(self, item):
        for key, value in self.entries:
            if key == item:
                return value

    def __contains__(self, item):
        for key, _ in self.entries:
            if key == item:
                return True

    def __iter__(self):
        return (key for key, value in self.entries)

    def __len__(self):
        return len(self.entries)

    def __hash__(self):
        return hash(self.entries)


class Asset:
    """
    Represents a digital asset.

    Assets should not be instantiated directly. Instead, use :func:`~madam.core.read` to retrieve an Asset
    representing your content.

    :param essence: The essence of the asset as a byte string
    :param metadata: The metadata describing the essence
    """
    def __init__(self, essence, metadata):
        self.essence_data = essence
        if 'tags' not in metadata:
            metadata['tags'] = set()
        if 'mime_type' not in metadata:
            metadata['mime_type'] = None
        self.metadata = _FrozenDict(metadata)

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return other.__dict__ == self.__dict__
        return False

    def __getattr__(self, item):
        if item in self.metadata:
            return self.metadata[item]
        raise AttributeError('%r object has no attribute %r' % (self.__class__, item))

    def __setattr__(self, key, value):
        if 'metadata' in self.__dict__ and key in self.__dict__['metadata']:
            raise NotImplementedError('Unable to overwrite metadata attribute.')
        super().__setattr__(key, value)

    def __setstate__(self, state):
        """
        Sets this objects __dict__ to the specified state.

        Required for Asset to be unpicklable. If this is absent, pickle will not
        set the __dict__ correctly due to the presence of :func:`~madam.core.Asset.__getattr__`.
        :param state: The state passed by pickle
        """
        self.__dict__ = state

    @property
    def essence(self):
        """
        Represents the actual content of the asset.

        The essence of an MP3 file, for example, is only comprised of the actual audio data,
        whereas metadata such as ID3 tags are stored separately as metadata.
        """
        return io.BytesIO(self.essence_data)

    def __hash__(self):
        return hash(self.essence_data) ^ hash(self.metadata)


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
            metadata = dict(asset.metadata)
            metadata[metadata_format] = metadata_processor.read(file)
            stripped_essence = metadata_processor.strip(asset.essence)
            clean_asset = Asset(stripped_essence.read(), metadata=_FrozenDict(metadata))
            asset = clean_asset
        except:
            pass
    return asset


def write(asset, file, **options):
    """
    Write the Asset object to the specified file.

    :param asset: Asset that contains the data to be written
    :param file: file-like object to be written
    :param \**options: Output file format specific options (e.g. quality, interlacing, etc.)
    :raises UnsupportedFormatError: if the output file format is not supported

    :Example:

    >>> import madam
    >>> gif_asset = madam.Asset(essence=b'GIF89a\x01\x00\x01\x00\x00\x00\x00;')
    >>> with open('path/to/file.gif', 'wb') as file:
    ...     madam.write(gif_asset, file)
    >>> wav_asset = madam.Asset(essence=b'RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00D\xac\x00\x00\x88X\x01\x00\x02\x00\x10\x00data\x00\x00\x00\x00')
    >>> with open('path/to/file.wav', 'wb') as file:
    ...     madam.write(wav_asset, file)
    """
    processors_supporting_type = (processor for processor in processors if processor.can_write(asset, **options))
    processor = next(processors_supporting_type, None)
    if processor is None:
        raise UnsupportedFormatError()
    processor.write(asset, file, **options)


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
        raise NotImplementedError()

    @abc.abstractmethod
    def read(self, file):
        raise NotImplementedError()

    @abc.abstractmethod
    def can_write(self, asset, **options):
        raise NotImplementedError()

    @abc.abstractmethod
    def write(self, asset, file, **options):
        raise NotImplementedError()


class MetadataProcessor(metaclass=abc.ABCMeta):
    def __init__(self):
        metadata_processors_by_format[self.format] = self

    @property
    @abc.abstractmethod
    def format(self):
        raise NotImplementedError()

    @abc.abstractmethod
    def read(self, file):
        raise NotImplementedError()

    @abc.abstractmethod
    def strip(self, file):
        raise NotImplementedError()

    @abc.abstractmethod
    def combine(self, file, metadata):
        """
        Returns a byte stream whose contents represent the specified file where the specified metadata was added.

        :param metadata: Metadata information to be added
        :param file: Container file
        :return: File-like object with combined content
        """
        raise NotImplementedError()
