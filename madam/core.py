import abc
import functools
import hashlib
import importlib
import io
import json
import os
import shelve
import shutil
import threading
from collections.abc import Callable, Generator, Iterable, Iterator, Mapping, MutableMapping, MutableSequence
from pathlib import Path
from typing import IO, Any, Concatenate, Generic, ParamSpec, TypeVar

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
        return tuple(_immutable(v) for v in value)
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

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Asset):
            return NotImplemented
        return other.__dict__ == self.__dict__

    def __getattr__(self, item: str) -> Any:
        # Never forward Python protocol names into metadata — dunders must
        # follow normal attribute resolution only.
        if item.startswith('__') and item.endswith('__'):
            raise AttributeError(f'{self.__class__!r} object has no attribute {item!r}')
        if item in self.metadata:
            return self.metadata[item]
        raise AttributeError(f'{self.__class__!r} object has no attribute {item!r}')

    def __setattr__(self, key: str, value: Any):
        if 'metadata' in self.__dict__ and key in self.__dict__['metadata']:
            raise NotImplementedError('Unable to overwrite metadata attribute.')
        super().__setattr__(key, value)

    def __setstate__(self, state: dict[str, Any]):
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

    @property
    def content_id(self) -> str:
        """
        Returns a stable, content-addressed identifier for this asset's essence.

        The identifier is the SHA-256 hex digest of the raw essence bytes and is
        independent of metadata.  Two assets with identical bytes always have the
        same ``content_id``, making it suitable as an object-store key or
        deduplication handle.
        """
        return hashlib.sha256(self._essence_data).hexdigest()

    @classmethod
    def _from_bytes(cls, essence_bytes: bytes, **metadata: Any) -> 'Asset':
        """
        Internal fast-path constructor for callers that already hold the raw bytes.

        Unlike :meth:`__init__`, no I/O is performed — ``essence_bytes`` is stored
        directly without calling ``read()``.  This is an internal API; external code
        should use :meth:`__init__` with a file-like object.
        """
        obj = cls.__new__(cls)
        obj._essence_data = essence_bytes
        if 'mime_type' not in metadata:
            metadata['mime_type'] = None
        obj.metadata = _immutable(metadata)
        return obj

    def __repr__(self) -> str:
        metadata_str = ' '.join(f'{k}={v!r}' for k, v in self.metadata.items() if not isinstance(v, frozendict))
        return f'<{self.__class__.__qualname__} {metadata_str}>'


class LazyAsset(Asset):
    """
    An :class:`Asset` that stores only a URI instead of raw bytes.

    Essence bytes are fetched on demand by calling the *loader* callable.
    Because the raw bytes are never stored in the object, ``pickle.dumps``
    produces a payload that contains only the URI and metadata — safe to
    send through a Celery broker even for large video files.

    :param uri: Opaque string identifying the remote content (e.g. an S3 URI).
    :param loader: Callable ``(uri: str) -> IO`` that returns a readable
                   stream for the given URI.  May be ``None`` to create a
                   detached asset that will raise on essence access.
    :param \\**metadata: Metadata describing the asset.
    """

    def __init__(self, uri: str, loader: Callable[[str], IO] | None, **metadata: Any) -> None:
        # Bypass Asset.__init__ — we do not have bytes yet.
        if 'mime_type' not in metadata:
            metadata['mime_type'] = None
        object.__setattr__(self, '_uri', uri)
        object.__setattr__(self, '_loader', loader)
        object.__setattr__(self, 'metadata', _immutable(metadata))

    @property
    def uri(self) -> str:
        """The URI that identifies the remote content."""
        return object.__getattribute__(self, '_uri')

    @property
    def essence(self) -> IO:
        """
        Fetches and returns the asset content from the configured loader.

        :raises RuntimeError: if no loader was provided at construction time.
        """
        loader = object.__getattribute__(self, '_loader')
        if loader is None:
            raise RuntimeError(
                'LazyAsset has no loader — cannot access essence. Attach a loader before calling essence.'
            )
        return loader(self.uri)

    @property
    def content_id(self) -> str:
        try:
            return object.__getattribute__(self, '_content_id_cache')
        except AttributeError:
            digest = hashlib.sha256(self.essence.read()).hexdigest()
            object.__setattr__(self, '_content_id_cache', digest)
            return digest

    def __hash__(self) -> int:
        return hash(self.uri) ^ hash(self.metadata)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, LazyAsset):
            return NotImplemented
        return self.uri == other.uri and self.metadata == other.metadata

    def __getstate__(self) -> dict[str, Any]:
        # Only persist URI and metadata — never the loader or bytes.
        return {'_uri': self.uri, 'metadata': self.metadata}

    def __setstate__(self, state: dict[str, Any]) -> None:
        object.__setattr__(self, '_uri', state['_uri'])
        object.__setattr__(self, '_loader', None)
        object.__setattr__(self, 'metadata', state['metadata'])

    def __repr__(self) -> str:
        return f'<LazyAsset uri={self.uri!r}>'


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


