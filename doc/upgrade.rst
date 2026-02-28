Upgrade Guide
=============

This page documents all changes users of the MADAM library need to be aware
of when upgrading from one release to the next.

.. contents::
   :local:
   :depth: 2


0.22.0 → 0.23.0
----------------

Breaking changes
~~~~~~~~~~~~~~~~

Changed: ``OperatorError`` message format
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

:class:`~madam.core.OperatorError` messages raised by
:class:`~madam.ffmpeg.FFmpegProcessor` operators now follow the pattern::

   Could not <operation>: <last stderr line>

Previously the full FFmpeg stderr output was included verbatim.  Code that
parsed the error message text must be updated to match the new, shorter format.

Changed: ``Asset.__getattr__`` no longer forwards dunder lookups
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

:class:`~madam.core.Asset.__getattr__` no longer forwards Python protocol
names (dunder attributes such as ``__len__`` or ``__iter__``) into the
metadata dict.  Accessing a dunder attribute that is not defined on the class
now raises :exc:`AttributeError` as expected by the Python data model.

This only affects code that stored a key like ``'__len__'`` in asset metadata
and accessed it via attribute syntax.  Direct dict access
(``asset.metadata['__len__']``) still works.

Changed: ``exif['_raw']`` key added for unmapped EXIF fields
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

:meth:`~madam.exif.ExifMetadataProcessor.read` now stores EXIF fields that
have no entry in ``metadata_to_exif`` under the reserved key ``'_raw'`` inside
the ``exif`` metadata dict, instead of silently discarding them.

.. code-block:: python

   metadata = processor.read(jpeg_file)
   print(metadata['exif'].get('_raw'))
   # {'0th.40961': b'...',  ...}   # ColorSpace, UserComment, etc.

The ``_raw`` value is a plain ``dict`` keyed as ``'<IFD>.<tag_int>'`` with
raw EXIF values as returned by *piexif* (bytes, tuples, or ints).  These
values are written back verbatim by
:meth:`~madam.exif.ExifMetadataProcessor.combine`.

Code that previously asserted ``len(metadata['exif']) == <N>`` (counting only
mapped fields) may need to account for the additional ``'_raw'`` key when the
image contains unmapped EXIF tags.

Changed: ``UnsupportedFormatError`` is now a ``PermanentOperatorError``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

:class:`~madam.core.UnsupportedFormatError` is now a subclass of
:class:`~madam.core.PermanentOperatorError` (itself a subclass of
:class:`~madam.core.OperatorError`).  Existing ``except OperatorError`` and
``except UnsupportedFormatError`` clauses continue to work.  If you catch
:class:`~madam.core.OperatorError` and need to distinguish retryable failures
from permanent ones, see the new error hierarchy below.


Changes requiring attention
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Changed: ``FFmpegProcessor.__init__`` raises ``EnvironmentError`` on bad setup
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

:class:`~madam.ffmpeg.FFmpegProcessor` now raises :exc:`EnvironmentError`
(rather than crashing with an unhandled exception) if:

* ``ffprobe`` is not found on ``PATH`` — message contains ``'not found'``.
* The ``ffprobe`` version check times out — message contains ``'timed out'``.
* The detected version is below the minimum (3.3) — message includes the
  detected version string.

Changed: ``PillowProcessor`` warns on unknown config keys
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

:class:`~madam.image.PillowProcessor` now emits a :exc:`UserWarning` when a
configuration mapping passed to the constructor contains a key that is not
recognised for the target MIME type.  For example:

.. code-block:: python

   import warnings
   warnings.simplefilter('always')

   processor = PillowProcessor({'image/jpeg': {'qualiti': 90}})
   # When convert(mime_type='image/jpeg') is called:
   # UserWarning: Unknown config key 'qualiti' for format image/jpeg.
   #              Valid keys: ['progressive', 'quality']

Previously unrecognised keys were silently ignored.  Check your
``PillowProcessor`` config dicts and correct any misspelled keys.

Valid keys per format:

* ``image/avif`` — ``quality``, ``speed``
* ``image/gif`` — ``optimize``
* ``image/jpeg`` — ``quality``, ``progressive``
* ``image/png`` — ``optimize``, ``zopfli``, ``zopfli_strategies``
* ``image/tiff`` — ``compression``
* ``image/webp`` — ``quality``, ``method``

Changed: ``FFmpegProcessor._threads`` is now a property
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The private attribute ``_FFmpegProcessor__threads`` (name-mangled) no longer
exists.  It has been replaced by the ``_threads`` property, which evaluates
``multiprocessing.cpu_count()`` fresh on each access so that containerised
deployments that change CPU affinity at runtime are handled correctly.

If you accessed ``processor._FFmpegProcessor__threads`` in your code, update
it to ``processor._threads``.


New features
~~~~~~~~~~~~

New: retry-aware error hierarchy
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Two new :class:`~madam.core.OperatorError` subclasses allow worker tasks to
decide whether to retry or move a job to a dead-letter queue:

* :class:`~madam.core.TransientOperatorError` — the operation failed for a
  reason that may resolve on retry (e.g. a temporary resource constraint).
* :class:`~madam.core.PermanentOperatorError` — the operation can never
  succeed with this input (e.g. unsupported format or codec).
  :class:`~madam.core.UnsupportedFormatError` is now a subclass of this.

.. code-block:: python

   from madam.core import TransientOperatorError, PermanentOperatorError

   try:
       result = operator(asset)
   except TransientOperatorError:
       queue.retry()
   except PermanentOperatorError:
       queue.dead_letter()

New: ``Asset.content_id``
^^^^^^^^^^^^^^^^^^^^^^^^^^

