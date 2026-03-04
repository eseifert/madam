Explanation: Why MADAM works the way it does
############################################

This document explains the design philosophy behind MADAM — the *why* rather
than the *what*.  If you want to know what MADAM can do and how to use it, see
:doc:`tutorial`, :doc:`howto`, and the :ref:`modindex`.


.. contents::
   :local:
   :depth: 2


Immutable assets
================

Every MADAM transformation returns a **new** :class:`~madam.core.Asset`
object.  The original is never modified.  This is a deliberate design choice
with several concrete benefits.

Correctness
-----------

Mutation is a common source of bugs.  Consider a pipeline that resizes an
image and then converts it to WebP.  If ``resize()`` mutated the asset
in-place, a later step that needed the original dimensions would silently see
the wrong value.  With immutable assets, every step works with a stable
snapshot — there are no hidden side-effects to reason about.

Thread safety
-------------

Immutable objects can be freely shared between threads without locks.
A single source asset can be fed into many parallel worker threads, each
running a different branch of processing, without any synchronisation
overhead.

Functional composition
----------------------

Because operators are pure ``Asset → Asset`` functions, they compose
naturally.  You can chain them, store them in lists, pass them as arguments,
and build higher-order combinators — just as you would with numeric values.
The :class:`~madam.core.Pipeline` class is only possible *because* operators
are pure functions over immutable data.

.. note::

   The only mutable state in an asset is the file pointer of its ``essence``.
   Calling ``asset.essence.read()`` consumes the stream.  If you need to read
   the essence more than once, call ``asset.essence.seek(0)`` first, or store
   the bytes with ``asset.essence.read()``.


The operator pattern
====================

Processor methods such as ``resize()`` or ``convert()`` do **not** transform
an asset directly.  Instead, they return a *configured callable* — an operator
— that can be applied to any number of assets later:

.. code-block:: python

   # Step 1: configure (fast, no I/O)
   make_thumbnail = processor.resize(width=200, height=200, mode=ResizeMode.FIT)

   # Step 2: apply (does the actual work)
   thumbnail_a = make_thumbnail(asset_a)
   thumbnail_b = make_thumbnail(asset_b)

This two-step design has a few advantages over the alternative of calling
``processor.resize(asset, width=200, height=200)`` directly.

Configure once, apply many
--------------------------

The configuration step validates parameters and captures context once.
Repeated application to many assets pays only the cost of the transformation
itself, not of re-parsing configuration every time.

Composability
-------------

Operators are plain callables (functions).  They can be stored in variables,
put into lists, passed to other functions, and added to pipelines just like
any other Python object.  This makes it trivial to build reusable
"transformation recipes" that are independent of any specific asset.

Separation of concerns
----------------------

The thing that *describes* a transformation is separate from the things it is
applied to.  This makes code easier to test: you can unit-test a configured
operator with a simple mock asset without needing to exercise the full
pipeline.


Choosing the right processor: ``get_processor()``
===================================================

MADAM ships several processor implementations — :class:`~madam.image.PillowProcessor`,
:class:`~madam.ffmpeg.FFmpegProcessor`, :class:`~madam.vector.SVGProcessor`,
and others — but user code should rarely import them directly.

The preferred way to obtain a processor is through
:meth:`~madam.core.Madam.get_processor`:

.. code-block:: python

   processor = madam.get_processor(asset)

There are two reasons to prefer this over direct instantiation.

The processor carries the Madam configuration
----------------------------------------------

When you create a :class:`~madam.core.Madam` instance with a configuration
dictionary, that configuration is forwarded to every processor the instance
creates.  ``get_processor()`` returns one of those pre-configured processor
instances.  A processor created directly — ``PillowProcessor()`` — starts
with default settings and ignores any quality or codec options you may have
set on the ``Madam`` instance.

.. code-block:: python

   # Madam carries quality settings.
   madam = Madam({'image/jpeg': {'quality': 85}})

   # get_processor() returns a processor that already knows about quality=85.
   processor = madam.get_processor(asset)
   output = processor.convert(mime_type='image/jpeg')(asset)
   # → saved at quality=85 ✓

   # Direct instantiation bypasses the config.
   from madam.image import PillowProcessor
   processor = PillowProcessor()
   output = processor.convert(mime_type='image/jpeg')(asset)
   # → saved at the default quality ✗

Format independence
-------------------

``get_processor()`` accepts three kinds of input, selected automatically:

* **An** :class:`~madam.core.Asset` *(preferred)* — performs an O(1) look-up
  using ``asset.mime_type``.  Because the MIME type is already known from the
  earlier ``read()`` call, no I/O is needed.  This is the recommended form.
* **A MIME type string** — also an O(1) look-up, useful when you know the
  format without holding an asset yet.
* **A file-like object** — the original byte-probe loop: each processor's
  ``can_read()`` is tried in turn until one succeeds.  Use this only when
  neither of the faster forms is applicable.

If no processor can handle the input, ``get_processor()`` raises
:class:`~madam.core.UnsupportedFormatError`; it never returns ``None``.