class TransientOperatorError(OperatorError):
    """
    Raised when an operator fails due to a temporary condition (e.g. OOM,
    disk full) that may succeed on retry.
    """


class PermanentOperatorError(OperatorError):
    """
    Raised when an operator fails due to a permanent condition (e.g. invalid
    codec, corrupt input) that will never succeed on retry.
    """


class UnsupportedFormatError(PermanentOperatorError):
    """
    Represents an error that is raised whenever file content with unknown type
    is encountered.
    """

    def __init__(self, *args) -> None:
        """
        Initializes a new `UnsupportedFormatError`.
        """
        super().__init__(*args)


_P = ParamSpec('_P')


class ProcessingContext(abc.ABC):
    """
    Represents the deferred in-memory state of an asset being processed.

    Consecutive operators that share the same :class:`Processor` are grouped
    into a *run* by :class:`Pipeline`.  The processor accumulates each
    operator's effect on the context object and only encodes the result once
    when :meth:`materialize` is called — either at a processor boundary or at
    the end of the pipeline.
    """

    @property
    @abc.abstractmethod
    def processor(self) -> 'Processor':
        """The :class:`Processor` that owns this context."""
        raise NotImplementedError()

    @abc.abstractmethod
    def materialize(self) -> 'Asset':
        """Encode and return the final :class:`Asset`."""
        raise NotImplementedError()


def operator(
    function: Callable[Concatenate[Any, 'Asset', _P], 'Asset'],
) -> Callable[Concatenate[Any, _P], Callable[['Asset'], 'Asset']]:
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
    def wrapper(self: Any, **kwargs: _P.kwargs) -> Callable[['Asset'], 'Asset']:
        configured_operator = functools.partial(function, self, **kwargs)
        return configured_operator

    return wrapper


class _BranchStep:
    """Internal step that fans out each asset into one output per sub-pipeline."""

    def __init__(self, pipelines: tuple['Pipeline', ...]) -> None:
        self.pipelines = pipelines


class _WhenStep:
    """Internal step that conditionally applies one of two operators."""

    def __init__(
        self,
        predicate: Callable[['Asset'], bool],
        then: Callable[['Asset'], 'Asset'],
        else_: Callable[['Asset'], 'Asset'] | None,
    ) -> None:
        self.predicate = predicate
        self.then = then
        self.else_ = else_


# A pipeline step is either a plain operator callable or one of the control-flow
# step objects introduced by Pipeline.branch() and Pipeline.when().
_PipelineStep = Callable[['Asset'], 'Asset'] | _BranchStep | _WhenStep


