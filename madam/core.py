import abc
import functools
import io
import importlib
import os
import shelve
import shutil
from pathlib import Path
from typing import Any, Callable, Dict, Generator, IO, Iterable, Iterator, \
    Mapping, MutableMapping, MutableSequence, Optional, Set, Tuple, TypeVar, Union

from frozendict import frozendict


def _immutable(value: Any) -> Any:
    """
    Creates a read-only version from the specified value.

    Dictionaries, lists, and sets will be converted recursively.

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


def _mutable(value: Any) -> Any:
    """
    Creates a writeable version from the specified (read-only) value.

    Frozen dictionaries, tuples, and frozen sets will be converted recursively.

    :param value: Value to be transformed into a writeable version
    :return: Writeable value
    """
    if isinstance(value, frozendict):
        return {k: _mutable(v) for k, v in value.items()}
    elif isinstance(value, frozenset):
        return {_mutable(v) for v in value}
    elif isinstance(value, tuple):
        return [_mutable(v) for v in value]
    else:
        return value


class Asset:
    """
    Represents a digital asset.

    An `Asset` is an immutable value object whose contents consist of *essence*
    and *metadata*. Essence represents the actual data of a media file, such as
    the color values of an image, whereas the metadata describes the essence.

    Assets should not be instantiated directly. Instead, use
    :func:`~madam.core.Madam.read` to retrieve an `Asset` representing the
    content.
    """
    def __init__(self, essence: IO, **metadata: Any) -> None:
        """
        Initializes a new `Asset` with the specified essence and metadata.

        :param essence: The essence of the asset as a file-like object
        :type essence: IO
        :param \\**metadata: The metadata describing the essence
        :type \\*metadata: Any
        """
        self._essence_data = essence.read()
        if 'mime_type' not in metadata:
            metadata['mime_type'] = None
        self.metadata = _immutable(metadata)

    def __eq__(self, other: 'Asset') -> bool:
        if isinstance(other, self.__class__):
            return other.__dict__ == self.__dict__
        return False

    def __getattr__(self, item: str) -> Any:
        if item in self.metadata:
            return self.metadata[item]
        raise AttributeError('%r object has no attribute %r' % (self.__class__, item))

    def __setattr__(self, key: str, value: Any):
        if 'metadata' in self.__dict__ and key in self.__dict__['metadata']:
            raise NotImplementedError('Unable to overwrite metadata attribute.')
        super().__setattr__(key, value)

    def __setstate__(self, state: Dict[str, Any]):
        """
        Sets this objects __dict__ to the specified state.

        Required for Asset to be unpicklable. If this is absent, pickle will
        not set the `__dict__` correctly due to the presence of
        :func:`~madam.core.Asset.__getattr__`.

        :param state: The state passed by pickle
        """
        self.__dict__ = state

    @property
    def essence(self) -> IO:
        """
        Represents the actual content of the asset.

        The essence of an MP3 file, for example, is only comprised of the actual audio data,
        whereas metadata such as ID3 tags are stored separately as metadata.
        """
        return io.BytesIO(self._essence_data)

    def __hash__(self) -> int:
        return hash(self._essence_data) ^ hash(self.metadata)

    def __repr__(self) -> str:
        metadata_str = ' '.join(
            '{}={!r}'.format(k, v)
            for k, v in self.metadata.items()
            if not isinstance(v, frozendict)
        )
        return '<{} {}>'.format(self.__class__.__qualname__, metadata_str)


class UnsupportedFormatError(Exception):
    """
    Represents an error that is raised whenever file content with unknown type
    is encountered.
    """
    def __init__(self, *args) -> None:
        """
        Initializes a new `UnsupportedFormatError`.
        """
        super().__init__(*args)


def operator(function: Callable) -> Callable:
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
    Represents an error that is raised whenever an error occurs in an
    :func:`~madam.core.operator`.
    """
    def __init__(self, *args):
        """
        Initializes a new `OperatorError`.
        """
        super().__init__(*args)


class Pipeline:
    """
    Represents a processing pipeline for :class:`~madam.core.Asset` objects.

    The pipeline can be configured to hold a list of asset processing
    operators, all of which are applied to one or more assets when calling the
    :func:`~madam.core.Pipeline.process` method.
    """
    def __init__(self) -> None:
        """
        Initializes a new pipeline without operators.
        """
        self.operators = []  # type: MutableSequence[Callable]

    def process(self, *assets: Asset) -> Generator[Asset, float, None]:
        """
        Applies the operators in this pipeline on the specified assets.

        :param \\*assets: Asset objects to be processed
        :type \\*assets: Asset
        :return: Generator with processed assets
        """
        for asset in assets:
            processed_asset = asset
            for operator in self.operators:
                processed_asset = operator(processed_asset)
            yield processed_asset

    def add(self, operator: Callable) -> None:
        """
        Appends the specified operator to the processing chain.

        :param operator: Operator to be added
        """
        self.operators.append(operator)


