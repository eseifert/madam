Overview
########

Main registry
=============

The class :class:`madam.core.Madam` manages the extensions that can be used to
process different file formats and provides convenience methods to read and
write files.  The simplest way to create a registry with default settings is:

.. code-block:: python

   from madam import Madam

   madam = Madam()

For scripts that do not need a custom configuration, a lazily-initialised
module-level singleton is also available:

.. code-block:: python

   import madam

   asset = madam.default_madam.read(open('photo.jpg', 'rb'))

Format-specific defaults (quality, codec options, etc.) can be passed as a
configuration dictionary to the constructor.  See :doc:`configuration` for
the full list of options.


Media assets
============

At the core of MADAM are **assets** in the form of :class:`madam.core.Asset`
objects.  An asset is an immutable value object that holds:

* **essence** — the raw media bytes, accessible as a file-like object via
  ``asset.essence``.
* **metadata** — a :class:`frozendict` of key/value pairs accessible as
  attributes (``asset.width``) *or* via the ``metadata`` dict.

Assets are typically created by calling :meth:`~madam.core.Madam.read`:

.. code-block:: python

   with open('photo.jpg', 'rb') as f:
       asset = madam.read(f)

   print(asset.mime_type)   # 'image/jpeg'
   print(asset.width)       # e.g. 4000
   print(asset.height)      # e.g. 3000
   print(asset.color_space) # 'RGB'

Because assets are immutable, every transformation returns a *new* asset
rather than modifying the original:

.. code-block:: python

   resized = make_thumbnail(asset)    # new Asset, 'asset' is unchanged
   assert asset.width == 4000         # original unaffected

Each asset also has a content-addressed identifier:

.. code-block:: python

   print(asset.content_id)
   # 'e3b0c44298fc1c149afb4c8996fb92427ae41e4649b934ca495991b7852b855'

Two assets with identical essence bytes always share the same ``content_id``,
making it suitable as an object-store key or a deduplication handle.


Processors
==========

The extensions used to read, process, and write file formats are called
**processors**.  There are two types:

Essence processors (or just processors)
    Represented by :class:`madam.core.Processor` objects.  They are
    responsible for reading and writing the raw media data and for providing
    operators that modify it.  One implementation is
    :class:`madam.image.PillowProcessor`.

Metadata processors
    Represented by :class:`madam.core.MetadataProcessor` objects.  They read
    and write metadata *only*, without touching the essence.  Examples include
    :class:`madam.exif.ExifMetadataProcessor` (EXIF in JPEG/WebP),
    :class:`madam.iptc.IPTCMetadataProcessor` (IPTC in JPEG), and
    :class:`madam.xmp.XMPMetadataProcessor` (XMP in JPEG).

You can retrieve the processor for a specific asset directly:

.. code-block:: python

   processor = madam.get_processor(asset)


Operators
=========

Essence processors provide **operators**: methods decorated with
:func:`~madam.core.operator` that are *configured first* and then *applied*
to one or many assets.  This two-step design lets you reuse a configured
callable across many assets without repeating the configuration:

.. code-block:: python

   from madam.image import ResizeMode

   processor = madam.get_processor(asset)

   # Step 1: configure — returns an Asset → Asset callable
   make_thumbnail = processor.resize(width=200, height=200, mode=ResizeMode.FIT)

   # Step 2: apply to any number of assets
   thumbnail_a = make_thumbnail(asset_a)
   thumbnail_b = make_thumbnail(asset_b)

Operators can be stored, passed to functions, and added to pipelines just
like any other callable.

.. note:: Operators can raise :class:`~madam.core.OperatorError` when
    something goes wrong.  See `Error handling`_ below for how to distinguish
    between retryable and permanent failures.

Example — image adjustments (obtain the processor first via ``get_processor``):

.. code-block:: python

   processor = madam.get_processor(asset)

   enhance = processor.adjust_brightness(factor=1.2)
   result = enhance(asset)

   add_vignette = processor.vignette(strength=0.4)
   result = add_vignette(result)

