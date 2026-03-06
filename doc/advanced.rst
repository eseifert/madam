Advanced use cases
##################

This chapter covers patterns that go beyond the basic read-transform-write
workflow: deferring I/O with :class:`~madam.core.LazyAsset`, distributing
work across processes with Celery, getting the most out of the
:class:`~madam.core.Pipeline` execution model, and integrating adaptive
streaming output.

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


Advanced Pipeline patterns
===========================

Fan-out with branch()
---------------------

:meth:`~madam.core.Pipeline.branch` sends each source asset through multiple
sub-pipelines in sequence and yields all results.  Use it to produce several
renditions from one pass:

.. code-block:: python

   from madam import Madam
   from madam.core import Pipeline
   from madam.image import ResizeMode

   madam = Madam()
   proc = madam.get_processor('image/jpeg')

   thumb_pipe = Pipeline()
   thumb_pipe.add(proc.resize(width=150, height=150, mode=ResizeMode.FILL))
   thumb_pipe.add(proc.convert(mime_type='image/webp'))

   preview_pipe = Pipeline()
   preview_pipe.add(proc.resize(width=1200, height=900, mode=ResizeMode.FIT))
   preview_pipe.add(proc.convert(mime_type='image/jpeg'))

   main_pipe = Pipeline()
   main_pipe.branch(thumb_pipe, preview_pipe)

   with open('photo.jpg', 'rb') as f:
       source = madam.read(f)

   # Yields: thumbnail, preview (2 results per source asset)
   thumb, preview = main_pipe.process(source)

Conditional logic with when()
------------------------------

:meth:`~madam.core.Pipeline.when` applies an operator only when a predicate
is true.  An optional ``else_`` operator is applied when the predicate is
false:

.. code-block:: python

   pipeline = Pipeline()

   # Convert oversized images to WebP; keep small images as-is
   pipeline.when(
       predicate=lambda a: a.width > 1920 or a.height > 1080,
       then=proc.resize(width=1920, height=1080, mode=ResizeMode.FIT),
   )

   # Different output format for PNG vs everything else
   pipeline.when(
       predicate=lambda a: str(a.mime_type) == 'image/png',
       then=proc.convert(mime_type='image/png'),
       else_=proc.convert(mime_type='image/jpeg'),
   )

Forcing an intermediate encode with flush()
--------------------------------------------

MADAM groups consecutive operators from the same processor into a *run* and
applies them without intermediate encode/decode cycles.  For lossy formats
this avoids quality loss, but sometimes you need an explicit encode at a
specific point — for example, to apply a sharpening filter *after* a lossy
resize has already committed its artefacts:

.. code-block:: python

   pipeline = Pipeline()
   pipeline.add(proc.resize(width=1200, height=900))
   pipeline.add(Pipeline.flush())       # encode to JPEG here
   pipeline.add(proc.sharpen(radius=1, percent=80))   # new encode cycle

Without the flush, resize and sharpen would share a single Pillow operation
and the sharpen kernel would run on lossless in-memory data.  With the flush,
sharpen sees the already-compressed pixel values — matching what a user would
see after opening and re-saving the file.

Processing multiple assets at once
------------------------------------

:meth:`~madam.core.Pipeline.process` accepts any number of source assets and
yields results in the same order:

.. code-block:: python

   sources = [madam.read(open(p, 'rb')) for p in image_paths]
   for result in pipeline.process(*sources):
       storage[result.content_id] = (result, set())

Deferred execution and the processing context
----------------------------------------------

Under the hood, consecutive operators from the same processor share a live
*processing context* rather than re-encoding between steps:

- **Images** (:class:`~madam.image.PillowContext`) — holds a ``PIL.Image``
  object; encodes once at the end of the run.
- **Video/audio** (:class:`~madam.ffmpeg.FFmpegContext`) — accumulates an
  ``FFmpegFilterGraph`` and runs a single ``ffmpeg`` subprocess.
- **SVG** (:class:`~madam.vector.SVGContext`) — holds a live ``ElementTree``;
  serialises once per run.

This means three consecutive resize operations on an image result in **one
Pillow encode**, not three, eliminating cumulative JPEG artefacts.

The pipeline automatically inserts a materialisation step whenever the
processor changes.  Use :meth:`~madam.core.Pipeline.flush` to force an
early materialisation within a single-processor run.


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


Fast tag-based filtering with InMemoryStorage
==============================================