class Processor(metaclass=abc.ABCMeta):
    """
    Represents an entity that can create :class:`~madam.core.Asset` objects
    from binary data.

    Every `Processor` needs to have an `__init__` method with an optional
    `config` parameter in order to be registered correctly.
    """
    @abc.abstractmethod
    def __init__(self, config: Optional[Mapping[str, Any]] = None) -> None:
        """
        Initializes a new `Processor`.

        :param config: Mapping with settings.
        """
        self.config = {}
        if config:
            self.config.update(config)

    @abc.abstractmethod
    def can_read(self, file: IO) -> bool:
        """
        Returns whether the specified MIME type is supported by this processor.

        :param file: file-like object to be tested
        :type file: IO
        :return: whether the data format of the specified file is supported or not
        :rtype: bool
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def read(self, file: IO) -> Asset:
        """
        Returns an :class:`~madam.core.Asset` object whose essence is identical to
        the contents of the specified file.

        :param file: file-like object to be read
        :type file: IO
        :return: Asset with essence
        :rtype: Asset
        :raises UnsupportedFormatError: if the specified data format is not supported
        """
        raise NotImplementedError()


class MetadataProcessor(metaclass=abc.ABCMeta):
    """
    Represents an entity that can manipulate metadata.

    Every `MetadataProcessor` needs to have an `__init__` method with an
    optional `config` parameter in order to be registered correctly.
    """
    @abc.abstractmethod
    def __init__(self, config: Optional[Mapping[str, Any]] = None) -> None:
        """
        Initializes a new `MetadataProcessor`.
        """
        self.config = {}
        if config:
            self.config.update(config)

    @property
    @abc.abstractmethod
    def formats(self) -> Iterable[str]:
        """
        The metadata formats which are supported.

        :return: supported metadata formats
        :rtype: set[str]
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def read(self, file: IO) -> Mapping:
        """
        Reads the file and returns the metadata.

        The metadata that is returned is grouped by type. The keys are specified by
        :attr:`~madam.core.MetadataProcessor.format`.

        :param file: File-like object to be read
        :type file: IO
        :return: Metadata contained in the file
        :rtype: Mapping
        :raises UnsupportedFormatError: if the data is corrupt or its format is not supported
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def strip(self, file: IO) -> IO:
        """
        Removes all metadata of the supported type from the specified file.

        :param file: file-like that should get stripped of the metadata
        :type file: IO
        :return: file-like object without metadata
        :rtype: IO
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def combine(self, file: IO, metadata: Mapping) -> IO:
        """
        Returns a byte stream whose contents represent the specified file where
        the specified metadata was added.

        :param metadata: Mapping of the metadata format to the metadata dict
        :type metadata: Mapping
        :param file: Container file
        :type file: IO
        :return: file-like object with combined content
        :rtype: IO
        """
        raise NotImplementedError()


