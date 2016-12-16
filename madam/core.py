import abc
import functools
import io
import importlib
import os
import shelve
import shutil
from collections.abc import MutableMapping

from frozendict import frozendict


class Madam:
    """
    Represents an instance of the library.
    """
    def __init__(self):
        """
        Initializes a new library instance with default configuration.

        The default configuration includes a list of all available Processor
        and MetadataProcessor implementations.
        """
        self.config = dict(
            processors=[
                'madam.image.PillowProcessor',
                'madam.vector.SVGProcessor',
                'madam.ffmpeg.FFmpegProcessor',
            ],
            metadata_processors=[
                'madam.exiv2.Exiv2MetadataProcessor',
                'madam.vector.SVGMetadataProcessor',
                'madam.ffmpeg.FFmpegMetadataProcessor',
            ]
        )
        self._processors = []
        self._metadata_processors = []

        # Initialize processors
        for processor_path in self.config['processors']:
            processor_class = Madam._import_from(processor_path)
            self._processors.append(processor_class())

        # Initialize metadata processors
        for processor_path in self.config['metadata_processors']:
            try:
                processor_class = Madam._import_from(processor_path)
            except ImportError:
                self.config['metadata_processors'].remove(processor_path)
                continue
            processor = processor_class()
            self._metadata_processors.append(processor)

    @staticmethod
    def _import_from(member_path):
        """
        Returns the member located at the specified import path.

        :param member_path: Fully qualified name of the member to be imported
        :return: Member
        """
        module_path, member_name = member_path.rsplit('.', 1)
        module = importlib.import_module(module_path)
        member_class = getattr(module, member_name)
        return member_class

    def get_processor(self, file):
        """
        Returns a processor that can read the data in the specified file.

        :param file: file-like object to be parsed.
        :return: Processor object that can handle the data in the specified file,
                 or None if no suitable processor could be found.
        """
        for processor in self._processors:
            file.seek(0)
            if processor.can_read(file):
                file.seek(0)
                return processor
        return None

    def read(self, file, additional_metadata=None):
        r"""
        Reads the specified file and returns its contents as an Asset object.

        :param file: file-like object to be parsed
        :param additional_metadata: optional metadata for the resulting asset.
               Existing metadata entries extracted from the file will be overwritten.
        :type additional_metadata: dict
        :returns: Asset representing the specified file
        :raises UnsupportedFormatError: if the file format cannot be recognized or is not supported
        :raises TypeError: if the file is None

        :Example:

        >>> import io
        >>> from madam import Madam
        >>> madam = Madam()
        >>> file = io.BytesIO(b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
        ... b'\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00'
        ... b'\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82')
        >>> asset = madam.read(file)
        """
        if not file:
            raise TypeError('Unable to read object of type %s' % type(file))

        processor = self.get_processor(file)
        if not processor:
            raise UnsupportedFormatError()

        asset = processor.read(file)

        handled_formats = set()
        for metadata_processor in self._metadata_processors:
            asset_metadata = dict(asset.metadata)
            file.seek(0)
            try:
                metadata_by_format = metadata_processor.read(file)
                for metadata_format, metadata_values in metadata_by_format.items():
                    if metadata_format in handled_formats:
                        continue
                    asset_metadata[metadata_format] = metadata_values
                stripped_essence = metadata_processor.strip(asset.essence)
                clean_asset = Asset(stripped_essence, **asset_metadata)
                asset = clean_asset
                handled_formats.update(metadata_processor.formats)
            except UnsupportedFormatError:
                pass

        if additional_metadata:
            asset_metadata = dict(asset.metadata)
            asset_metadata.update(dict(additional_metadata))
            asset = Asset(asset.essence, **asset_metadata)

        return asset

    def write(self, asset, file):
        r"""
        Write the Asset object to the specified file.

        :param asset: Asset that contains the data to be written
        :param file: file-like object to be written

        :Example:

        >>> import io
        >>> import os
        >>> from madam import Madam
        >>> from madam.core import Asset
        >>> gif_asset = Asset(essence=io.BytesIO(b'GIF89a\x01\x00\x01\x00\x00\x00\x00;'), mime_type='image/gif')
        >>> madam = Madam()
        >>> with open(os.devnull, 'wb') as file:
        ...     madam.write(gif_asset, file)
        >>> wav_asset = Asset(
        ...     essence=io.BytesIO(b'RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00D\xac'
        ...             b'\x00\x00\x88X\x01\x00\x02\x00\x10\x00data\x00\x00\x00\x00'),
        ...     mime_type='video/mp4')
        >>> with open(os.devnull, 'wb') as file:
        ...     madam.write(wav_asset, file)
        """
        essence_with_metadata = asset.essence
        handled_formats = set()
        for metadata_processor in self._metadata_processors:
            metadata_by_format = {}

            for metadata_format in metadata_processor.formats:
                if metadata_format in handled_formats:
                    continue
                metadata = getattr(asset, metadata_format, None)
                if metadata is None:
                    handled_formats.add(metadata_format)
                    continue
                metadata_by_format[metadata_format] = metadata

            if not metadata_by_format:
                continue

            try:
                essence_with_metadata = metadata_processor.combine(essence_with_metadata, metadata_by_format)
                handled_formats.update(metadata_processor.formats)
            except UnsupportedFormatError:
                pass

        shutil.copyfileobj(essence_with_metadata, file)