Your code does not need to know whether the asset is a JPEG, a WebP, a PNG,
or an MP4.  The correct processor is selected automatically, and your
pipeline code stays format-agnostic:

.. code-block:: python

   for path in input_dir.glob('*'):
       with open(path, 'rb') as f:
           asset = madam.read(f)
       # Works for images, video, audio, SVG — no format checks needed.
       processor = madam.get_processor(asset)
       result = processor.convert(mime_type='image/webp')(asset)

   # Lookup by MIME type string — no asset required.
   processor = madam.get_processor('image/jpeg')


Essence and metadata separation
================================

Every asset carries two distinct pieces of data.

*Essence* is the raw media bytes — the compressed pixel data, the audio
samples, or the video stream — stored as a file-like object accessible via
``asset.essence``.

*Metadata* is structured information *about* the media: its dimensions,
colour space, duration, camera model, copyright, keywords, and so on.
Metadata is stored as a :class:`frozendict` and accessed via ``asset.metadata``
or as attributes (``asset.width``, ``asset.mime_type``).

Why keep them separate?
------------------------

**Reproducibility.**  When you strip metadata from a JPEG and re-embed it,
the resulting bytes change — which would invalidate ``content_id`` and break
caching.  By keeping metadata separate, MADAM ensures that the essence is a
stable, reproducible representation of the pixel data.

**Portability.**  Metadata schemas differ across formats.  An EXIF camera
model tag, an IPTC headline, and an XMP rights statement are three different
ways of attaching structured information to an image.  MADAM normalises them
into a common Python dictionary, so your code can access ``asset.metadata['exif']['camera.model']``
without knowing whether the source file was a JPEG, a TIFF, or a WebP.

**Safety.**  Embedded metadata can contain personal information (GPS
coordinates, device serial numbers).  Separating it makes it easy to strip or
redact sensitive fields before publishing an asset.

What gets extracted automatically
----------------------------------

:meth:`~madam.core.Madam.read` runs the essence through all registered
metadata processors in sequence.  For a JPEG, this means:

1. :class:`~madam.exif.ExifMetadataProcessor` extracts EXIF tags → ``asset.metadata['exif']``
2. :class:`~madam.iptc.IPTCMetadataProcessor` extracts IPTC fields → ``asset.metadata['iptc']``
3. :class:`~madam.xmp.XMPMetadataProcessor` extracts XMP properties → ``asset.metadata['xmp']``
4. A unified ``created_at`` timestamp (ISO 8601) is synthesised from EXIF,
   then XMP, then FFmpeg tags — whichever is present first.

The essence returned by ``read()`` has all embedded metadata *stripped*, so
the bytes represent purely the pixel data.  The metadata is stored separately
in the asset and can be re-embedded later by calling
``metadata_processor.combine(essence, metadata)``.


Format detection
================

When you call ``madam.read(f)``, MADAM has to decide which processor can
handle the file.  It does not rely on the file extension, which is unreliable
and absent for in-memory buffers.  Instead, it probes the raw bytes.

Each processor implements :meth:`~madam.core.Processor.can_read`, which
peeks at the byte stream and returns ``True`` if the processor recognises the
format.  :class:`~madam.core.Madam` tries each registered processor in
priority order until one accepts the file:

1. :class:`~madam.image.PillowProcessor` — handles BMP, GIF, JPEG, PNG, TIFF, WebP, AVIF, HEIC, raw formats.
2. :class:`~madam.vector.SVGProcessor` — handles SVG.
3. :class:`~madam.ffmpeg.FFmpegProcessor` — handles all audio and video formats supported by FFmpeg.

The probing approach means MADAM works correctly with:

* Files that have wrong or missing extensions.
* In-memory buffers returned by another library.
* Network streams where no filename is known.

If no processor accepts the file, :meth:`~madam.core.Madam.read` raises
:class:`~madam.core.UnsupportedFormatError`.


Processors and metadata processors
====================================

MADAM uses two distinct processor roles.

:class:`~madam.core.Processor`
    An essence processor reads and writes the full media stream.  It provides
    operators that transform the essence — resize, convert, trim, and so on.
    Essence processors are format-specific: :class:`~madam.image.PillowProcessor`
    handles raster images, :class:`~madam.ffmpeg.FFmpegProcessor` handles
    audio and video, :class:`~madam.vector.SVGProcessor` handles SVG.

:class:`~madam.core.MetadataProcessor`
    A metadata processor reads, strips, and re-embeds metadata tags without
    touching the essence pixels.  It operates on the file stream directly.
    Examples: :class:`~madam.exif.ExifMetadataProcessor`,
    :class:`~madam.iptc.IPTCMetadataProcessor`,
    :class:`~madam.xmp.XMPMetadataProcessor`.

This separation exists because metadata operations and essence operations have
very different characteristics.  Extracting EXIF tags from a JPEG is a
lightweight string-parsing operation; resizing a 50-megapixel image is a
compute-intensive pixel-manipulation operation.  Keeping them separate allows
MADAM to apply metadata processors on every read without incurring the cost
of a full decode-encode cycle.