class Madam:
    """
    Represents an instance of the library.
    """
    def __init__(self, config: Optional[Mapping[str, Any]] = None) -> None:
        """
        Initializes a new library instance with default configuration.

        The default configuration includes a list of all available Processor
        and MetadataProcessor implementations.

        :param config: Mapping with settings.
        """
        self.config = {}  # type: Dict[str, Any]
        if config:
            self.config.update(config)

        # Initialize processors
        self.processors = {
            'madam.image.PillowProcessor',
            'madam.vector.SVGProcessor',
            'madam.ffmpeg.FFmpegProcessor',
        }
        self._processors = []
        for processor_path in set(self.processors):
            try:
                processor_class = Madam._import_from(processor_path)
            except ImportError:
                self.processors.remove(processor_path)
                continue
            processor = processor_class(self.config)
            self._processors.append(processor)

        # Initialize metadata processors
        self.metadata_processors = {
            'madam.exif.ExifMetadataProcessor',
            'madam.vector.SVGMetadataProcessor',
            'madam.ffmpeg.FFmpegMetadataProcessor',
        }
        self._metadata_processors = []
        for processor_path in set(self.metadata_processors):
            try:
                processor_class = Madam._import_from(processor_path)
            except ImportError:
                self.metadata_processors.remove(processor_path)
                continue
            processor = processor_class(self.config)
            self._metadata_processors.append(processor)

    @staticmethod
    def _import_from(member_path: str):
        """
        Returns the member located at the specified import path.

        :param member_path: Fully qualified name of the member to be imported
        :return: Member
        """
        module_path, member_name = member_path.rsplit('.', 1)
        module = importlib.import_module(module_path)
        member_class = getattr(module, member_name)
        return member_class

    def get_processor(self, file: IO) -> Optional[Processor]:
        """
        Returns a processor that can read the data in the specified file.
        If no suitable processor can be found None will be returned.

        :param file: file-like object to be parsed.
        :type file: IO
        :return: Processor object that can handle the data in the specified file,
                 or None if no suitable processor could be found.
        :rtype: Processor or None
        """
        for processor in self._processors:
            file.seek(0)
            if processor.can_read(file):
                file.seek(0)
                return processor
        return None

    def read(self, file: IO, additional_metadata: Mapping = None):
        r"""
        Reads the specified file and returns its contents as an :class:`~madam.core.Asset` object.

        :param file: file-like object to be parsed
        :type file: IO
        :param additional_metadata: optional metadata for the resulting asset.
               Existing metadata entries extracted from the file will be overwritten.
        :type additional_metadata: Mapping
        :returns: Asset representing the specified file
        :rtype: Asset
        :raises UnsupportedFormatError: if the file format cannot be recognized or is not supported
        :raises TypeError: if the file is None

        :Example:

        >>> import io
        >>> from madam import Madam
        >>> manager = Madam()
        >>> file = io.BytesIO(b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
        ... b'\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00'
        ... b'\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82')
        >>> asset = manager.read(file)
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

    def write(self, asset: Asset, file: IO) -> None:
        r"""
        Write the :class:`~madam.core.Asset` object to the specified file.

        :param asset: Asset that contains the data to be written
        :type asset: Asset
        :param file: file-like object to be written
        :type file: IO

        :Example:

        >>> import io
        >>> import os
        >>> from madam import Madam
        >>> from madam.core import Asset
        >>> gif_asset = Asset(essence=io.BytesIO(b'GIF89a\x01\x00\x01\x00\x00\x00\x00;'), mime_type='image/gif')
        >>> manager = Madam()
        >>> with open(os.devnull, 'wb') as file:
        ...     manager.write(gif_asset, file)
        >>> wav_asset = Asset(
        ...     essence=io.BytesIO(b'RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00D\xac'
        ...             b'\x00\x00\x88X\x01\x00\x02\x00\x10\x00data\x00\x00\x00\x00'),
        ...     mime_type='video/mp4')
        >>> with open(os.devnull, 'wb') as file:
        ...     manager.write(wav_asset, file)
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


AssetKey = TypeVar('AssetKey')
AssetTags = Set[str]