class Pipeline:
    """
    Represents a processing pipeline for :class:`~madam.core.Asset` objects.

    The pipeline can be configured to hold a list of asset processing
    operators, all of which are applied to one or more assets when calling the
    :func:`~madam.core.Pipeline.process` method.

    In addition to linear chains of operators, the pipeline supports fan-out
    via :meth:`branch` and conditional dispatch via :meth:`when`.
    """

    def __init__(self) -> None:
        """
        Initializes a new pipeline without operators.
        """
        self.operators: MutableSequence[_PipelineStep] = []

    def process(self, *assets: Asset) -> Generator[Asset, float, None]:
        """
        Applies the operators in this pipeline on the specified assets.

        :param \\*assets: Asset objects to be processed
        :type \\*assets: Asset
        :return: Generator with processed assets
        """
        current: list[Asset] = list(assets)
        for step in self.operators:
            if isinstance(step, _BranchStep):
                next_assets: list[Asset] = []
                for asset in current:
                    for sub_pipeline in step.pipelines:
                        next_assets.extend(sub_pipeline.process(asset))
                current = next_assets
            elif isinstance(step, _WhenStep):
                next_assets = []
                for asset in current:
                    if step.predicate(asset):
                        next_assets.append(step.then(asset))
                    elif step.else_ is not None:
                        next_assets.append(step.else_(asset))
                    else:
                        next_assets.append(asset)
                current = next_assets
            else:
                current = [step(asset) for asset in current]
        yield from current

    def add(self, operator: Callable) -> None:
        """
        Appends the specified operator to the processing chain.

        :param operator: Operator to be added
        """
        self.operators.append(operator)

    def branch(self, *pipelines: 'Pipeline') -> None:
        """
        Adds a fan-out step that sends each incoming asset through every
        sub-pipeline, yielding one output asset per sub-pipeline per input.

        :param \\*pipelines: Sub-pipelines to fan out into
        """
        self.operators.append(_BranchStep(pipelines))

    def when(
        self,
        predicate: Callable[['Asset'], bool],
        then: Callable[['Asset'], 'Asset'],
        else_: Callable[['Asset'], 'Asset'] | None = None,
    ) -> None:
        """
        Adds a conditional step that applies *then* when *predicate* returns
        ``True`` and *else_* (if given) otherwise.  When *predicate* returns
        ``False`` and no *else_* is provided, the asset passes through unchanged.

        :param predicate: Callable that receives an asset and returns a bool
        :param then: Operator applied when *predicate* is ``True``
        :param else_: Operator applied when *predicate* is ``False``; optional
        """
        self.operators.append(_WhenStep(predicate, then, else_))