Example — format conversion:

.. code-block:: python

   to_webp = processor.convert(mime_type='image/webp')
   webp_asset = to_webp(asset)

   with open('output.webp', 'wb') as f:
       madam.write(webp_asset, f)


Pipelines
=========

The :class:`madam.core.Pipeline` class makes it easy to apply a sequence of
operators to one or many assets.

Linear pipeline
---------------

.. code-block:: python

   from madam.core import Pipeline
   from madam.image import ResizeMode

   processor = madam.get_processor(asset)

   portrait_pipeline = Pipeline()
   portrait_pipeline.add(processor.resize(width=300, height=300, mode=ResizeMode.FIT))
   portrait_pipeline.add(processor.sharpen(radius=2, percent=120))
   portrait_pipeline.add(processor.convert(mime_type='image/webp'))

   for processed in portrait_pipeline.process(*source_assets):
       with open(f'out_{processed.content_id}.webp', 'wb') as f:
           f.write(processed.essence.read())

Branching pipeline
------------------

:meth:`~madam.core.Pipeline.branch` fans each input asset out through
several independent sub-pipelines, yielding one output per sub-pipeline per
input:

.. code-block:: python

   thumb_pipe = Pipeline()
   thumb_pipe.add(processor.resize(width=150, height=150, mode=ResizeMode.FILL))

   preview_pipe = Pipeline()
   preview_pipe.add(processor.resize(width=1200, height=900, mode=ResizeMode.FIT))

   pipeline = Pipeline()
   pipeline.branch(thumb_pipe, preview_pipe)

   # For 10 source assets this yields 20 assets: thumbnail + preview for each.
   for asset in pipeline.process(*originals):
       ...

Conditional pipeline
--------------------

:meth:`~madam.core.Pipeline.when` applies one operator when a predicate holds,
and optionally another when it does not:

.. code-block:: python

   pipeline = Pipeline()
   pipeline.when(
       predicate=lambda a: a.width > 1920,
       then=processor.resize(width=1920, height=1080, mode=ResizeMode.FIT),
   )
   # Assets at or below 1920 px wide pass through unchanged.

   # With an else_ branch for format normalization:
   pipeline.when(
       predicate=lambda a: a.mime_type == 'image/png',
       then=processor.convert(mime_type='image/webp'),
       else_=processor.convert(mime_type='image/jpeg'),
   )


Metadata
========

:meth:`~madam.core.Madam.read` automatically extracts metadata from all
registered processors and makes it available directly on the returned asset.

Reading metadata
----------------

Metadata is grouped by processor format under top-level keys:

.. code-block:: python

   asset = madam.read(open('photo.jpg', 'rb'))

   # Format metadata set by the essence processor:
   print(asset.mime_type)    # 'image/jpeg'
   print(asset.width)        # 4000
   print(asset.height)       # 3000

   # EXIF metadata (if present):
   exif = asset.metadata.get('exif', {})
   print(exif.get('camera.manufacturer'))  # e.g. 'Canon'
   print(exif.get('camera.model'))         # e.g. 'EOS 5D Mark III'
   print(exif.get('focal_length'))         # e.g. 85.0
   print(exif.get('datetime_original'))    # datetime.datetime object

   # IPTC metadata (if present):
   iptc = asset.metadata.get('iptc', {})
   print(iptc.get('headline'))
   print(iptc.get('keywords'))    # list of strings

   # XMP metadata (if present):
   xmp = asset.metadata.get('xmp', {})
   print(xmp.get('title'))
   print(xmp.get('rights'))

   # Unified creation timestamp (EXIF → XMP → ffmetadata priority):
   print(asset.created_at)    # ISO 8601 string, e.g. '2024-06-15T10:30:00'

Audio and video metadata live under ``'video'`` and ``'audio'`` sub-keys:

.. code-block:: python

   video_asset = madam.read(open('video.mp4', 'rb'))
   print(video_asset.duration)           # seconds, e.g. 120.5
   print(video_asset.metadata['video'])  # {'codec': 'h264', 'bitrate': 4000, …}
   print(video_asset.metadata['audio'])  # {'codec': 'aac', 'sample_rate': 48000, …}