class AssetStorage(MutableMapping[AssetKey, Tuple[Asset, AssetTags]]):
    """
    Represents an abstract base class for data stores of
    :class:`~madam.core.Asset` objects.

    All implementations of `AssetStorage` require a constructor.

    The persistence guarantees for stored data may differ based on the
    respective storage implementation.
    """
    @abc.abstractmethod
    def __init__(self) -> None:
        """
        Initializes a new `AssetStorage`.
        """
        pass

    def filter(self, **kwargs: Any) -> Iterable[AssetKey]:
        """
        Returns a sequence of asset keys whose assets match the criteria that are
        specified by the passed arguments.

        :param \\**kwargs: Criteria defined as keys and values
        :return: Sequence of asset keys
        :rtype: Iterable
        """
        matches = []
        for asset_key, (asset, tags) in self.items():
            for key, value in kwargs.items():
                if asset.metadata.get(key) == value:
                    matches.append(asset_key)
        return matches

    def filter_by_tags(self, *tags: str) -> Iterable[AssetKey]:
        """
        Returns a set of all asset keys in this storage that have at least the
        specified tags.

        :param \\*tags: Mandatory tags of an asset to be included in result
        :return: Keys of the assets whose tags are a superset of the specified tags
        :rtype: Iterable
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
    def __init__(self) -> None:
        """
        Initializes a new, empty `InMemoryStorage` object.
        """
        super().__init__()
        self.store = {}

    def __setitem__(self, asset_key: AssetKey, asset_and_tags: Tuple[Asset, AssetTags]):
        """
        Stores an :class:`~madam.core.Asset` in this asset storage using the
        specified key.

        The `asset_and_tags` argument is a tuple of the asset and the
        associated tags.

        Adding an asset key twice overwrites all tags for the asset.

        :param asset_key: Unique value used as a key to store the asset.
        :param asset_and_tags: Tuple of the asset and the tags associated with the asset
        :type asset_and_tags: Tuple[Asset, Set[str]]
        """
        asset, tags = asset_and_tags
        if not tags:
            tags = frozenset()
        self.store[asset_key] = (asset, frozenset(tags))

    def __getitem__(self, asset_key: AssetKey) -> Tuple[Asset, AssetTags]:
        """
        Returns a tuple of the :class:`~madam.core.Asset` with the specified
        key and the tags associated with the asset.

        An error will be raised if the key does not exist.

        :param asset_key: Key of the asset for which the tags should be returned
        :return: A tuple containing an asset and a set of the tags associated with the asset
        :rtype: Tuple[Asset, Set[str]]
        :raise KeyError: if the key does not exist in this storage
        """
        if asset_key not in self.store:
            raise KeyError('Asset with key %r cannot be found in storage' % asset_key)
        return self.store[asset_key]

    def __delitem__(self, asset_key: AssetKey) -> None:
        """
        Removes the :class:`~madam.core.Asset` with the specified key from this
        asset storage, as well as all associated data (e.g. tags).

        :param asset_key: Key of the asset to be removed
        :raise KeyError: if the key does not exist in this storage
        """
        if asset_key not in self.store:
            raise KeyError('Asset with key %r cannot be found in storage' % asset_key)
        del self.store[asset_key]

    def __contains__(self, asset_key: AssetKey) -> bool:
        """
        Returns whether an asset with the specified key is stored in this
        asset storage.

        :param asset_key: Key of the asset that should be tested
        :return: `True` if the key exists, `False` otherwise
        :rtype: bool
        """
        return asset_key in self.store

    def __iter__(self) -> Iterator[AssetKey]:
        """
        Returns an object that can be used to iterate all asset that are stored
        in this asset storage.

        :return: Iterator object
        """
        return iter(list(self.store.keys()))

    def __len__(self) -> int:
        """
        Returns the number of assets in this storage.

        :return: Number of assets in this storage
        :rtype: int
        """
        return len(self.store)


class ShelveStorage(AssetStorage):
    """
    Represents a persistent storage backend for :class:`~madam.core.Asset`
    objects. Asset keys must be strings.

    ShelveStorage uses a file on the file system to serialize Assets.
    """
    def __init__(self, path: Union[Path, str]):
        """
        Initializes a new `ShelveStorage` with the specified path.

        :param path: File system path where the data should be stored
        :type path: pathlib.Path or str
        """
        super().__init__()
        if os.path.exists(path) and not os.path.isfile(path):
            raise ValueError('The storage path %r is not a file.' % path)
        self.path = path

    def __setitem__(self, asset_key: str, asset_and_tags: Tuple[Asset, AssetTags]) -> None:
        """
        Stores an :class:`~madam.core.Asset` in this asset storage using the
        specified key.

        The `asset_and_tags` argument is a tuple of the asset and the
        associated tags.

        Adding an asset key twice overwrites all tags for the asset.

        :param asset_key: Unique value used as a key to store the asset.
        :param asset_and_tags: Tuple of the asset and the tags associated with the asset
        :type asset_and_tags: (Asset, collections.Iterable)
        """
        asset, tags = asset_and_tags
        if not tags:
            tags = frozenset()
        with shelve.open(self.path) as store:
            store[asset_key] = (asset, tags)

    def __getitem__(self, asset_key: str) -> Tuple[Asset, AssetTags]:
        """
        Returns a tuple of the :class:`~madam.core.Asset` with the specified
        key and the tags associated with the asset.

        An error will be raised if the key does not exist.

        :param asset_key: Key of the asset for which the tags should be returned
        :type asset_key: str
        :return: A tuple containing an asset and a set of the tags associated with the asset
        :rtype: (Asset, set)
        :raise KeyError: if the key does not exist in this storage
        """
        with shelve.open(self.path) as store:
            if asset_key not in store:
                raise KeyError('Asset with key %r cannot be found in storage' % asset_key)
            return store[asset_key]

    def __delitem__(self, asset_key: str) -> None:
        """
        Removes the :class:`~madam.core.Asset` with the specified key from this
        asset storage, as well as all associated data (e.g. tags).

        :param asset_key: Key of the asset to be removed
        :type asset_key: str
        :raise KeyError: if the key does not exist in this storage
        """
        with shelve.open(self.path) as store:
            if asset_key not in store:
                raise KeyError('Asset with key %r cannot be found in storage' % asset_key)
            del store[asset_key]

    def __contains__(self, asset_key: str) -> bool:
        """
        Returns whether an asset with the specified key is stored in this
        asset storage.
        :param asset_key: Key of the asset that should be tested
        :type asset_key: str
        :return: `True` if the key exists, `False` otherwise
        :rtype: bool
        """
        with shelve.open(self.path) as store:
            return asset_key in store

    def __iter__(self) -> Iterator[str]:
        """
        Returns an object that can be used to iterate all asset that are stored
        in this asset storage.
        :return: Iterator object
        """
        with shelve.open(self.path) as store:
            return iter(list(store.keys()))

    def __len__(self) -> int:
        """
        Returns the number of assets in this storage.
        :return: Number of assets in this storage
        :rtype: int
        """
        with shelve.open(self.path) as store:
            return len(store)
