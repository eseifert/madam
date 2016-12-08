import abc
import functools
import io
import importlib
import itertools
import os
import shelve
import shutil
from collections import defaultdict

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
                'madam.ffmpeg.FFmpegProcessor',
            ],
            metadata_processors=[
                'madam.exiv2.Exiv2MetadataProcessor',
                'madam.ffmpeg.FFmpegMetadataProcessor',
            ]
        )
        self._processors = []
        self._metadata_processors_by_format = {}
        self._metadata_formats_by_processor = defaultdict(list)

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
            # Make sure there is only one metadata processor
            for format in processor.formats:
                if format in self._metadata_processors_by_format:
                    # There is already a metadata processor for this format
                    continue
                self._metadata_processors_by_format[format] = processor
                self._metadata_formats_by_processor[processor].append(format)

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
            if processor._can_read(file):
                file.seek(0)
                return processor
        return None

    def read(self, file, metadata=None):
        r"""
        Reads the specified file and returns its contents as an Asset object.

        :param file: file-like object to be parsed
        :param metadata: optional metadata for the resulting asset.
                         Existing metadata entries extracted from the file will be overwritten.
        :type metadata: dict
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
        asset = processor._read(file)
        for metadata_processor, metadata_formats in self._metadata_formats_by_processor.items():
            file.seek(0)
            try:
                asset_metadata = dict(asset.metadata)
                metadata_by_formats = metadata_processor.read(file)
                for metadata_format in metadata_formats:
                    if metadata_format in metadata_by_formats:
                        asset_metadata[metadata_format] = metadata_by_formats[metadata_format]
                stripped_essence = metadata_processor.strip(asset.essence)
                clean_asset = Asset(stripped_essence, **asset_metadata)
                asset = clean_asset
            except UnsupportedFormatError:
                pass
        if metadata:
            asset_metadata = dict(asset.metadata)
            asset_metadata.update(dict(metadata))
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
        for metadata_format, processor in self._metadata_processors_by_format.items():
            metadata = getattr(asset, metadata_format, None)
            if metadata is not None:
                essence_with_metadata = processor.combine(essence_with_metadata, {metadata_format: metadata})
        shutil.copyfileobj(essence_with_metadata, file)


class AssetStorage(metaclass=abc.ABCMeta):
    """
    Represents a data store for :class:`~madam.core.Asset` objects.

    The persistence guarantees for stored data may differ based on the
    respective storage implementation.
    """
    @abc.abstractmethod
    def add(self, asset, tags=None):
        """
        Adds the specified :class:`~madam.core.Asset` to this asset storage.

        An iterable of strings can be passed as an optional argument which describe
        the tags that apply for the added asset.

        Adding the same asset twice overwrites all tags for the asset.

        :param asset: Asset to be added
        :param tags: Tags associated with the asset
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def remove(self, asset):
        """
        Removes the specified :class:`~madam.core.Asset` from this asset storage.

        :param asset: Asset to be removed
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def __contains__(self, asset):
        raise NotImplementedError()

    @abc.abstractmethod
    def __iter__(self):
        raise NotImplementedError()

    @abc.abstractmethod
    def get_tags(self, asset):
        """
        Returns a set of all tags in this storage for the specified asset.

        :param asset: Asset for which the tags should be returned
        :return: Tags that are stored for the specified asset
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def filter_by_tags(self, *tags):
        """
        Returns a set of all assets in this storage that have at least the specified tags.

        :param tags: Mandatory tags of an asset to be included in result
        :return: Assets whose tags are a superset of the specified tags
        """
        raise NotImplementedError()


class InMemoryStorage(AssetStorage):
    """
    Represents a non-persistent storage backend for assets.

    Assets are not serialized, but stored in main memory.
    """
    def __init__(self):
        self.tags_by_asset = {}

    def add(self, asset, tags=None):
        if not tags:
            tags = set()
        self.tags_by_asset[asset] = tags

    def remove(self, asset):
        if asset not in self.tags_by_asset:
            raise ValueError('Unable to delete asset that is not contained in storage.')
        del self.tags_by_asset[asset]

    def __contains__(self, asset):
        return asset in self.tags_by_asset

    def get(self, **kwargs):
        matches = []
        for asset in self.tags_by_asset.keys():
            for key, value in kwargs.items():
                if asset.metadata.get(key, None) == value:
                    matches.append(asset)
        return matches

    def __iter__(self):
        return iter(list(self.tags_by_asset.keys()))

    def get_tags(self, asset):
        tags = self.tags_by_asset.get(asset)
        if tags is None:
            raise KeyError('Asset %r cannot be found in storage' % asset)
        return frozenset(tags)

    def filter_by_tags(self, *tags):
        search_tags = set(tags)
        return set(asset for asset, asset_tags in self.tags_by_asset.items() if search_tags <= asset_tags)


class ShelveStorage(AssetStorage):
    """
    Represents a persistent storage backend for assets.

    ShelveStorage uses a directory on the file system to serialize Assets.
    """
    def __init__(self, path):
        """
        Initializes a new ShelveStorage with the specified path.

        :param path: File system path where the data should go
        """
        if os.path.exists(path) and not os.path.isfile(path):
            raise ValueError('The storage path %r is not a file.' % path)
        self.path = path

        with shelve.open(self.path) as assets:
            max_stored_asset_id = max(map(int, assets.keys())) if assets.keys() else 0
            self._asset_id_sequence = itertools.count(start=max_stored_asset_id + 1)

    def __contains__(self, asset):
        with shelve.open(self.path) as assets:
            return asset in (stored_asset for stored_asset, tags in assets.values())

    def add(self, asset, tags=None):
        if not tags:
            tags = set()
        with shelve.open(self.path) as assets:
            for asset_id, asset_with_tags in assets.items():
                if asset == asset_with_tags[0]:
                    assets[asset_id] = (asset, tags)
                    return
            asset_id = next(self._asset_id_sequence)
            assets[str(asset_id)] = (asset, tags)

    def remove(self, asset):
        with shelve.open(self.path) as assets:
            for asset_id, (stored_asset, _) in assets.items():
                if stored_asset == asset:
                    del assets[asset_id]
                    return
        raise ValueError('Unable to remove unknown asset %r' % asset)

    def __iter__(self):
        with shelve.open(self.path) as assets:
            return iter([asset for asset, tags in assets.values()])

    def get_tags(self, asset):
        with shelve.open(self.path) as assets:
            for stored_asset, tags in assets.values():
                if stored_asset == asset:
                    return frozenset(tags)
        raise KeyError('Asset %r cannot be found in storage' % asset)

    def filter_by_tags(self, *tags):
        search_tags = set(tags)
        with shelve.open(self.path) as assets:
            return set(asset for asset, asset_tags in assets.values() if search_tags <= asset_tags)


def _freeze_dict(dictionary):
    """
    Creates a read-only dictionary from the specified dictionary.

    If the dictionary contains a value which is a dictionary, this dict
    is recursively transformed into a read-only dict.

    :param dictionary: Dict to be transformed into a read-only dict
    :return: Read-only dictionary
    """
    entries = {}
    for key, value in dictionary.items():
        if isinstance(value, dict):
            value = _freeze_dict(value)
        if isinstance(value, set):
            value = frozenset(value)
        entries[key] = value
    return frozendict(entries)


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
        self.metadata = _freeze_dict(metadata)

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
    def _can_read(self, mime_type):
        """
        Returns whether the specified MIME type is supported by this processor.

        :param mime_type: MIME type to be checked
        :return: whether the specified MIME type is supported or not
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def _read(self, file):
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
