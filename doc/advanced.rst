Advanced use cases
##################

This chapter covers patterns that go beyond the basic read-transform-write
workflow documented in :doc:`howto`.  Each section focuses on something the
how-to guides either don't cover at all or only mention in passing:
deferring I/O with :class:`~madam.core.LazyAsset`, distributing work across
processes with Celery, content-addressed deduplication, custom streaming
backends, real-time progress reporting, fine-tuning encoder settings, and
writing your own :class:`~madam.core.Processor`.

.. contents::
   :local:
   :depth: 2


Deferred loading with LazyAsset
================================

Problem
-------

A standard :class:`~madam.core.Asset` holds the raw essence bytes in memory.
For a 500 MB video file that means a 500 MB payload every time the asset
passes through a message broker (Celery, RQ, …), gets pickled into a cache,
or is stored in a database column.  The payload usually exceeds broker limits
and is slow regardless.

Solution
--------

:class:`~madam.core.LazyAsset` stores only a *URI string* and the metadata
dict.  The raw bytes are fetched on demand the first time ``.essence`` is
accessed by calling a *loader* function you provide.

.. code-block:: python

   from madam.core import LazyAsset

   def s3_loader(uri: str):
       """Return a readable BytesIO stream for an s3:// URI."""
       import io
       import boto3
       bucket, key = uri[5:].split('/', 1)  # strip 's3://'
       buf = io.BytesIO()
       boto3.client('s3').download_fileobj(bucket, key, buf)
       buf.seek(0)
       return buf

   asset = LazyAsset(
       uri='s3://my-bucket/uploads/video.mp4',
       loader=s3_loader,
       mime_type='video/mp4',
       duration=120.0,
       width=1920,
       height=1080,
   )

The loader is **never serialised**.  Calling ``pickle.dumps(asset)`` produces
a small payload that contains only the URI and the metadata mapping:

.. code-block:: python

   import pickle

   data = pickle.dumps(asset)          # a few hundred bytes, not 500 MB
   restored = pickle.loads(data)
   print(restored.uri)                 # 's3://my-bucket/uploads/video.mp4'
   print(restored.mime_type)           # 'video/mp4'

After unpickling the *loader* is ``None``.  Re-attach a loader before
accessing the essence:

.. code-block:: python

   restored._loader = s3_loader        # re-attach in the worker process
   frame = restored.essence.read(1024) # fetches from S3 now

A LazyAsset is a drop-in for a regular Asset: processors, operators, and
pipelines accept it wherever they accept Asset:

.. code-block:: python

   from madam import Madam

   madam = Madam()
   processor = madam.get_processor(asset)   # O(1) — uses asset.mime_type
   thumbnail = processor.resize(width=320, height=240)(asset)

.. note::

   Because every call to ``.essence`` invokes the loader, cache the result
   locally if you need to read the stream more than once:

   .. code-block:: python

      import io
      data = io.BytesIO(asset.essence.read())   # one round-trip
      # use data as many times as you like


Distributed processing with Celery
====================================

The combination of :class:`~madam.core.LazyAsset`'s small pickle payload and
MADAM's pure-function operators makes Celery integration straightforward.

Basic task
----------

.. code-block:: python

   # tasks.py
   import io
   import boto3
   from celery import Celery
   from madam import Madam
   from madam.core import LazyAsset, OperatorError

   app = Celery('tasks', broker='redis://localhost:6379/0')
   madam = Madam({'image/jpeg': {'quality': 80}})

   def s3_loader(uri: str):
       bucket, key = uri[5:].split('/', 1)
       buf = io.BytesIO()
       boto3.client('s3').download_fileobj(bucket, key, buf)
       buf.seek(0)
       return buf

   def s3_upload(asset, bucket: str, key: str) -> str:
       boto3.client('s3').upload_fileobj(asset.essence, bucket, key)
       return f's3://{bucket}/{key}'

   @app.task(bind=True, max_retries=3)
   def resize_and_store(self, uri: str, width: int, height: int):
       # Re-attach loader in the worker (loader is never pickled)
       asset = LazyAsset(uri=uri, loader=s3_loader, mime_type='image/jpeg')

       try:
           processor = madam.get_processor(asset)
           result = processor.resize(width=width, height=height)(asset)
           out_key = f'thumbnails/{width}x{height}/{uri.split("/")[-1]}'
           return s3_upload(result, 'my-bucket', out_key)
       except OperatorError as exc:
           raise self.retry(exc=exc, countdown=2 ** self.request.retries)

Calling the task:

.. code-block:: python

   # In your web handler or upload handler:
   resize_and_store.delay('s3://my-bucket/uploads/photo.jpg', 320, 240)