class AssetStorage(MutableMapping):
    """
    Represents a data store for :class:`~madam.core.Asset` objects.

    The persistence guarantees for stored data may differ based on the
    respective storage implementation.
    """
    def filter(self, **kwargs):
        """
        Returns a sequence of asset keys whose assets match the criteria that are
        specified by the passed arguments.
        :param kwargs: Criteria defined as keys and values
        :return: Sequence of asset keys
        """
        matches = []
        for asset_key, (asset, tags) in self.items():
            for key, value in kwargs.items():
                if asset.metadata.get(key) == value:
                    matches.append(asset_key)
        return matches

    def filter_by_tags(self, *tags):
        """
        Returns a set of all asset keys in this storage that have at least the
        specified tags.

        :param tags: Mandatory tags of an asset to be included in result
        :return: Keys of the assets whose tags are a superset of the specified tags
        """
        search_tags = frozenset(tags)
        return set(asset_key for asset_key, (asset, asset_tags) in self.items()
                   if search_tags <= asset_tags)


class InMemoryStorage(AssetStorage):
    """
    Represents a non-persistent storage backend for :class:`~madam.core.Asset`
    objects.

    Assets are not serialized, but stored in memory.
    """
    def __init__(self):
        """
        Initializes a new, empty InMemoryStorage object.
        """
        self.store = {}

    def __setitem__(self, asset_key, asset_and_tags):
        """
        Stores an :class:`~madam.core.Asset` in this asset storage using the
        specified key.

        The `asset_and_tags` argument is a tuple of the asset and the
        associated tags.

        Adding an asset key twice overwrites all tags for the asset.

        :param asset_key: Unique value used as a key to store the asset.
        :param asset: Tuple of the asset and the tags associated with the asset
        """
        asset, tags = asset_and_tags
        if not tags:
            tags = frozenset()
        self.store[asset_key] = (asset, frozenset(tags))

    def __getitem__(self, asset_key):
        """
        Returns a tuple of the :class:`~madam.core.Asset` with the specified
        key and the tags associated with the asset.

        An error will be raised if the key does not exist.

        :param asset_key: Key of the asset for which the tags should be returned
        :return: A tuple containing an asset and a set the tags associated with the asset
        :raise KeyError: if the key does not exist in this storage
        """
        if asset_key not in self.store:
            raise KeyError('Asset with key %r cannot be found in storage' % asset_key)
        return self.store[asset_key]

    def __delitem__(self, asset_key):
        """
        Removes the :class:`~madam.core.Asset` with the specified key from this
        asset storage, as well as all associated data (e.g. tags).

        :param asset_key: Key of the asset to be removed
        :raise KeyError: if the key does not exist in this storage
        """
        if asset_key not in self.store:
            raise KeyError('Asset with key %r cannot be found in storage' % asset_key)
        del self.store[asset_key]

    def __contains__(self, asset_key):
        """
        Returns whether an asset with the specified key is stored in this
        asset storage.
        :param asset_key: Key of the asset that should be tested
        :return: `True` if the key exists, `False` otherwise
        """
        return asset_key in self.store

    def __iter__(self):
        """
        Returns an object that can be used to iterate all asset that are stored
        in this asset storage.
        :return: Iterator object
        """
        return iter(list(self.store.keys()))

    def __len__(self):
        """
        Returns the number of assets in this storage.
        :return: Number of assets in this storage
        """
        return len(self.store)