class Processor(metaclass=abc.ABCMeta):
    """
    Represents an entity that can create :class:`~madam.core.Asset` objects
    from binary data.

    Every `Processor` needs to have an `__init__` method with an optional
    `config` parameter in order to be registered correctly.
    """

    @abc.abstractmethod
    def __init__(self, config: Mapping[str, Any] | None = None) -> None:
        """
        Initializes a new `Processor`.

        :param config: Mapping with settings.
        """
        self.config: dict[str, Any] = dict(config) if config else {}

    @property
    def supported_mime_types(self) -> frozenset:
        """MIME types this processor can handle (used to build the Madam index)."""
        return frozenset()

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
    def __init__(self, config: Mapping[str, Any] | None = None) -> None:
        """
        Initializes a new `MetadataProcessor`.
        """
        self.config: dict[str, Any] = dict(config) if config else {}

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

    def __init__(self, config: Mapping[str, Any] | None = None) -> None:
        """
        Initializes a new library instance with default configuration.

        The default configuration includes a list of all available Processor
        and MetadataProcessor implementations.

        :param config: Mapping with settings.
        """
        self.config: dict[str, Any] = dict(config) if config else {}

        # Initialize processors
        # Order matters: more specific processors must come before general-purpose
        # ones.  PillowProcessor handles still-image formats (including AVIF) and
        # must be checked before FFmpegProcessor, which also accepts AVIF via the
        # MP4/ISOBMFF container and would misidentify it as video/quicktime.
        self.processors = {
            'madam.image.PillowProcessor',
            'madam.vector.SVGProcessor',
            'madam.ffmpeg.FFmpegProcessor',
        }
        _processor_priority = [
            'madam.image.PillowProcessor',
            'madam.vector.SVGProcessor',
            'madam.ffmpeg.FFmpegProcessor',
        ]

        def _proc_key(p: str) -> int:
            return _processor_priority.index(p) if p in _processor_priority else len(_processor_priority)

        self._processors = []
        for processor_path in sorted(self.processors, key=_proc_key):
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
            'madam.iptc.IPTCMetadataProcessor',
            'madam.xmp.XMPMetadataProcessor',
            'madam.vector.SVGMetadataProcessor',
            'madam.ffmpeg.FFmpegMetadataProcessor',
        }
        _metadata_processor_priority = [
            'madam.exif.ExifMetadataProcessor',
            'madam.iptc.IPTCMetadataProcessor',
            'madam.xmp.XMPMetadataProcessor',
            'madam.vector.SVGMetadataProcessor',
            'madam.ffmpeg.FFmpegMetadataProcessor',
        ]

        def _meta_key(p: str) -> int:
            pri = _metadata_processor_priority
            return pri.index(p) if p in pri else len(pri)

        self._metadata_processors = []
        for processor_path in sorted(self.metadata_processors, key=_meta_key):
            try:
                processor_class = Madam._import_from(processor_path)
            except ImportError:
                self.metadata_processors.remove(processor_path)
                continue
            processor = processor_class(self.config)
            self._metadata_processors.append(processor)

        # Build a MIME-type → processor index for O(1) lookup.
        # The _processors list is already in priority order, so the first
        # processor that claims a MIME type wins (e.g. PillowProcessor beats
        # FFmpegProcessor for image/jpeg).
        self._mime_type_to_processor: dict[str, Processor] = {}
        for _proc in self._processors:
            for _mt in _proc.supported_mime_types:
                _key = str(_mt)
                if _key not in self._mime_type_to_processor:
                    self._mime_type_to_processor[_key] = _proc

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

    def get_processor(self, source: 'Asset | IO | str') -> 'Processor':
        """
        Returns a processor that can handle the given source.

        Three calling forms are supported:

        - ``get_processor(asset)`` — fast O(1) lookup by ``asset.mime_type``;
          falls back to byte-probing the essence when the MIME type is not in
          the index.
        - ``get_processor('image/jpeg')`` — fast O(1) lookup by MIME type string.
        - ``get_processor(file)`` — slow byte-probe loop (same as before).

        :param source: An :class:`Asset`, a MIME type string, or a file-like object.
        :raises UnsupportedFormatError: if no processor can handle the given source.
        :return: Processor that can handle the source.
        :rtype: Processor
        """
        if isinstance(source, Asset):
            processor = self._mime_type_to_processor.get(str(source.mime_type))
            if processor is not None:
                return processor
            source = source.essence  # fall back to byte probe

        if isinstance(source, str):
            processor = self._mime_type_to_processor.get(source)
            if processor is not None:
                return processor
            raise UnsupportedFormatError(f'No processor found for MIME type {source!r}')

        # IO path: existing can_read() probe loop
        for processor in self._processors:
            source.seek(0)
            if processor.can_read(source):
                source.seek(0)
                return processor
        raise UnsupportedFormatError()

    def read(self, file: IO, additional_metadata: Mapping | None = None):
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
            raise TypeError(f'Unable to read object of type {type(file)}')

        processor = self.get_processor(file)
        asset = processor.read(file)
        asset_metadata: dict[str, Any] = dict(asset.metadata)

        # Pass 1: collect metadata from all processors using the original file.
        # Essence is not copied or stripped here.
        handled_formats: set[str] = set()
        for metadata_processor in self._metadata_processors:
            file.seek(0)
            try:
                metadata_by_format = metadata_processor.read(file)
                for fmt, values in metadata_by_format.items():
                    if fmt not in handled_formats:
                        asset_metadata[fmt] = values
                handled_formats.update(metadata_processor.formats)
            except UnsupportedFormatError:
                pass

        # Pass 2: strip metadata from essence, chaining each processor's output
        # into the next.  Only one IO object is live per iteration.
        stripped: IO = asset.essence
        for metadata_processor in self._metadata_processors:
            try:
                stripped = metadata_processor.strip(stripped)
            except UnsupportedFormatError:
                stripped.seek(0)

        # Pass 3: normalize the most authoritative creation timestamp into a
        # top-level 'created_at' key (ISO 8601 string).  Sources are checked
        # in priority order: EXIF > XMP > FFmpeg container metadata.
        created_at: str | None = None
        exif = asset_metadata.get('exif', {})
        dt = exif.get('datetime_original') or exif.get('datetime_digitized')
        if dt is not None:
            created_at = dt.strftime('%Y-%m-%dT%H:%M:%S')
        if created_at is None:
            xmp = asset_metadata.get('xmp', {})
            created_at = xmp.get('create_date')
        if created_at is None:
            ffmeta = asset_metadata.get('ffmetadata', {})
            created_at = ffmeta.get('creation_time')
        if created_at is not None:
            asset_metadata['created_at'] = created_at

        # Pass 4: apply caller-supplied overrides and construct the final asset.
        if additional_metadata:
            asset_metadata.update(additional_metadata)
        return Asset._from_bytes(stripped.read(), **asset_metadata)

    def strip(self, asset: Asset) -> Asset:
        """
        Returns a copy of the asset with all embedded metadata removed from
        both the essence bytes and the metadata dict.

        Structural properties such as ``mime_type``, ``width``, ``height``,
        and ``duration`` are preserved.  Format-specific metadata
        (``exif``, ``xmp``, ``iptc``, ``ffmetadata``, ``rdf``, …) and the
        derived ``created_at`` key are dropped.

        :param asset: Asset to strip
        :type asset: Asset
        :return: New asset without metadata
        :rtype: Asset
        :raises UnsupportedFormatError: if the asset format is not supported
        """
        processor = self.get_processor(asset)
        stripped: IO = asset.essence
        for metadata_processor in self._metadata_processors:
            try:
                stripped = metadata_processor.strip(stripped)
            except UnsupportedFormatError:
                stripped.seek(0)
        stripped.seek(0)
        return processor.read(stripped)

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
AssetTags = frozenset[str]