Fan-out: generating multiple renditions in parallel
----------------------------------------------------

Submit one task per rendition instead of one large sequential task.  All
workers read the same source lazily from S3, so there is no wasted bandwidth
for renditions that fail:

.. code-block:: python

   from celery import group

   RENDITIONS = [
       {'width': 1920, 'height': 1080, 'suffix': '1080p'},
       {'width': 1280, 'height': 720,  'suffix': '720p'},
       {'width': 640,  'height': 360,  'suffix': '360p'},
       {'width': 320,  'height': 240,  'suffix': 'thumb'},
   ]

   def enqueue_renditions(source_uri: str):
       job = group(
           resize_and_store.s(source_uri, r['width'], r['height'])
           for r in RENDITIONS
       )
       return job.apply_async()

Chaining tasks with a Pipeline
-------------------------------

For multi-step processing, build the pipeline once and share it across tasks:

.. code-block:: python

   from madam.core import Pipeline
   from madam.image import ResizeMode

   # Build once at module level — operators are plain callables, safe to share
   _pipeline = Pipeline()
   _pipeline.add(madam.get_processor('image/jpeg').resize(
       width=1280, height=720, mode=ResizeMode.FILL))
   _pipeline.add(madam.get_processor('image/jpeg').convert(mime_type='image/webp'))

   @app.task
   def transcode_to_webp(uri: str):
       asset = LazyAsset(uri=uri, loader=s3_loader, mime_type='image/jpeg')
       results = list(_pipeline.process(asset))
       return s3_upload(results[0], 'my-bucket', f'webp/{uri.split("/")[-1]}')

.. tip::

   Use ``TransientOperatorError`` to drive Celery retries and
   ``PermanentOperatorError`` for dead-letter routing:

   .. code-block:: python

      from madam.core import (
          TransientOperatorError,
          PermanentOperatorError,
          UnsupportedFormatError,
      )

      @app.task(bind=True, max_retries=5)
      def safe_transcode(self, uri: str):
          asset = LazyAsset(uri=uri, loader=s3_loader, mime_type='video/mp4')
          try:
              processor = madam.get_processor(asset)
              result = processor.convert(mime_type='video/webm')(asset)
              return s3_upload(result, 'my-bucket', uri.split('/')[-1])
          except UnsupportedFormatError:
              return None           # skip silently
          except PermanentOperatorError:
              send_to_dead_letter(uri)
              return None
          except TransientOperatorError as exc:
              raise self.retry(exc=exc, countdown=2 ** self.request.retries)


Content-addressed storage and deduplication
============================================

Every :class:`~madam.core.Asset` exposes a :attr:`~madam.core.Asset.content_id`
property that is the hex-encoded SHA-256 digest of the raw essence bytes.  Use
it as a storage key to deduplicate identical files automatically:

.. code-block:: python

   from madam.core import FileSystemAssetStorage

   storage = FileSystemAssetStorage('/data/assets')

   for path in incoming_files:
       with open(path, 'rb') as f:
           asset = madam.read(f)
       # Identical content → same key → no duplicate entry
       storage[asset.content_id] = (asset, {'raw'})

Retrieve by content ID or check existence cheaply:

.. code-block:: python

   cid = '3a7bd3e2...'
   if cid in storage:
       asset, tags = storage[cid]

For :class:`~madam.core.LazyAsset`, ``content_id`` is computed on first
access and cached; subsequent calls are O(1):

.. code-block:: python

   lazy = LazyAsset(uri='s3://bucket/image.jpg', loader=s3_loader,
                    mime_type='image/jpeg')
   cid = lazy.content_id   # fetches once, hashes, caches
   cid2 = lazy.content_id  # returns cached value — no fetch


Custom streaming output backends
==================================

The how-to guide shows how to write HLS/DASH segments to a local directory
with :class:`~madam.streaming.DirectoryOutput`.  This section covers the two
other built-in backends and how to implement your own.

Writing to a zip archive (in-memory)
--------------------------------------

Useful for testing, for download APIs that stream the archive, or for
uploading all segments to object storage as a single atomic batch:

.. code-block:: python

   import io
   import zipfile
   from madam.streaming import ZipOutput

   buf = io.BytesIO()
   with ZipOutput(buf) as output:
       proc.to_hls(asset, output=output, segment_duration=6)

   # buf now holds a zip with the manifest and all segments
   buf.seek(0)
   with zipfile.ZipFile(buf) as zf:
       print(zf.namelist())   # ['index.m3u8', 'segment_000.ts', …]

Writing to object storage
--------------------------

Implement :class:`~madam.streaming.MultiFileOutput` to write directly to any
backend.  The interface requires only a single ``write`` method:

.. code-block:: python

   import boto3
   from madam.streaming import MultiFileOutput

   class S3Output(MultiFileOutput):
       def __init__(self, bucket: str, prefix: str):
           self._bucket = bucket
           self._prefix = prefix
           self._client = boto3.client('s3')

       def write(self, relative_path: str, data: bytes) -> None:
           key = f'{self._prefix}/{relative_path}'
           self._client.put_object(Bucket=self._bucket, Key=key, Body=data)

   output = S3Output('my-bucket', 'hls/video1')
   proc.to_hls(asset, output=output, segment_duration=4)

MPEG-DASH works the same way — replace ``to_hls`` with ``to_dash``:

.. code-block:: python

   proc.to_dash(asset, output=S3Output('my-bucket', 'dash/video1'),
                segment_duration=4)

Both methods accept optional ``video`` and ``audio`` dicts that mirror the
``convert()`` operator options:

.. code-block:: python

   from madam.video import VideoCodec
   from madam.audio import AudioCodec

   proc.to_hls(
       asset,
       output=output,
       segment_duration=6,
       video={'codec': VideoCodec.H264, 'bitrate': 2000},
       audio={'codec': AudioCodec.AAC,  'bitrate': 128},
   )


Real-time transcoding progress
================================

Pass a ``progress_callback`` to :meth:`~madam.ffmpeg.FFmpegProcessor.convert`
to receive periodic progress updates during long transcoding jobs.  The
callback receives a ``dict`` with keys like ``frame``, ``fps``,
``out_time``, and ``bitrate``:

.. code-block:: python

   from madam import Madam

   madam = Madam()
   with open('video.mp4', 'rb') as f:
       asset = madam.read(f)

   proc = madam.get_processor(asset)

   def on_progress(info: dict) -> None:
       frame = info.get('frame', '?')
       out_time = info.get('out_time', '?')
       print(f'frame={frame}  time={out_time}')

   result = proc.convert(
       mime_type='video/webm',
       progress_callback=on_progress,
   )(asset)

When no ``progress_callback`` is supplied, MADAM uses ``subprocess.run``
(simpler, lower overhead).  When a callback is supplied it switches to
``subprocess.Popen`` and reads the progress stream line by line.

Celery + progress with a result backend
-----------------------------------------

Combine the callback with Celery's ``update_state`` to expose live progress
through the result backend:

.. code-block:: python

   @app.task(bind=True)
   def transcode_video(self, uri: str, target_mime: str):
       asset = LazyAsset(uri=uri, loader=s3_loader, mime_type='video/mp4')
       proc = madam.get_processor(asset)

       def on_progress(info: dict) -> None:
           self.update_state(
               state='PROGRESS',
               meta={'out_time': info.get('out_time', ''), 'frame': info.get('frame', '')},
           )

       result = proc.convert(
           mime_type=target_mime,
           progress_callback=on_progress,
       )(asset)
       return s3_upload(result, 'my-bucket', uri.split('/')[-1])


Fine-tuning encoder settings
==============================

Pass a configuration mapping to :class:`~madam.core.Madam` to control
encoder defaults.  Keys are MIME type strings (or short names); values are
dicts of options:

.. code-block:: python

   from madam import Madam

   madam = Madam({
       'image/jpeg': {'quality': 85, 'progressive': True},
       'image/png':  {'optimize': True, 'zopfli': True},
       'image/webp': {'quality': 80, 'method': 6},
       'image/avif': {'quality': 70, 'speed': 4},
       'image/gif':  {'optimize': True},
       'image/tiff': {'compression': 'tiff_lzw'},
       'ffmpeg':     {'threads': 8},
       'video':      {'keyframe_interval': 60},
   })

Image options
--------------

.. list-table::
   :header-rows: 1
   :widths: 20 35 45

   * - MIME type
     - Key
     - Values / meaning
   * - ``image/jpeg``
     - ``quality``
     - Integer 1–95 (Pillow default 75)
   * - ``image/jpeg``
     - ``progressive``
     - ``True`` for progressive JPEG encoding
   * - ``image/png``
     - ``optimize``
     - ``True`` to enable Pillow's optimizer pass
   * - ``image/png``
     - ``zopfli`` / ``zopfli_strategies``
     - Enable Zopfli compression (requires ``madam[optimize]``)
   * - ``image/webp``
     - ``quality``
     - Integer 1–100
   * - ``image/webp``
     - ``method``
     - 0 (fastest) – 6 (best compression)
   * - ``image/avif``
     - ``quality``
     - Integer 0–100 (higher = better quality, larger file)
   * - ``image/avif``
     - ``speed``
     - 0 (slowest/best) – 10 (fastest/worst)
   * - ``image/tiff``
     - ``compression``
     - ``'tiff_lzw'``, ``'tiff_deflate'``, ``'jpeg'``, ``'raw'``
   * - ``image/gif``
     - ``optimize``
     - ``True`` to merge duplicate palette entries