class ShelveStorage(AssetStorage):
    """
    Represents a persistent storage backend for :class:`~madam.core.Asset`
    objects. Asset keys must be strings.

    ShelveStorage uses a file on the file system to serialize Assets.
    """
    def __init__(self, path):
        """
        Initializes a new ShelveStorage with the specified path.

        :param path: File system path where the data should be stored
        """
        if os.path.exists(path) and not os.path.isfile(path):
            raise ValueError('The storage path %r is not a file.' % path)
        self.path = path

    def __setitem__(self, asset_key, asset_and_tags):
        """
        Stores an :class:`~madam.core.Asset` in this asset storage using the
        specified key.

        The `asset_and_tags` argument is a tuple of the asset and the
        associated tags.

        Adding an asset key twice overwrites all tags for the asset.

        :param asset_key: Unique value used as a key to store the asset.
        :param asset: Tuple of the asset and the tags associated with the asset
        """
        asset, tags = asset_and_tags
        if not tags:
            tags = frozenset()
        with shelve.open(self.path) as store:
            store[asset_key] = (asset, tags)

    def __getitem__(self, asset_key):
        """
        Returns a tuple of the :class:`~madam.core.Asset` with the specified
        key and the tags associated with the asset.

        An error will be raised if the key does not exist.

        :param asset_key: Key of the asset for which the tags should be returned
        :return: A tuple containing an asset and a set the tags associated with the asset
        :raise KeyError: if the key does not exist in this storage
        """
        with shelve.open(self.path) as store:
            if asset_key not in store:
                raise KeyError('Asset with key %r cannot be found in storage' % asset_key)
            return store[asset_key]

    def __delitem__(self, asset_key):
        """
        Removes the :class:`~madam.core.Asset` with the specified key from this
        asset storage, as well as all associated data (e.g. tags).

        :param asset_key: Key of the asset to be removed
        :raise KeyError: if the key does not exist in this storage
        """
        with shelve.open(self.path) as store:
            if asset_key not in store:
                raise KeyError('Asset with key %r cannot be found in storage' % asset_key)
            del store[asset_key]

    def __contains__(self, asset_key):
        """
        Returns whether an asset with the specified key is stored in this
        asset storage.
        :param asset_key: Key of the asset that should be tested
        :return: `True` if the key exists, `False` otherwise
        """
        with shelve.open(self.path) as store:
            return asset_key in store

    def __iter__(self):
        """
        Returns an object that can be used to iterate all asset that are stored
        in this asset storage.
        :return: Iterator object
        """
        with shelve.open(self.path) as store:
            return iter(list(store.keys()))

    def __len__(self):
        """
        Returns the number of assets in this storage.
        :return: Number of assets in this storage
        """
        with shelve.open(self.path) as store:
            return len(store)


def _immutable(value):
    """
    Creates a read-only version from the specified value.

    Dictionaries, lists, and sets will be handled recursively.

    :param value: Value to be transformed into a read-only version
    :return: Read-only value
    """
    if isinstance(value, dict):
        return frozendict({k: _immutable(v) for k, v in value.items()})
    elif isinstance(value, set):
        return frozenset({_immutable(v) for v in value})
    elif isinstance(value, list):
        return tuple([_immutable(v) for v in value])
    else:
        return value


class Asset:
    """
    Represents a digital asset.

    An :class:`~madam.core.Asset` is an immutable value object whose contents consist
    of *essence* and *metadata*. Essence represents the actual data of a media file,
    such as the color values of an image, whereas the metadata describes the essence.

    Assets should not be instantiated directly. Instead, use :func:`~madam.core.read` to retrieve an Asset
    representing your content.
    """
    def __init__(self, essence, **metadata):
        """
        Initializes a new :class:`~madam.core.Asset` with the specified essence and metadata.

        :param essence: The essence of the asset as a file-like object
        :param metadata: The metadata describing the essence
        """
        self._essence_data = essence.read()
        if 'mime_type' not in metadata:
            metadata['mime_type'] = None
        self.metadata = _immutable(metadata)

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
        return io.BytesIO(self._essence_data)

    def __hash__(self):
        return hash(self._essence_data) ^ hash(self.metadata)