class AssetStorage(MutableMapping[AssetKey, tuple[Asset, AssetTags]], Generic[AssetKey]):
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
            if all(asset.metadata.get(key) == value for key, value in kwargs.items()):
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
        return {asset_key for asset_key, (asset, asset_tags) in self.items() if search_tags <= asset_tags}


class IndexedAssetStorage(AssetStorage[AssetKey]):
    """Mixin that maintains an in-memory inverted index over scalar metadata values.

    Makes :meth:`filter` O(k) where k is the number of matching assets instead of
    O(n·c) for n stored assets and c filter criteria.

    Subclasses must call :meth:`_index_asset` in ``__setitem__`` and
    :meth:`_deindex_asset` in ``__delitem__``.
    """

    def __init__(self) -> None:
        super().__init__()
        # Maps (metadata_key, value) -> set of asset keys
        self._index: dict[tuple[str, Any], set[AssetKey]] = {}

    def _index_asset(self, key: AssetKey, asset: Asset) -> None:
        for meta_key, meta_value in asset.metadata.items():
            if isinstance(meta_value, (str, int, float, bool, type(None))):
                self._index.setdefault((meta_key, meta_value), set()).add(key)

    def _deindex_asset(self, key: AssetKey, asset: Asset) -> None:
        for meta_key, meta_value in asset.metadata.items():
            if isinstance(meta_value, (str, int, float, bool, type(None))):
                bucket = self._index.get((meta_key, meta_value))
                if bucket:
                    bucket.discard(key)

    def filter(self, **kwargs: Any) -> Iterable[AssetKey]:
        if not kwargs:
            return list(self.keys())
        sets = [self._index.get((k, v), set()) for k, v in kwargs.items()]
        result = sets[0].intersection(*sets[1:])
        return list(result)