Writing metadata
----------------

Pass a metadata dict to :meth:`~madam.core.Madam.write`; the library
re-embeds metadata into the essence automatically:

.. code-block:: python

   from madam.exif import ExifMetadataProcessor

   exif_proc = ExifMetadataProcessor()

   # Read existing metadata
   with open('photo.jpg', 'rb') as f:
       metadata = exif_proc.read(f)
       f.seek(0)
       plain_essence = exif_proc.strip(f)

   # Add a description
   updated = dict(metadata)
   updated.setdefault('exif', {})['description'] = 'Sunset over the Alps'

   # Re-combine and write
   with open('photo.jpg', 'rb') as f_in, open('annotated.jpg', 'wb') as f_out:
       combined = exif_proc.combine(f_in, updated)
       f_out.write(combined.read())


Storage
=======

MADAM organises media assets using modular **storage backends**.  All backends
subclass :class:`madam.core.AssetStorage` and behave like Python dictionaries,
storing an asset together with its metadata and a set of tag strings.  The
basic store/retrieve pattern is:

.. code-block:: python

   # Store
   storage[asset_key] = (asset, {'portrait', 'holiday_2024'})

   # Retrieve
   asset, tags = storage[asset_key]

Three built-in backends are provided:

:class:`~madam.core.InMemoryStorage`
    Stores assets in a plain Python dictionary.  Thread-safe.  Data is lost
    when the process exits.

    .. code-block:: python

       from madam.core import InMemoryStorage

       storage = InMemoryStorage()
       storage['hero'] = (asset, {'homepage', 'featured'})
       hero, tags = storage['hero']

:class:`~madam.core.ShelveStorage`
    Persists assets to disk using the Python :mod:`shelve` module.

    .. code-block:: python

       from madam.core import ShelveStorage

       storage = ShelveStorage('/var/lib/madam/shelve')
       storage['hero'] = (asset, {'homepage'})

:class:`~madam.core.FileSystemAssetStorage`
    Stores each asset as two files: the essence bytes and a JSON metadata
    sidecar.  Writes are atomic (write-then-rename), making it safe for
    concurrent workers on shared file systems.

    .. code-block:: python

       from madam.core import FileSystemAssetStorage

       storage = FileSystemAssetStorage('/var/lib/madam/assets')
       storage['hero'] = (asset, {'homepage', 'featured'})

Filtering
---------

All backends support filtering by metadata values or by tags:

.. code-block:: python

   # Find all JPEG assets wider than 1000 px
   results = list(storage.filter(mime_type='image/jpeg', width=1000))

   # Find assets tagged with both 'homepage' and 'featured'
   results = list(storage.filter_by_tags({'homepage', 'featured'}))

:class:`~madam.core.InMemoryStorage` uses an inverted index for O(k) filter
performance (k = number of matching assets).  The disk-based backends use a
linear scan.


Error handling
==============

All operator failures raise exceptions from the
:class:`~madam.core.OperatorError` hierarchy:

.. code-block:: python

   from madam.core import OperatorError, TransientOperatorError, PermanentOperatorError

   try:
       result = operator(asset)
   except TransientOperatorError:
       # Temporary failure (e.g. out of memory, disk full) — safe to retry.
       queue.retry()
   except PermanentOperatorError:
       # Permanent failure (e.g. unsupported codec, corrupt input) — do not retry.
       queue.dead_letter()
   except OperatorError:
       # Generic failure — catch-all.
       log.error('Operator failed', exc_info=True)

:class:`~madam.core.UnsupportedFormatError` is a subclass of
:class:`~madam.core.PermanentOperatorError` and is raised when a file format
is not recognised or not supported by the available processors.


.. _FFmpeg: https://ffmpeg.org/
.. _Pillow: https://python-pillow.org/
.. _piexif: https://piexif.readthedocs.io/