class UnsupportedFormatError(Exception):
    """
    Represents an error that is raised whenever file content with unknown type is encountered.
    """
    pass


class Pipeline:
    """
    Represents a processing pipeline for :class:`~madam.core.Asset` objects.

    The pipeline can be configured to hold a list of asset processing operators, all
    of which are applied to one or more assets when calling the
    :func:`~madam.core.Pipeline.process` method.
    """
    def __init__(self):
        """
        Initializes a new pipeline without operators.
        """
        self.operators = []

    def process(self, *assets):
        """
        Applies the operators in this pipeline on the specified assets.

        :param assets: Assets to be processed
        :return: Generator with processed assets
        """
        for asset in assets:
            processed_asset = asset
            for operator in self.operators:
                processed_asset = operator(processed_asset)
            yield processed_asset

    def add(self, operator):
        """
        Appends the specified operator to the processing chain.

        :param operator: Operator to be added
        """
        self.operators.append(operator)


class Processor(metaclass=abc.ABCMeta):
    """
    Represents an entity that can create :class:`~madam.core.Asset` objects
    from binary data.

    Every Processor needs to have a no-args __init__ method in order to be registered correctly.
    """

    @abc.abstractmethod
    def can_read(self, file):
        """
        Returns whether the specified MIME type is supported by this processor.

        :param file: file-like object to be tested
        :return: whether the data format of the specified file is supported or not
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def read(self, file):
        """
        Returns an :class:`~madam.core.Asset` object whose essence is identical to
        the contents of the specified file.

        :param file: file-like object to be read
        :return: Asset with essence
        :raises UnsupportedFormatError: if the specified data format is not supported
        """
        raise NotImplementedError()


class MetadataProcessor(metaclass=abc.ABCMeta):
    """
    Represents an entity that can manipulate metadata.

    Every MetadataProcessor needs to have a no-args __init__ method in order to be registered correctly.
    """
    @property
    @abc.abstractmethod
    def formats(self):
        """
        The metadata formats which are supported.
        :return: supported metadata formats
        :rtype: tuple
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def read(self, file):
        """
        Reads the file and returns the metadata.

        The metadata that is returned is grouped by type. The keys are specified by
        :attr:`~madam.core.MetadataProcessor.format`.

        :param file: File-like object to be read
        :return: Metadata contained in the file
        :rtype: dict
        :raises UnsupportedFormatError: if the data is corrupt or its format is not supported
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def strip(self, file):
        """
        Removes all metadata of the supported type from the specified file.

        :param file: file-like that should get stripped of the metadata
        :return: file-like object without metadata
        :rtype: io.BytesIO
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def combine(self, file, metadata):
        """
        Returns a byte stream whose contents represent the specified file where
        the specified metadata was added.

        :param metadata: Mapping of the metadata format to the metadata dict
        :param file: Container file
        :return: file-like object with combined content
        :rtype: io.BytesIO
        """
        raise NotImplementedError()


def operator(function):
    """
    Decorator function for methods that process assets.

    Usually, it will be used with operations in a :class:`~madam.core.Processor`
    implementation to make the methods configurable before applying the method
    to an asset.

    Only keyword arguments are allowed for configuration.

    Example for using a decorated :attr:`convert` method:

    .. code:: python

        convert_to_opus = processor.convert(mime_type='audio/opus')
        convert_to_opus(asset)

    :param function: Method to decorate
    :return: Configurable method
    """
    @functools.wraps(function)
    def wrapper(self, **kwargs):
        configured_operator = functools.partial(function, self, **kwargs)
        return configured_operator
    return wrapper


class OperatorError(Exception):
    """
    Represents an error that is raised whenever an error occurs in an :func:`~madam.core.operator`.
    """
    pass