class InMemoryStorage(IndexedAssetStorage[Any]):
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
        self._lock = threading.RLock()
        self.store: dict[Any, tuple[Asset, AssetTags]] = {}

    def __setitem__(self, asset_key: AssetKey, asset_and_tags: tuple[Asset, AssetTags]):
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
        with self._lock:
            # Deindex old asset if replacing an existing key.
            if asset_key in self.store:
                self._deindex_asset(asset_key, self.store[asset_key][0])
            self.store[asset_key] = asset, frozenset(tags)
            self._index_asset(asset_key, asset)

    def __getitem__(self, asset_key: AssetKey) -> tuple[Asset, AssetTags]:
        """
        Returns a tuple of the :class:`~madam.core.Asset` with the specified
        key and the tags associated with the asset.

        An error will be raised if the key does not exist.

        :param asset_key: Key of the asset for which the tags should be returned
        :return: A tuple containing an asset and a set of the tags associated with the asset
        :rtype: Tuple[Asset, Set[str]]
        :raise KeyError: if the key does not exist in this storage
        """
        with self._lock:
            if asset_key not in self.store:
                raise KeyError(f'Asset with key {asset_key!r} cannot be found in storage')
            return self.store[asset_key]

    def __delitem__(self, asset_key: AssetKey) -> None:
        """
        Removes the :class:`~madam.core.Asset` with the specified key from this
        asset storage, as well as all associated data (e.g. tags).

        :param asset_key: Key of the asset to be removed
        :raise KeyError: if the key does not exist in this storage
        """
        with self._lock:
            if asset_key not in self.store:
                raise KeyError(f'Asset with key {asset_key!r} cannot be found in storage')
            self._deindex_asset(asset_key, self.store[asset_key][0])
            del self.store[asset_key]

    def __contains__(self, asset_key: AssetKey) -> bool:
        """
        Returns whether an asset with the specified key is stored in this
        asset storage.

        :param asset_key: Key of the asset that should be tested
        :return: `True` if the key exists, `False` otherwise
        :rtype: bool
        """
        with self._lock:
            return asset_key in self.store

    def __iter__(self) -> Iterator[AssetKey]:
        """
        Returns an object that can be used to iterate all asset that are stored
        in this asset storage.

        :return: Iterator object
        """
        with self._lock:
            return iter(list(self.store.keys()))

    def __len__(self) -> int:
        """
        Returns the number of assets in this storage.

        :return: Number of assets in this storage
        :rtype: int
        """
        with self._lock:
            return len(self.store)


class ShelveStorage(AssetStorage[str]):
    """
    Represents a persistent storage backend for :class:`~madam.core.Asset`
    objects. Asset keys must be strings.

    ShelveStorage uses a file on the file system to serialize Assets.
    """

    def __init__(self, path: Path | str):
        """
        Initializes a new `ShelveStorage` with the specified path.

        :param path: File system path where the data should be stored
        :type path: pathlib.Path or str
        """
        super().__init__()
        if os.path.exists(str(path)) and not os.path.isfile(str(path)):
            raise ValueError(f'The storage path {path!r} is not a file.')
        self.path = path

    def __setitem__(self, asset_key: str, asset_and_tags: tuple[Asset, AssetTags]) -> None:
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
        with shelve.open(str(self.path)) as store:
            store[asset_key] = asset, tags

    def __getitem__(self, asset_key: str) -> tuple[Asset, AssetTags]:
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
        with shelve.open(str(self.path)) as store:
            if asset_key not in store:
                raise KeyError(f'Asset with key {asset_key!r} cannot be found in storage')
            return store[asset_key]

    def __delitem__(self, asset_key: str) -> None:
        """
        Removes the :class:`~madam.core.Asset` with the specified key from this
        asset storage, as well as all associated data (e.g. tags).

        :param asset_key: Key of the asset to be removed
        :type asset_key: str
        :raise KeyError: if the key does not exist in this storage
        """
        with shelve.open(str(self.path)) as store:
            if asset_key not in store:
                raise KeyError(f'Asset with key {asset_key!r} cannot be found in storage')
            del store[asset_key]

    def __contains__(self, asset_key: object) -> bool:
        """
        Returns whether an asset with the specified key is stored in this
        asset storage.
        :param asset_key: Key of the asset that should be tested
        :type asset_key: str
        :return: `True` if the key exists, `False` otherwise
        :rtype: bool
        """
        if not isinstance(asset_key, str):
            return False
        with shelve.open(str(self.path)) as store:
            return asset_key in store

    def __iter__(self) -> Iterator[str]:
        """
        Returns an object that can be used to iterate all asset that are stored
        in this asset storage.
        :return: Iterator object
        """
        with shelve.open(str(self.path)) as store:
            return iter(list(store.keys()))

    def __len__(self) -> int:
        """
        Returns the number of assets in this storage.
        :return: Number of assets in this storage
        :rtype: int
        """
        with shelve.open(str(self.path)) as store:
            return len(store)