Video / FFmpeg options
-----------------------

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Key
     - Effect
   * - ``'ffmpeg': {'threads': N}``
     - Number of FFmpeg threads (default: CPU count)
   * - ``'video': {'keyframe_interval': N}``
     - Keyframe interval in frames (default 100)
   * - ``'video/quicktime': {'faststart': False}``
     - Disable ``-movflags +faststart`` (enabled by default for MP4/QuickTime)

Per-codec CRF overrides are set with a ``'codec/<libname>'`` key:

.. code-block:: python

   madam = Madam({
       'codec/libx264':    {'crf': 23},   # H.264 (default 23)
       'codec/libvpx-vp9': {'crf': 33},   # VP9
       'codec/libx265':    {'crf': 28},   # H.265
   })

.. note::

   The ``Madam()`` constructor does not validate configuration keys.
   Unrecognised keys under image MIME types emit a :class:`UserWarning`;
   FFmpeg keys are silently ignored.


Writing a custom Processor
============================

To add support for a new file format, subclass :class:`~madam.core.Processor`
and override the two abstract methods plus the ``supported_mime_types``
property.  Register the new processor with :class:`~madam.core.Madam` so that
:meth:`~madam.core.Madam.get_processor` finds it automatically.

Minimal example
----------------

.. code-block:: python

   import io
   from madam.core import Asset, Processor, UnsupportedFormatError, operator

   class NetpbmProcessor(Processor):
       """Read/write Netpbm PBM/PGM/PPM files."""

       MAGIC = {b'P1': 'image/x-portable-bitmap',
                b'P2': 'image/x-portable-graymap',
                b'P3': 'image/x-portable-pixmap',
                b'P4': 'image/x-portable-bitmap',
                b'P5': 'image/x-portable-graymap',
                b'P6': 'image/x-portable-pixmap'}

       @property
       def supported_mime_types(self) -> frozenset:
           return frozenset(self.MAGIC.values())

       def can_read(self, file: io.IOBase) -> bool:
           magic = file.read(2)
           file.seek(0)
           return magic in self.MAGIC

       def read(self, file: io.IOBase) -> Asset:
           data = file.read()
           magic = data[:2]
           if magic not in self.MAGIC:
               raise UnsupportedFormatError('Not a Netpbm file')
           mime_type = self.MAGIC[magic]
           # Parse dimensions from the header (simplified)
           lines = data.split(b'\n')
           w, h = map(int, lines[1].split())
           return Asset._from_bytes(data, mime_type=mime_type, width=w, height=h)

Adding operators with ``@operator``
-------------------------------------

Use the :func:`~madam.core.operator` decorator to create lazy, reusable
operators.  Calling the method returns a configured callable
(``Asset → Asset``), not the result directly:

.. code-block:: python

   from madam.core import operator

   class NetpbmProcessor(Processor):
       ...

       @operator
       def invert(self, asset: Asset) -> Asset:
           """Return a new asset with all pixel values inverted."""
           import PIL.Image
           img = PIL.Image.open(asset.essence).convert('RGB')
           inverted = PIL.Image.eval(img, lambda v: 255 - v)
           buf = io.BytesIO()
           inverted.save(buf, format='PPM')
           buf.seek(0)
           return Asset(essence=buf, mime_type=asset.mime_type,
                        width=asset.width, height=asset.height)

   proc = NetpbmProcessor()
   invert_op = proc.invert()          # returns a callable (not the result)
   result = invert_op(ppm_asset)      # apply to an asset

Operators returned by ``@operator`` can be stored in a
:class:`~madam.core.Pipeline` and applied in sequence:

.. code-block:: python

   from madam.core import Pipeline

   pipeline = Pipeline()
   pipeline.add(proc.invert())
   pipeline.add(proc.invert())   # double invert → original
   (result,) = pipeline.process(ppm_asset)

Registering with Madam
------------------------

.. code-block:: python

   from madam import Madam

   madam = Madam()
   madam.processors.append(NetpbmProcessor())
   # madam.get_processor('image/x-portable-pixmap') now returns your processor

.. note::

   Madam builds its internal MIME-type index at ``__init__`` time.  If you
   register a processor after construction, call
   ``madam._rebuild_mime_index()`` (or simply construct a fresh ``Madam()``
   with the processor already appended to the processor list) to keep the
   O(1) lookup accurate.