Content addressing with ``content_id``
========================================

Every asset exposes a :attr:`~madam.core.Asset.content_id` attribute — a
SHA-256 hex digest of the raw essence bytes.

.. code-block:: python

   print(asset.content_id)
   # 'a3f5c8d2e1b4f7a6...'  (64 hex characters)

Content-addressed identities have two important properties.

**Deterministic.** Two assets with identical essence bytes always have the
same ``content_id``, regardless of when they were created or where they came
from.  This makes ``content_id`` a reliable deduplication key.

**Stable.** The ID is derived entirely from the bytes.  It does not change
when you rename a file or move it between machines.  It *does* change if the
bytes change — including after a lossy compression step — which makes it an
accurate fingerprint of the exact encoded data.

Practical uses:

* **Unique filenames.** ``f'{asset.content_id}.webp'`` is guaranteed to be
  unique for unique content.
* **Storage keys.** Pass ``content_id`` as the key to any storage backend.
* **Cache invalidation.** If the ID has not changed, the bytes have not
  changed — no reprocessing needed.
* **Deduplication.** Before storing, check whether ``content_id`` already
  exists in the store.


Pipeline design
================

The :class:`~madam.core.Pipeline` class lets you build reusable processing
workflows from operators.  Its design reflects two goals: simplicity for the
common case and flexibility for more complex scenarios.

Linear pipelines (the common case)
------------------------------------

:meth:`~madam.core.Pipeline.add` appends an operator to the pipeline.  When
:meth:`~madam.core.Pipeline.process` is called, each operator is applied in
order to each asset:

.. code-block:: python

   pipeline = Pipeline()
   pipeline.add(processor.resize(width=800, height=800, mode=ResizeMode.FIT))
   pipeline.add(processor.convert(mime_type='image/webp'))

Branching pipelines (fan-out)
------------------------------

:meth:`~madam.core.Pipeline.branch` takes several sub-pipelines and fans each
input asset out through all of them.  One input yields N outputs, where N is
the number of branches.  This is the natural way to produce multiple renditions
(thumbnail, preview, full-resolution) in a single pass:

.. code-block:: python

   pipeline = Pipeline()
   pipeline.branch(thumb_pipe, preview_pipe, original_pipe)
   # 1 source asset → 3 output assets

Conditional pipelines (gating)
--------------------------------

:meth:`~madam.core.Pipeline.when` applies an operator only when a predicate
holds.  This avoids the need for if/else checks scattered across pipeline code
and keeps the processing graph declarative:

.. code-block:: python

   pipeline.when(
       predicate=lambda a: a.width > 1920,
       then=processor.resize(width=1920, height=1080, mode=ResizeMode.FIT),
       # Assets at or below 1920 px pass through unchanged.
   )

Why a class instead of function composition?
---------------------------------------------

Python's ``functools.reduce`` or a simple list of functions can technically
achieve the same effect as a linear pipeline.  The ``Pipeline`` class exists
because it provides a named, inspectable, reusable object that is easy to
log, serialise, and pass around.  It also provides the ``branch`` and ``when``
primitives — which would be awkward to express as pure function composition —
in a consistent, testable API.


Storage model
=============

MADAM's storage backends all implement the :class:`~madam.core.AssetStorage`
abstract base class, which behaves like a dict keyed by arbitrary strings.
Each value is an ``(asset, tags)`` pair, where ``tags`` is a set of strings.

.. code-block:: python

   storage['hero'] = (asset, {'homepage', 'featured'})
   asset, tags = storage['hero']

The tag-based model
--------------------

Storing a free-form set of tags alongside each asset — rather than, say,
a rigid category column — gives you a lightweight but flexible classification
system.  An asset can belong to multiple logical groups simultaneously
(``'homepage'`` and ``'featured'`` and ``'2024'``), and you can filter by
any combination:

.. code-block:: python

   featured_homepage = list(storage.filter_by_tags({'homepage', 'featured'}))

Why three backends?
--------------------

:class:`~madam.core.InMemoryStorage`
    The simplest possible implementation: a Python dictionary.  Suitable for
    testing, for short-lived worker processes, and for any use-case where
    data loss on process exit is acceptable.  Thread-safe via an
    :class:`threading.RLock`.

:class:`~madam.core.ShelveStorage`
    Adds persistence via Python's :mod:`shelve` module with minimal setup.
    Good for single-process tools where a full database would be overkill.

:class:`~madam.core.FileSystemAssetStorage`
    Stores essence bytes and a JSON metadata sidecar per asset.  Writes are
    atomic (write to a temp file, then rename) so a crash mid-write cannot
    produce a corrupt entry.  Suitable for concurrent workers that share a
    file system.

All three share the same interface, so switching backends requires changing
one line.


.. _FFmpeg: https://ffmpeg.org/
.. _Pillow: https://python-pillow.org/
