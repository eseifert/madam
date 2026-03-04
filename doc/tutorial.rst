Tutorial: Processing your first media asset
###########################################

This tutorial walks you through the core workflow of MADAM from scratch.  By
the end you will be able to:

* Read an image file and inspect its metadata
* Resize and convert the image using the configured processor
* Build a reusable pipeline that processes a whole batch of files
* Store the results in a storage backend

You do not need any prior knowledge of MADAM.  You will need Python 3.11 or
later and a copy of your own image file (JPEG, PNG, WebP, etc.) to follow
along.

.. contents::
   :local:
   :depth: 2


Step 1 — Install MADAM
======================

Install MADAM from PyPI::

   pip install madam

If you plan to process audio or video files, also install FFmpeg on your
system.  On most Linux distributions::

   sudo apt-get install ffmpeg   # Debian / Ubuntu
   brew install ffmpeg           # macOS (Homebrew)


Step 2 — Create a registry
===========================

Every interaction with MADAM starts with a :class:`~madam.core.Madam`
instance.  It acts as a registry that automatically selects the right
processor for each file format and carries your configuration:

.. code-block:: python

   from madam import Madam

   madam = Madam()

That's all you need for default settings.  In :ref:`step-6-configure` you
will see how to pass custom quality settings.


Step 3 — Read an image
=======================

Open your image file in binary mode and pass it to
:meth:`~madam.core.Madam.read`:

.. code-block:: python

   with open('photo.jpg', 'rb') as f:
       asset = madam.read(f)

``asset`` is now an :class:`~madam.core.Asset` — an immutable object that
holds the raw image data (the *essence*) and the extracted metadata.

Inspect the metadata using attribute access:

.. code-block:: python

   print(asset.mime_type)    # 'image/jpeg'
   print(asset.width)        # e.g. 4000
   print(asset.height)       # e.g. 3000
   print(asset.color_space)  # 'RGB'

If the file contains EXIF data it is available under the ``exif`` key:

.. code-block:: python

   exif = asset.metadata.get('exif', {})
   print(exif.get('camera.model'))      # e.g. 'Canon EOS 5D Mark III'
   print(exif.get('datetime_original')) # datetime.datetime(2024, 6, 15, …)
   print(asset.created_at)              # '2024-06-15T10:30:00'

.. note::

   ``madam.read()`` automatically strips embedded metadata (EXIF, IPTC, XMP)
   from the essence so that the raw bytes represent *only* the pixel data.
   The metadata is stored separately in ``asset.metadata``.


Step 4 — Get a processor and run an operator
=============================================

To transform an asset you need a *processor* — an object that knows how to
manipulate a particular format.  Rather than importing a processor class
directly, use :meth:`~madam.core.Madam.get_processor` to obtain the processor
that was configured for this asset's format:

.. code-block:: python

   processor = madam.get_processor(asset)

This returns the same processor instance that ``madam.read()`` used
internally, already initialised with the Madam instance's configuration.
It works with images, audio, and video alike — you never need to import
:class:`~madam.image.PillowProcessor` or :class:`~madam.ffmpeg.FFmpegProcessor`
directly.

Now create a *resize operator* — a callable that takes an asset and returns a
resized version:

.. code-block:: python

   from madam.image import ResizeMode

   make_thumbnail = processor.resize(width=200, height=200, mode=ResizeMode.FIT)

The operator is configured once and can be applied to any number of assets.
Apply it to your photo:

.. code-block:: python

   thumbnail = make_thumbnail(asset)

   print(thumbnail.width)   # 200 (or less, because FIT keeps the aspect ratio)
   print(thumbnail.height)  # 200 (or less)

The original ``asset`` is unchanged — MADAM never mutates assets.


Step 5 — Convert format and save
==================================

Create a format-conversion operator and chain it:

.. code-block:: python

   to_webp = processor.convert(mime_type='image/webp')
   webp_thumbnail = to_webp(thumbnail)

   print(webp_thumbnail.mime_type)  # 'image/webp'

Write the result to disk with :meth:`~madam.core.Madam.write`:

.. code-block:: python

   with open('thumbnail.webp', 'wb') as f:
       madam.write(webp_thumbnail, f)

You can also write the raw essence directly if you prefer:

.. code-block:: python

   with open('thumbnail.webp', 'wb') as f:
       f.write(webp_thumbnail.essence.read())


.. _step-6-configure:

Step 6 — Configure format defaults
=====================================

Pass a configuration dictionary to ``Madam()`` to set quality and codec
defaults.  These settings are automatically applied by the processor that
``get_processor()`` returns:

.. code-block:: python

   madam = Madam({
       'image/jpeg': {'quality': 85, 'progressive': True},
       'image/webp': {'quality': 80, 'method': 6},
   })

   with open('photo.jpg', 'rb') as f:
       asset = madam.read(f)

   processor = madam.get_processor(asset)
   convert = processor.convert(mime_type='image/jpeg')
   result = convert(asset)
   # The result is saved at quality=85 because the Madam config says so.

See :doc:`configuration` for the full list of options for every format.


Step 7 — Build a pipeline
===========================

When you need to apply the same sequence of operators to many assets, use a
:class:`~madam.core.Pipeline`:

.. code-block:: python

   from madam.core import Pipeline
   from madam.image import ResizeMode

   # Build the pipeline once.
   pipeline = Pipeline()
   pipeline.add(processor.resize(width=800, height=800, mode=ResizeMode.FIT))
   pipeline.add(processor.sharpen(radius=1, percent=100))
   pipeline.add(processor.convert(mime_type='image/webp'))

   # Read all source images.
   import pathlib

   sources = []
   for path in pathlib.Path('originals/').glob('*.jpg'):
       with open(path, 'rb') as f:
           sources.append(madam.read(f))

   # Process and save.
   for processed in pipeline.process(*sources):
       name = processed.content_id + '.webp'
       with open(f'output/{name}', 'wb') as f:
           madam.write(processed, f)

:attr:`~madam.core.Asset.content_id` is a SHA-256 digest of the essence bytes,
making it a safe unique filename.


Step 8 — Store assets
======================

Use a storage backend to keep assets organised and searchable.  The simplest
backend is :class:`~madam.core.InMemoryStorage`:

.. code-block:: python

   from madam.core import InMemoryStorage

   storage = InMemoryStorage()

   for path in pathlib.Path('originals/').glob('*.jpg'):
       with open(path, 'rb') as f:
           asset = madam.read(f)
       # Store with a key and tags.
       storage[path.stem] = (asset, {'photo', 'original'})

   # Retrieve by key.
   hero, tags = storage['hero']

   # Filter by metadata value.
   jpegs = list(storage.filter(mime_type='image/jpeg'))

   # Filter by tag.
   originals = list(storage.filter_by_tags({'original'}))

For persistent storage across restarts, use
:class:`~madam.core.FileSystemAssetStorage` instead — it writes one file per
asset to a directory atomically:

.. code-block:: python

   from madam.core import FileSystemAssetStorage

   storage = FileSystemAssetStorage('/var/lib/myapp/assets')
   storage['hero'] = (asset, {'homepage'})


What's next?
=============

Now that you know the basics, explore the rest of the documentation:

* :doc:`howto` — Practical recipes for specific tasks (effects, metadata,
  video, pipelines, optional formats, …)
* :doc:`explanation` — Why MADAM is designed the way it is (immutable assets,
  the operator pattern, format detection, …)
* :doc:`configuration` — Full reference for all format-specific settings
* :ref:`modindex` — Complete API reference for every class and function