:class:`~madam.core.InMemoryStorage` maintains an inverted index over all
scalar metadata values.  This makes :meth:`~madam.core.AssetStorage.filter`
calls O(k) where *k* is the number of matching assets rather than O(n) over
all stored assets:

.. code-block:: python

   from madam.core import InMemoryStorage

   storage = InMemoryStorage()
   storage['hero']   = (hero_asset,   {'homepage', 'featured'})
   storage['banner'] = (banner_asset, {'homepage'})
   storage['thumb']  = (thumb_asset,  {'thumbnail'})

   # O(k) index lookup — does not scan all assets
   homepage_assets = list(storage.filter(tags={'homepage'}))

   # Filter by metadata value
   jpegs = list(storage.filter(mime_type='image/jpeg'))

   # Filter by multiple tags at once (subset test)
   featured_homepage = list(storage.filter_by_tags({'featured', 'homepage'}))

Use :class:`~madam.core.ShelveStorage` or
:class:`~madam.core.FileSystemAssetStorage` for persistent storage across
process restarts:

.. code-block:: python

   from madam.core import FileSystemAssetStorage

   # Atomic writes: safe for multiple workers writing concurrently
   storage = FileSystemAssetStorage('/data/processed')
   storage['my-key'] = (asset, {'processed', 'webp'})


Adaptive streaming output (HLS and MPEG-DASH)
===============================================

:class:`~madam.ffmpeg.FFmpegProcessor` can produce HTTP Live Streaming (HLS)
and MPEG-DASH manifests with their associated segments.  Both methods write
output through a :class:`~madam.streaming.MultiFileOutput` backend so the
destination (directory, zip archive, object storage …) is decoupled from the
encoding step.

Write to a directory
--------------------

.. code-block:: python

   from madam import Madam
   from madam.streaming import DirectoryOutput

   madam = Madam()
   with open('video.mp4', 'rb') as f:
       asset = madam.read(f)

   proc = madam.get_processor(asset)
   output = DirectoryOutput('/var/www/hls/video1')
   proc.to_hls(asset, output=output, segment_duration=6)
   # Creates: /var/www/hls/video1/index.m3u8
   #          /var/www/hls/video1/segment_000.ts
   #          /var/www/hls/video1/segment_001.ts  …

Write to a zip archive (in-memory)
-----------------------------------

Useful for testing, for download APIs that stream the archive, or for
uploading all segments to object storage as a batch:

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

Write to object storage
------------------------

Implement :class:`~madam.streaming.MultiFileOutput` to write directly to any
backend:

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

   from madam.streaming import DirectoryOutput

   proc.to_dash(asset, output=DirectoryOutput('/var/www/dash/video1'),
                segment_duration=4)
   # Creates: /var/www/dash/video1/manifest.mpd
   #          /var/www/dash/video1/init-stream0.mp4
   #          /var/www/dash/video1/chunk-stream0-00001.m4s  …

Custom codec options
--------------------

Both methods accept ``video`` and ``audio`` keyword arguments that mirror the
``convert()`` operator options:

.. code-block:: python

   from madam.video import VideoCodec
   from madam.audio import AudioCodec

   proc.to_hls(
       asset,
       output=DirectoryOutput('/var/www/hls/video1'),
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


Format-agnostic batch processing
==================================

Because :meth:`~madam.core.Madam.get_processor` accepts an asset, a MIME
type string, or a raw file, you can write a single processing loop that works
across images, audio, and video without any format checks in application code:

.. code-block:: python

   import pathlib
   from madam import Madam
   from madam.core import UnsupportedFormatError, OperatorError

   madam = Madam({'image/jpeg': {'quality': 80}, 'image/webp': {'quality': 80}})

   def batch_convert(input_dir: str, output_dir: str, target_mime: str) -> None:
       out = pathlib.Path(output_dir)
       out.mkdir(parents=True, exist_ok=True)

       for path in pathlib.Path(input_dir).iterdir():
           if not path.is_file():
               continue
           try:
               with open(path, 'rb') as f:
                   asset = madam.read(f)
               processor = madam.get_processor(asset)
               result = processor.convert(mime_type=target_mime)(asset)
           except UnsupportedFormatError:
               print(f'Skipping unsupported file: {path.name}')
               continue
           except OperatorError as exc:
               print(f'Failed to convert {path.name}: {exc}')
               continue

           out_path = out / path.with_suffix('').name
           with open(out_path, 'wb') as f:
               madam.write(result, f)
           print(f'Converted {path.name} → {out_path.name}')

   batch_convert('/data/raw', '/data/converted', 'image/webp')