:class:`~madam.core.Asset` now exposes a ``content_id`` property that returns
a hex-encoded SHA-256 digest of the asset's essence bytes.  Two assets with
identical binary content share the same ``content_id``, making it suitable as
an object-store key or a cache lookup key.

.. code-block:: python

   asset = madam.read(open('photo.jpg', 'rb'))
   print(asset.content_id)
   # 'e3b0c44298fc1c149afb…'

New: ``madam.default_madam`` singleton
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

A module-level lazy singleton is now available for scripts that do not need a
custom configuration:

.. code-block:: python

   import madam
   asset = madam.default_madam.read(open('photo.jpg', 'rb'))

The singleton is created on first access and reused thereafter.

New: ``FFmpegProcessor`` thread count configuration
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The number of threads used by FFmpeg can be capped via the processor config:

.. code-block:: python

   from madam.ffmpeg import FFmpegProcessor
   processor = FFmpegProcessor(config={'ffmpeg': {'threads': 4}})

When unset (or set to ``0``), the default is ``multiprocessing.cpu_count()``.

New: ``LazyAsset``
^^^^^^^^^^^^^^^^^^^

:class:`~madam.core.LazyAsset` is an :class:`~madam.core.Asset` subclass that
stores only a URI and metadata dict.  Essence bytes are fetched on demand via
a caller-supplied loader callable.  Pickling a ``LazyAsset`` produces a small
payload (URI + metadata only), making it safe to send through message brokers
even for large video files.

.. code-block:: python

   from madam.core import LazyAsset

   def load(uri):
       return open(uri, 'rb')

   asset = LazyAsset(uri='s3://bucket/video.mp4', loader=load,
                     mime_type='video/mp4', duration=120.5)
   # essence is fetched only when asset.essence is accessed

New: ``progress_callback`` in ``FFmpegProcessor.convert``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

:meth:`~madam.ffmpeg.FFmpegProcessor.convert` now accepts an optional
``progress_callback`` keyword argument.  When provided it is called after each
FFmpeg progress block with a ``dict[str, str]`` of progress fields (``frame``,
``fps``, ``out_time``, ``speed``, etc.).

.. code-block:: python

   def on_progress(info):
       print(f"speed={info.get('speed')}  time={info.get('out_time')}")

   convert = processor.convert(mime_type='video/mp4',
                                progress_callback=on_progress)
   result = convert(asset)

New: ``FileSystemAssetStorage``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

A new storage backend :class:`~madam.core.FileSystemAssetStorage` stores each
asset as two files on disk: essence bytes and a JSON metadata/tags sidecar.
Writes are atomic (write-then-rename), making it safe for concurrent workers
on shared NFS or object-store FUSE mounts.  Asset keys are directory names;
the root directory is created automatically on init.

.. code-block:: python

   from madam.core import FileSystemAssetStorage

   storage = FileSystemAssetStorage('/var/lib/madam/assets')
   storage['my-key'] = (asset, {'project': 'demo'})

New: additional format support
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The following formats are now supported out of the box:

* **Image**: AVIF (read and write via Pillow; default quality 80, speed 6)
* **Audio**: AAC (ADTS), FLAC (read); AAC, FLAC, Opus, WebM audio (encode targets)
* **Video**: MP4 (``video/mp4``), WebM (``video/webm``) as encode targets

New: ``VideoCodec`` and ``AudioCodec`` constant classes
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Two new classes provide stable, named constants for the codec strings accepted
by :meth:`~madam.ffmpeg.FFmpegProcessor.convert`.

.. code-block:: python

   from madam.video import VideoCodec
   from madam.audio import AudioCodec

   # Instead of raw FFmpeg strings:
   processor.convert(mime_type='video/mp4', video={'codec': 'libx264'})
   # Use named constants:
   processor.convert(mime_type='video/mp4', video={'codec': VideoCodec.H264})

Available constants:

* ``VideoCodec.H264`` — ``'libx264'``
* ``VideoCodec.H265`` — ``'libx265'``
* ``VideoCodec.VP8`` — ``'libvpx'``
* ``VideoCodec.VP9`` — ``'libvpx-vp9'``
* ``VideoCodec.AV1`` — ``'libaom-av1'``
* ``VideoCodec.COPY`` — ``'copy'`` (stream copy, no re-encoding)
* ``VideoCodec.NONE`` — ``None`` (drop the video stream; ``-vn``)

* ``AudioCodec.AAC`` — ``'aac'``
* ``AudioCodec.OPUS`` — ``'libopus'``
* ``AudioCodec.VORBIS`` — ``'libvorbis'``
* ``AudioCodec.MP3`` — ``'libmp3lame'``
* ``AudioCodec.FLAC`` — ``'flac'``
* ``AudioCodec.COPY`` — ``'copy'``
* ``AudioCodec.NONE`` — ``None`` (drop the audio stream; ``-an``)

Raw codec strings continue to work for backward compatibility.

New: ``IndexedAssetStorage`` and faster ``InMemoryStorage.filter``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

A new public mixin :class:`~madam.core.IndexedAssetStorage` (in
``madam.core``) maintains an in-memory inverted index over scalar metadata
values so that :meth:`~madam.core.AssetStorage.filter` runs in O(k) time
(k = number of matching assets) rather than scanning all stored assets.

:class:`~madam.core.InMemoryStorage` now inherits from
:class:`~madam.core.IndexedAssetStorage`.  This is backward-compatible: the
public interface is identical.

:class:`~madam.core.ShelveStorage` and
:class:`~madam.core.FileSystemAssetStorage` still use an unindexed linear
scan.