class FileSystemAssetStorage(AssetStorage[str]):
    """
    A persistent :class:`AssetStorage` that writes each asset as two files
    on the filesystem:

    * ``<key>/essence`` — raw essence bytes
    * ``<key>/metadata.json`` — JSON-encoded metadata and tags

    The storage is designed to work on any POSIX mount point, including
    network file systems (NFS, CIFS) and object-store-backed FUSE mounts
    (e.g. s3fs, rclone).  Asset keys must be valid directory-name strings
    (no path separators).

    Because files are written atomically (write to a temp file then rename),
    the storage is safe for concurrent writes from multiple Celery workers
    on a shared file system.
    """

    def __init__(self, path: Path | str) -> None:
        """
        Initialises a new :class:`FileSystemAssetStorage` rooted at *path*.

        The directory is created if it does not already exist.

        :param path: Root directory for stored assets.
        """
        super().__init__()
        self._root = Path(path)
        self._root.mkdir(parents=True, exist_ok=True)

    def _asset_dir(self, key: str) -> Path:
        return self._root / key

    def _essence_path(self, key: str) -> Path:
        return self._asset_dir(key) / 'essence'

    def _metadata_path(self, key: str) -> Path:
        return self._asset_dir(key) / 'metadata.json'

    def __setitem__(self, asset_key: str, asset_and_tags: tuple[Asset, AssetTags]) -> None:
        asset, tags = asset_and_tags
        if not tags:
            tags = frozenset()
        asset_dir = self._asset_dir(asset_key)
        asset_dir.mkdir(parents=True, exist_ok=True)

        # Write essence atomically.
        essence_path = self._essence_path(asset_key)
        tmp_essence = essence_path.with_suffix('.tmp')
        with open(tmp_essence, 'wb') as fh:
            shutil.copyfileobj(asset.essence, fh)
        tmp_essence.replace(essence_path)

        # Write metadata + tags atomically.
        metadata_dict = _mutable(asset.metadata)
        payload = {'metadata': metadata_dict, 'tags': list(tags)}
        meta_path = self._metadata_path(asset_key)
        tmp_meta = meta_path.with_suffix('.tmp')
        with open(tmp_meta, 'w', encoding='utf-8') as fh:
            json.dump(payload, fh)
        tmp_meta.replace(meta_path)

    def __getitem__(self, asset_key: str) -> tuple[Asset, AssetTags]:
        meta_path = self._metadata_path(asset_key)
        if not meta_path.exists():
            raise KeyError(f'Asset with key {asset_key!r} not found in FileSystemAssetStorage')
        with open(meta_path, encoding='utf-8') as fh:
            payload = json.load(fh)
        tags = frozenset(payload.get('tags', []))
        metadata = payload.get('metadata', {})
        with open(self._essence_path(asset_key), 'rb') as fh:
            essence_bytes = fh.read()
        asset = Asset(io.BytesIO(essence_bytes), **metadata)
        return asset, tags

    def __delitem__(self, asset_key: str) -> None:
        asset_dir = self._asset_dir(asset_key)
        if not asset_dir.exists():
            raise KeyError(f'Asset with key {asset_key!r} not found in FileSystemAssetStorage')
        shutil.rmtree(asset_dir)

    def __contains__(self, asset_key: object) -> bool:
        if not isinstance(asset_key, str):
            return False
        return self._essence_path(asset_key).exists()

    def __iter__(self) -> Iterator[str]:
        return (p.name for p in sorted(self._root.iterdir()) if p.is_dir())

    def __len__(self) -> int:
        return sum(1 for p in self._root.iterdir() if p.is_dir())
