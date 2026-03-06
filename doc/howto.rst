How-to guides
#############

These guides solve specific problems.  They assume you already have a
:class:`~madam.core.Madam` instance and at least one :class:`~madam.core.Asset`
to work with.  For a step-by-step introduction see :doc:`tutorial`.

.. tip::

   Always obtain a processor through :meth:`~madam.core.Madam.get_processor`
   rather than importing and instantiating a processor class directly.
   ``get_processor`` returns the processor that is already configured with your
   ``Madam`` instance's settings (quality, codec options, thread count, etc.),
   so format-specific defaults are applied automatically and your code stays
   format-agnostic:

   .. code-block:: python

      # Preferred — works for images, video, audio, SVG:
      processor = madam.get_processor(asset)

      # Avoid — bypasses the Madam config and couples code to a specific format:
      from madam.image import PillowProcessor
      processor = PillowProcessor()

.. contents::
   :local:
   :depth: 2


Images
======

How to resize an image
-----------------------

Use :meth:`~madam.image.PillowProcessor.resize` with one of the three
:class:`~madam.image.ResizeMode` values:

.. code-block:: python

   from madam import Madam
   from madam.image import ResizeMode

   madam = Madam()
   with open('photo.jpg', 'rb') as f:
       asset = madam.read(f)

   processor = madam.get_processor(asset)

   # EXACT: scale to exactly 800×600, ignoring the aspect ratio.
   exact = processor.resize(width=800, height=600, mode=ResizeMode.EXACT)

   # FIT: scale down to fit entirely inside 800×600 (letterbox).
   fit = processor.resize(width=800, height=600, mode=ResizeMode.FIT)

   # FILL: scale and crop to cover exactly 800×600.
   fill = processor.resize(width=800, height=600, mode=ResizeMode.FILL)

   result = fill(asset)

Use ``gravity`` in ``FILL`` mode to control which part of the image is
preserved (default: ``'center'``):

.. code-block:: python

   # Keep the top of the image when cropping for a 4:3 thumbnail.
   cover_top = processor.resize(
       width=400, height=300,
       mode=ResizeMode.FILL,
       gravity='north',
   )
   result = cover_top(asset)

Valid gravity values: ``'north_west'``, ``'north'``, ``'north_east'``,
``'west'``, ``'center'``, ``'east'``, ``'south_west'``, ``'south'``,
``'south_east'``.


How to crop an image
---------------------

Use :meth:`~madam.image.PillowProcessor.crop` with explicit pixel coordinates
or with a gravity anchor:

.. code-block:: python

   # Crop a 640×480 region starting at the top-left corner.
   exact_crop = processor.crop(width=640, height=480, x=0, y=0)

   # Crop 640×480 from the centre — no need to compute x and y manually.
   center_crop = processor.crop(width=640, height=480, gravity='center')

   result = center_crop(asset)

For content-aware cropping centered on a focal point (e.g. a face), use
:meth:`~madam.image.PillowProcessor.crop_to_focal_point` with normalised
``[0.0, 1.0]`` coordinates:

.. code-block:: python

   # Crop to 640×480, keeping the subject at 60 % across and 30 % down.
   crop_face = processor.crop_to_focal_point(
       width=640, height=480,
       focal_x=0.6, focal_y=0.3,
   )
   result = crop_face(portrait)


How to convert an image to a different format
----------------------------------------------

.. code-block:: python

   # JPEG → WebP
   to_webp = processor.convert(mime_type='image/webp')
   webp_asset = to_webp(asset)

   with open('output.webp', 'wb') as f:
       madam.write(webp_asset, f)

   # JPEG → PNG with explicit colour space conversion
   to_grayscale_png = processor.convert(
       mime_type='image/png',
       color_space='LUMA',
       depth=8,
   )
   grey = to_grayscale_png(asset)

Format-specific quality settings are controlled via the :class:`~madam.core.Madam`
configuration (see :doc:`configuration`).


How to apply tonal adjustments
--------------------------------

Use the adjustment operators to modify brightness, contrast, saturation, or
sharpness.  A factor of ``1.0`` leaves the image unchanged:

.. code-block:: python

   processor = madam.get_processor(asset)

   brighter    = processor.adjust_brightness(factor=1.3)   # 30 % brighter
   more_pop    = processor.adjust_contrast(factor=1.2)     # 20 % more contrast
   desaturated = processor.adjust_saturation(factor=0.4)   # 60 % less colour
   sharper     = processor.adjust_sharpness(factor=1.8)    # 80 % sharper

   result = sharper(more_pop(brighter(asset)))


How to apply artistic effects
-------------------------------

.. code-block:: python

   # Classic sepia tone.
   sepia = processor.sepia()(asset)

   # Warm orange tint at 25 % opacity.
   tinted = processor.tint(color=(255, 180, 80), opacity=0.25)(asset)

   # Radial vignette that darkens the corners by 40 %.
   vignetted = processor.vignette(strength=0.4)(asset)


How to blur or sharpen an image
---------------------------------

.. code-block:: python

   # Gaussian blur with a 4-pixel radius (useful for privacy redaction).
   blurred = processor.blur(radius=4)(asset)

   # Unsharp mask: radius, sharpening strength (%), minimum pixel difference.
   sharpened = processor.sharpen(radius=2, percent=150, threshold=3)(asset)


How to add padding (letterbox / border)
-----------------------------------------

Use :meth:`~madam.image.PillowProcessor.pad` to place an image on a larger
canvas, for example to add a uniform border:

.. code-block:: python

   # 20 px white border on all sides.
   add_border = processor.pad(
       width=asset.width + 40,
       height=asset.height + 40,
       color=(255, 255, 255),
       gravity='center',
   )
   padded = add_border(asset)

   # Square thumbnail with centred content and a transparent background.
   squarify = processor.pad(
       width=300, height=300,
       color=(0, 0, 0, 0),   # RGBA transparent
       gravity='center',
   )
   square = squarify(small_asset)


How to composite a watermark
------------------------------

Use :meth:`~madam.image.PillowProcessor.composite` to place one image on top
of another:

.. code-block:: python

   with open('watermark.png', 'rb') as f:
       watermark = madam.read(f)

   # Bottom-right corner at 60 % opacity.
   add_watermark = processor.composite(
       overlay_asset=watermark,
       gravity='south_east',
       opacity=0.6,
   )
   result = add_watermark(asset)

Use explicit pixel offsets to position the overlay exactly:

.. code-block:: python

   add_watermark = processor.composite(
       overlay_asset=watermark,
       x=20, y=20,   # 20 px from the top-left corner
   )


How to flatten transparency onto a background
-----------------------------------------------

PNG and WebP images may contain an alpha channel.  Use
:meth:`~madam.image.PillowProcessor.fill_background` to composite transparent
pixels over a solid colour before writing to a format that does not support
transparency (e.g. JPEG):

.. code-block:: python

   flatten = processor.fill_background(color=(255, 255, 255))  # white
   opaque = flatten(transparent_asset)

   to_jpeg = processor.convert(mime_type='image/jpeg')
   jpeg = to_jpeg(opaque)


How to round image corners
----------------------------

:meth:`~madam.image.PillowProcessor.round_corners` cuts the corners using a
smooth circular mask.  The output is always an RGBA PNG:

.. code-block:: python

   rounded = processor.round_corners(radius=24)(asset)

   with open('rounded.png', 'wb') as f:
       madam.write(rounded, f)


How to apply an alpha mask
----------------------------

Replace an image's alpha channel with a greyscale mask.  White (255) = fully
opaque; black (0) = fully transparent.  Output is always RGBA PNG:

.. code-block:: python

   with open('mask.png', 'rb') as f:
       mask = madam.read(f)

   masked = processor.apply_mask(mask_asset=mask)(asset)


How to rotate or flip an image
--------------------------------

.. code-block:: python

   from madam.image import FlipOrientation

   # Rotate 90 ° counter-clockwise (canvas expands to fit).
   rotated = processor.rotate(angle=90, expand=True)(asset)

   # Mirror horizontally.
   mirror_h = processor.flip(orientation=FlipOrientation.HORIZONTAL)(asset)

   # Auto-rotate based on the EXIF orientation tag.
   oriented = processor.auto_orient()(asset)


How to work with animated images (GIF, WebP)
---------------------------------------------

Read an animated GIF and inspect its frame count:

.. code-block:: python

   with open('animation.gif', 'rb') as f:
       animated = madam.read(f)

   print(animated.frame_count)   # e.g. 24

   processor = madam.get_processor(animated)

Extract a single frame as a static image:

.. code-block:: python

   # Zero-based index.
   get_frame = processor.extract_frame(frame=0)
   first_frame = get_frame(animated)


How to create an animated GIF or WebP
--------------------------------------

:func:`~madam.image.combine` assembles a list of image assets into a single
animated GIF or WebP.  It is a module-level function — no ``Madam`` instance
or processor is needed:

.. code-block:: python

   from madam.image import combine

   gif = combine([frame1, frame2, frame3], 'image/gif', duration=200, loop=0)
   webp = combine([frame1, frame2], 'image/webp', duration=100)

``duration`` is the per-frame delay in milliseconds (default ``100``).
``loop=0`` means infinite looping (default).

Supported output formats are ``'image/gif'`` and ``'image/webp'``.
:class:`~madam.core.UnsupportedFormatError` is raised for any other MIME type.

.. versionadded:: 1.0


How to render text as an image
--------------------------------

:func:`~madam.image.render_text` creates a new RGBA PNG asset sized to fit
the text.  It is a module-level function, not an operator:

.. code-block:: python

   from madam.image import render_text

   label = render_text(
       'Sale — 50 % off',
       font_path='/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
       font_size=36,
       color=(255, 255, 255),
       background=(200, 0, 0, 220),   # semi-transparent red
       padding=12,
   )

   # Composite it onto a product image.
   processor = madam.get_processor(product_asset)
   add_label = processor.composite(overlay_asset=label, gravity='south_west')
   result = add_label(product_asset)


How to optimise image quality automatically
--------------------------------------------

:meth:`~madam.image.PillowProcessor.optimize_quality` binary-searches for the
lowest quality setting that still passes a perceptual quality threshold
(measured with SSIMULACRA2).  Install the optional dependency first::

   pip install "madam[analysis]"

.. code-block:: python

   # Smallest WebP whose SSIMULACRA2 score is ≥ 85.
   optimize = processor.optimize_quality(
       min_ssim_score=85.0,
       mime_type='image/webp',
   )
   small_webp = optimize(asset)

   print(small_webp.mime_type)   # 'image/webp'

Supported output formats: JPEG, WebP, AVIF.  Typical thresholds: ≥ 90 nearly
imperceptible, ≥ 80 good, ≥ 70 acceptable.


How to extract the dominant colours from an image
--------------------------------------------------

:func:`~madam.image.extract_palette` returns the *count* most frequent colours
as ``(r, g, b)`` tuples, sorted by pixel frequency:

.. code-block:: python

   from madam.image import extract_palette

   colors = extract_palette(asset, count=5)
   # e.g. [(240, 220, 180), (50, 80, 120), …]  — most frequent first


Audio and video
================

How to read and inspect an audio or video file
-----------------------------------------------

.. code-block:: python

   with open('clip.mp4', 'rb') as f:
       asset = madam.read(f)

   print(asset.mime_type)             # 'video/quicktime'
   print(asset.duration)              # seconds, e.g. 120.5
   print(asset.metadata['video'])     # {'codec': 'h264', …}
   print(asset.metadata['audio'])     # {'codec': 'aac', …}


How to convert an audio or video file
---------------------------------------

.. code-block:: python

   from madam.video import VideoCodec
   from madam.audio import AudioCodec

   processor = madam.get_processor(asset)

   # Transcode MP4 → WebM with VP9 video and Opus audio.
   convert = processor.convert(
       mime_type='video/webm',
       video={'codec': VideoCodec.VP9},
       audio={'codec': AudioCodec.OPUS, 'bitrate': 128},
   )
   webm = convert(asset)
get_processor
   with open('output.webm', 'wb') as f:
       madam.write(webm, f)

Use :class:`~madam.video.VideoCodec` and :class:`~madam.audio.AudioCodec`
constants instead of raw FFmpeg codec strings to keep your code independent
of FFmpeg internals.  Raw strings still work for backward compatibility.


How to trim a video or audio clip
-----------------------------------

.. code-block:: python

   processor = madam.get_processor(asset)

   # Extract seconds 30–60.
   trim = processor.trim(start=30.0, duration=30.0)
   short_clip = trim(asset)


How to change playback speed
------------------------------

.. code-block:: python

   processor = madam.get_processor(asset)

   slow_mo    = processor.set_speed(factor=0.5)(asset)   # half speed
   time_lapse = processor.set_speed(factor=4.0)(asset)   # 4× faster


How to normalize audio loudness
---------------------------------

Use :meth:`~madam.ffmpeg.FFmpegProcessor.normalize_audio` for EBU R128
loudness normalization (two-pass FFmpeg ``loudnorm`` filter):

.. code-block:: python

   processor = madam.get_processor(asset)
   normalize = processor.normalize_audio(target_lufs=-23.0)
   normalized = normalize(asset)

   with open('normalized.mp3', 'wb') as f:
       madam.write(normalized, f)


How to concatenate clips
--------------------------

:func:`madam.video.concatenate` joins an iterable of clips end-to-end.  By
default streams are copied without re-encoding:

.. code-block:: python

   from madam.video import concatenate, VideoCodec
   from madam.audio import AudioCodec

   clips = [intro, main, outro]

   # Fast stream copy — use when all clips share the same codec.
   result = concatenate(clips, mime_type='video/mp4')

   # Force re-encoding — required when clips use different codecs.
   result = concatenate(
       clips,
       mime_type='video/mp4',
       video={'codec': VideoCodec.H264},
       audio={'codec': AudioCodec.AAC},
   )


How to burn in a graphic overlay
----------------------------------

Use :meth:`~madam.ffmpeg.FFmpegProcessor.overlay` to composite a static image
onto a video:

.. code-block:: python

   with open('logo.png', 'rb') as f:
       logo = madam.read(f)

   processor = madam.get_processor(video_asset)

   # Watermark in the bottom-right for the first 10 seconds only.
   burn_in = processor.overlay(
       overlay_asset=logo,
       gravity='south_east',
       to_seconds=10.0,
   )
   result = burn_in(video_asset)


How to generate a thumbnail sprite sheet
------------------------------------------

A sprite sheet lets browsers display seeking previews without fetching
individual frames.  Use :meth:`~madam.ffmpeg.FFmpegProcessor.thumbnail_sprite`:

.. code-block:: python

   processor = madam.get_processor(video_asset)

   make_sprite = processor.thumbnail_sprite(
       columns=5, rows=4,         # 20 thumbnails total
       thumb_width=160, thumb_height=90,
   )
   sheet = make_sprite(video_asset)

   # sheet.sprite contains: columns, rows, thumb_width, thumb_height,
   # interval_seconds — enough to generate a WebVTT thumbnail track.
   print(sheet.sprite)

   with open('sprite.jpg', 'wb') as f:
       f.write(sheet.essence.read())


How to create a video from images
-----------------------------------

:func:`~madam.ffmpeg.combine` converts a sequence of image (or video) assets
into a video by treating each asset as one frame at a fixed frame rate.
A default video codec is chosen automatically for the requested container;
you can override it with the ``video`` argument:

.. code-block:: python

   from madam.ffmpeg import combine
   from madam.video import VideoCodec

   # 3 frames at 2 fps → 1.5 second MP4 (H.264)
   video = combine(
       [img1, img2, img3],
       'video/mp4',
       fps=2.0,
       video={'codec': VideoCodec.H264},
   )

   # WebM / VP9 at 24 fps (default)
   webm = combine([img1, img2, img3], 'video/webm')

Supported output containers: ``video/mp4``, ``video/webm``,
``video/x-matroska``, ``video/quicktime``, ``video/x-msvideo``, and others.
:class:`~madam.core.UnsupportedFormatError` is raised for audio or image MIME
types.  :class:`~madam.core.OperatorError` is raised if FFmpeg fails.

.. versionadded:: 1.0


How to package a video for adaptive HTTP streaming
----------------------------------------------------

Use :meth:`~madam.ffmpeg.FFmpegProcessor.to_hls` (HTTP Live Streaming) or
:meth:`~madam.ffmpeg.FFmpegProcessor.to_dash` (MPEG-DASH).  Both write
multiple files (playlist + segments) to a :class:`~madam.streaming.MultiFileOutput`:

.. code-block:: python

   from madam.streaming import DirectoryOutput

   processor = madam.get_processor(video_asset)

   # HLS: writes index.m3u8 + segment_000.ts, segment_001.ts, …
   output = DirectoryOutput('/var/www/hls/video1')
   processor.to_hls(video_asset, output, segment_duration=6)

   # MPEG-DASH: writes manifest.mpd + media segments.
   output = DirectoryOutput('/var/www/dash/video1')
   processor.to_dash(video_asset, output, segment_duration=4)

Both methods accept optional ``video`` and ``audio`` dicts with ``codec`` and
``bitrate`` keys to customise the encoding.


Vector graphics
================

How to read and write an SVG file
-----------------------------------

SVG is handled by :class:`~madam.vector.SVGProcessor`, which is registered in
the default :class:`~madam.core.Madam` registry.  Use the familiar
:meth:`~madam.core.Madam.read` / :meth:`~madam.core.Madam.write` entry points:

.. code-block:: python

   from madam import Madam

   madam = Madam()

   with open('diagram.svg', 'rb') as f:
       asset = madam.read(f)

   print(asset.mime_type)   # 'image/svg+xml'
   print(asset.width)       # float, in px (if the root element has a width attribute)
   print(asset.height)      # float, in px (if the root element has a height attribute)

   with open('output.svg', 'wb') as f:
       madam.write(asset, f)


How to optimise an SVG file
-----------------------------

:meth:`~madam.vector.SVGProcessor.shrink` removes invisible and redundant
elements without changing the rendered appearance:

.. code-block:: python

   processor = madam.get_processor(asset)
   shrink = processor.shrink()
   small = shrink(asset)

The operator removes:

* XML whitespace (minification)
* Empty texts, groups, and ``<defs>`` sections
* Degenerate shapes: circles with ``r=0``, rectangles with ``width=0`` or
  ``height=0``, ellipses with a zero axis, paths without ``d``, polygons and
  polylines without ``points``, zero-length ``<line>`` elements
* Elements with ``display:none``, ``visibility:hidden``, or ``opacity:0``
* Empty ``<pattern>`` and ``<image>`` elements

All SVG length units (``px``, ``pt``, ``mm``, ``cm``, ``in``, ``em``, ``ex``,
``pc``, ``%``) are understood by the zero-value detection logic.

.. note::

   ``shrink()`` does not perform path simplification, coordinate rounding, or
   any lossy optimisation.  For aggressive size reduction, pass the result to an
   external tool such as ``svgo``.


How to read SVG metadata (RDF/DC)
-----------------------------------

:class:`~madam.vector.SVGMetadataProcessor` extracts the ``<svg:metadata>``
block, which typically contains RDF/Dublin Core markup:

.. code-block:: python

   from madam.vector import SVGMetadataProcessor

   meta_proc = SVGMetadataProcessor()

   with open('diagram.svg', 'rb') as f:
       metadata = meta_proc.read(f)

   # metadata['rdf']['xml'] contains the raw XML string of the metadata element.
   print(metadata['rdf'].get('xml'))

To strip the metadata block entirely:

.. code-block:: python

   with open('diagram.svg', 'rb') as f:
       clean = meta_proc.strip(f)   # returns a file-like object

   # Or use the high-level helper that chains all metadata processors:
   stripped = madam.strip(asset)

.. note::

   SVG metadata is also stripped automatically by :meth:`~madam.core.Madam.read`,
   so ``asset.essence`` never contains embedded metadata after a normal read.


Metadata
========

How to read EXIF metadata
---------------------------

EXIF data is automatically extracted by :meth:`~madam.core.Madam.read` and
stored under the ``'exif'`` key in the asset metadata:

.. code-block:: python

   asset = madam.read(open('photo.jpg', 'rb'))

   exif = asset.metadata.get('exif', {})
   print(exif.get('camera.manufacturer'))  # 'Canon'
   print(exif.get('camera.model'))         # 'EOS 5D Mark III'
   print(exif.get('focal_length'))         # 85.0  (mm)
   print(exif.get('fnumber'))              # 2.8
   print(exif.get('datetime_original'))    # datetime.datetime(2024, 6, 15, …)
   print(exif.get('gps.latitude'))         # 48.8583
   print(exif.get('orientation'))          # 1

Access the unified creation timestamp (drawn from EXIF, XMP, or container
metadata, whichever is most authoritative):

.. code-block:: python

   print(asset.created_at)   # '2024-06-15T10:30:00' or absent

Fields with no named mapping are collected under the ``'_raw'`` key:

.. code-block:: python

   raw = exif.get('_raw', {})   # dict keyed '<IFD>.<tag_int>'


How to read IPTC metadata
---------------------------

IPTC Application Record 2 data is automatically extracted from JPEG files:

.. code-block:: python

   iptc = asset.metadata.get('iptc', {})
   print(iptc.get('headline'))
   print(iptc.get('keywords'))    # list of strings
   print(iptc.get('caption'))
   print(iptc.get('copyright'))
   print(iptc.get('city'))
   print(iptc.get('country'))


How to read XMP metadata
--------------------------

XMP sidecar data is automatically extracted from JPEG files:

.. code-block:: python

   xmp = asset.metadata.get('xmp', {})
   print(xmp.get('title'))
   print(xmp.get('description'))
   print(xmp.get('subject'))       # list of strings
   print(xmp.get('rights'))
   print(xmp.get('creator'))
   print(xmp.get('create_date'))


How to write metadata back to a file
--------------------------------------

Use :meth:`~madam.core.Madam.write` together with an asset that carries
metadata.  The write pipeline re-embeds the metadata into the essence
automatically.  To modify a single field, create a new asset with updated
metadata:

.. code-block:: python

   from frozendict import frozendict

   # Add a copyright notice to an existing asset.
   updated_exif = dict(asset.metadata.get('exif', {}))
   updated_exif['description'] = 'Summit view, Zugspitze, 2024'

   new_metadata = dict(asset.metadata)
   new_metadata['exif'] = updated_exif

   from madam.core import Asset
   updated_asset = Asset(asset.essence, **new_metadata)

   with open('annotated.jpg', 'wb') as f:
       madam.write(updated_asset, f)


How to strip all metadata from a file
---------------------------------------

Use :meth:`~madam.core.Madam.strip` to produce a clean copy of any asset.
It removes all embedded metadata from both the Python metadata dict
*and* the essence bytes (EXIF, XMP, IPTC, ID3, FFmpeg container tags,
SVG RDF, …) while preserving structural properties such as ``mime_type``,
``width``, ``height``, and ``duration``:

.. code-block:: python

   with open('photo.jpg', 'rb') as f:
       asset = madam.read(f)

   clean = madam.strip(asset)

   # Format-specific dicts are gone.
   assert 'exif' not in clean.metadata
   assert 'xmp'  not in clean.metadata

   # Structural properties are preserved.
   assert clean.mime_type == asset.mime_type
   assert clean.width     == asset.width
   assert clean.height    == asset.height

   with open('clean.jpg', 'wb') as f:
       madam.write(clean, f)


Pipelines
=========

How to build a linear pipeline
--------------------------------

.. code-block:: python

   from madam.core import Pipeline
   from madam.image import ResizeMode

   madam = Madam({'image/jpeg': {'quality': 85}})

   with open('photo.jpg', 'rb') as f:
       asset = madam.read(f)

   processor = madam.get_processor(asset)

   pipeline = Pipeline()
   pipeline.add(processor.resize(width=1200, height=1200, mode=ResizeMode.FIT))
   pipeline.add(processor.sharpen(radius=1, percent=80))
   pipeline.add(processor.convert(mime_type='image/jpeg'))

   for result in pipeline.process(asset):
       with open('processed.jpg', 'wb') as f:
           madam.write(result, f)


How to build a branching pipeline
-----------------------------------

Use :meth:`~madam.core.Pipeline.branch` to produce multiple outputs from each
input — for example a thumbnail and a full-size preview:

.. code-block:: python

   from madam.core import Pipeline
   from madam.image import ResizeMode

   processor = madam.get_processor(asset)

   thumb_pipe = Pipeline()
   thumb_pipe.add(processor.resize(width=150, height=150, mode=ResizeMode.FILL))
   thumb_pipe.add(processor.convert(mime_type='image/webp'))

   preview_pipe = Pipeline()
   preview_pipe.add(processor.resize(width=1200, height=900, mode=ResizeMode.FIT))
   preview_pipe.add(processor.convert(mime_type='image/jpeg'))

   pipeline = Pipeline()
   pipeline.branch(thumb_pipe, preview_pipe)

   for result in pipeline.process(*source_assets):
       # Yields 2 × len(source_assets) assets in order:
       # (thumb_0, preview_0, thumb_1, preview_1, …)
       print(result.width, result.mime_type)


How to add conditional logic to a pipeline
--------------------------------------------

Use :meth:`~madam.core.Pipeline.when` to apply different operators based on
a predicate:

.. code-block:: python

   pipeline = Pipeline()

   # Downscale only images wider than 1920 px; leave others unchanged.
   pipeline.when(
       predicate=lambda a: a.width > 1920,
       then=processor.resize(width=1920, height=1080, mode=ResizeMode.FIT),
   )

   # Convert to WebP if PNG, else to JPEG.
   pipeline.when(
       predicate=lambda a: a.mime_type == 'image/png',
       then=processor.convert(mime_type='image/webp'),
       else_=processor.convert(mime_type='image/jpeg'),
   )


How deferred execution avoids quality loss
-------------------------------------------

When consecutive operators belong to the same processor, the pipeline groups
them into a **run** and encodes the result exactly once — not once per
operator.  For lossy formats (JPEG, AVIF, WebP, MP3, AAC, …) this prevents
cumulative quality degradation from multiple encode/decode cycles.  For
FFmpeg-based operations it also avoids spawning a subprocess per operator.

The behaviour is automatic — no API changes are needed:

.. code-block:: python

   from madam.core import Pipeline

   # All three operators share the same PillowProcessor, so Pillow decodes
   # the image once and encodes it once at the end.
   pipeline = Pipeline()
   pipeline.add(processor.resize(width=1200, height=900))
   pipeline.add(processor.crop(width=800, height=600, x=200, y=150))
   pipeline.add(processor.convert(mime_type='image/webp'))

   for result in pipeline.process(asset):
       ...

Materialisation (encoding to bytes) occurs automatically at:

* A **processor boundary** — when consecutive operators switch to a different
  processor.
* An **untagged step** — a plain function or lambda inserted in the pipeline.
* A **flush marker** (see below).


How to force an intermediate encode with ``Pipeline.flush()``
--------------------------------------------------------------

Sometimes you need stable intermediate bytes — for example to measure file
size after resizing before deciding whether to sharpen.  Insert
:meth:`~madam.core.Pipeline.flush` to force materialisation at that point:

.. code-block:: python

   from madam.core import Pipeline

   pipeline = Pipeline()
   pipeline.add(processor.resize(width=1200, height=900))
   pipeline.add(Pipeline.flush())   # encode to bytes here
   pipeline.add(processor.sharpen(radius=1, percent=80))

   for result in pipeline.process(asset):
       ...

Without the flush, ``resize`` and ``sharpen`` would be combined into a single
encode cycle.  With the flush, two separate encode/decode cycles occur.


Storage
=======

How to store and retrieve assets
----------------------------------

All storage backends subclass :class:`~madam.core.AssetStorage` and behave
like Python dicts.  The value is a ``(asset, tags)`` pair where ``tags`` is a
set of strings:

.. code-block:: python

   from madam.core import InMemoryStorage

   storage = InMemoryStorage()

   # Store.
   storage['hero'] = (asset, {'homepage', 'featured'})

   # Retrieve.
   hero, tags = storage['hero']
   print('hero' in storage)   # True
   print(len(storage))        # number of stored assets

   # Delete.
   del storage['hero']


How to filter assets by metadata
----------------------------------

.. code-block:: python

   # Find all JPEG assets.
   jpegs = list(storage.filter(mime_type='image/jpeg'))

   # Find all images wider than 2000 px.
   wide = list(storage.filter(width=2000))

:class:`~madam.core.InMemoryStorage` uses an inverted index so
:meth:`~madam.core.AssetStorage.filter` runs in O(k) time where k is the
number of matches, not the total number of stored assets.


How to filter assets by tags
------------------------------

.. code-block:: python

   # Assets that are tagged with BOTH 'homepage' AND 'featured'.
   results = list(storage.filter_by_tags({'homepage', 'featured'}))


How to persist assets to disk
-------------------------------

Use :class:`~madam.core.FileSystemAssetStorage` for atomic, crash-safe disk
storage.  Each asset is written as a pair of files (essence + JSON sidecar):

.. code-block:: python

   from madam.core import FileSystemAssetStorage

   storage = FileSystemAssetStorage('/var/lib/myapp/assets')
   storage['hero'] = (asset, {'homepage'})

   # The directory is created automatically.
   # Writes are atomic: a crash during write will not corrupt existing data.

Use :class:`~madam.core.ShelveStorage` as a simpler alternative when crash
safety is not a concern:

.. code-block:: python

   from madam.core import ShelveStorage

   storage = ShelveStorage('/var/lib/myapp/shelve')
   storage['hero'] = (asset, {'homepage'})


Optional formats
================

How to read HEIC/HEIF images
------------------------------

Install the optional ``pillow-heif`` plugin::

   pip install "madam[heif]"

After installation, ``madam.read()`` automatically recognises HEIC files.
All standard image operators work on the resulting asset:

.. code-block:: python

   with open('photo.heic', 'rb') as f:
       asset = madam.read(f)

   print(asset.mime_type)   # 'image/heic'

   # Convert to JPEG for wider compatibility.
   processor = madam.get_processor(asset)
   convert = processor.convert(mime_type='image/jpeg')
   jpeg = convert(asset)

.. note:: Writing back to HEIC is not supported by the plugin.


How to combine images into a PDF
----------------------------------

:func:`~madam.pdf.combine` assembles a sequence of image assets into a
multi-page PDF.  It requires no external libraries beyond Pillow (which is
always installed).  The ``page_width`` and ``page_height`` parameters are in
PDF points (1 pt = 1/72 inch; at 72 DPI one point equals one pixel).

The :data:`~madam.pdf.PAGE_SIZES` dictionary provides common paper sizes::

   pip install "madam[pdf]"   # only needed if you also want to rasterize PDFs

.. code-block:: python

   from madam.pdf import combine, PAGE_SIZES

   # Combine two images into an A4 PDF (portrait).
   pdf = combine([cover_asset, figure_asset], **PAGE_SIZES['a4'])

   with open('document.pdf', 'wb') as f:
       f.write(pdf.essence.read())

Each image is scaled to fit its page (preserving aspect ratio) and centred on
a white background.  The output always has ``mime_type='application/pdf'`` and
a ``page_count`` metadata attribute.

.. versionadded:: 1.0


How to rasterize a PDF page
------------------------------

Install the optional PDF dependencies (requires Poppler on the system)::

   pip install "madam[pdf]"

Once installed, :class:`~madam.pdf.PDFProcessor` is registered automatically
and you can use the standard :meth:`~madam.core.Madam.read` /
:meth:`~madam.core.Madam.get_processor` entry points:

.. code-block:: python

   with open('document.pdf', 'rb') as f:
       pdf_asset = madam.read(f)

   print(pdf_asset.page_count)   # total pages

   processor = madam.get_processor(pdf_asset)

   # Rasterize page 0 (first page) at 150 DPI as PNG.
   rasterize = processor.rasterize(page=0, dpi=150, mime_type='image/png')
   image = rasterize(pdf_asset)

   with open('page1.png', 'wb') as f:
       f.write(image.essence.read())


How to rasterize all pages of a PDF
--------------------------------------

Iterate over the ``page_count`` metadata attribute to convert every page:

.. code-block:: python

   with open('document.pdf', 'rb') as f:
       pdf_asset = madam.read(f)

   processor = madam.get_processor(pdf_asset)

   for page_index in range(pdf_asset.page_count):
       rasterize = processor.rasterize(page=page_index, dpi=150, mime_type='image/png')
       image = rasterize(pdf_asset)
       with open(f'page_{page_index + 1:04d}.png', 'wb') as f:
           f.write(image.essence.read())

You can feed the resulting image assets into any standard image pipeline:

.. code-block:: python

   # After rasterizing, use the Madam registry for further processing.
   image_processor = madam.get_processor(image)
   thumbnail = image_processor.resize(width=800, height=600)(image)

.. note::

   Supported output formats for rasterization are those accepted by
   ``pdf2image`` / Poppler: ``image/png``, ``image/jpeg``, ``image/tiff``.


How to decode a raw camera file (DNG, CR2, NEF, …)
----------------------------------------------------

Install the optional ``rawpy`` library (requires LibRaw on the system)::

   pip install "madam[raw]"

Once installed, :class:`~madam.raw.RawImageProcessor` is registered
automatically and you can use the standard entry points:

.. code-block:: python

   with open('photo.dng', 'rb') as f:
       raw_asset = madam.read(f)

   print(raw_asset.mime_type)   # 'image/x-raw'
   print(raw_asset.width)       # sensor width in pixels

   processor = madam.get_processor(raw_asset)

   # Decode the raw Bayer data to a TIFF (lossless).
   tiff = processor.decode(mime_type='image/tiff')(raw_asset)

   # Hand off to the normal image pipeline via the Madam registry.
   image_processor = madam.get_processor(tiff)
   thumbnail = image_processor.resize(width=800, height=600)(tiff)


Error handling
==============

MADAM uses a small exception hierarchy rooted at
:class:`~madam.core.OperatorError`::

   OperatorError
   ├── UnsupportedFormatError   # format not recognised or not supported
   ├── TransientOperatorError   # failure may go away on retry
   └── PermanentOperatorError   # failure is unrecoverable


How to handle read errors
--------------------------

:meth:`~madam.core.Madam.read` raises :class:`~madam.core.UnsupportedFormatError`
when no registered processor recognises the file:

.. code-block:: python

   from madam.core import UnsupportedFormatError

   try:
       asset = madam.read(f)
   except UnsupportedFormatError as e:
       log.warning('Cannot read file: %s', e)
       # Handle unsupported input — skip, quarantine, or raise to caller.

This can happen for genuinely unsupported formats, truncated files, or files
with incorrect content (e.g. a ``.jpg`` extension on a ZIP archive).


How to handle format detection errors
---------------------------------------

:meth:`~madam.core.Madam.get_processor` also raises
:class:`~madam.core.UnsupportedFormatError` when no processor can handle the
given asset, MIME type string, or file object:

.. code-block:: python

   from madam.core import UnsupportedFormatError

   try:
       processor = madam.get_processor(asset)
   except UnsupportedFormatError:
       log.warning('No processor for MIME type: %s', asset.mime_type)

``get_processor()`` never returns ``None`` — it either returns a usable
processor or raises.


How to handle operator errors
--------------------------------

All operator failures raise from the :class:`~madam.core.OperatorError`
hierarchy.  Use :class:`~madam.core.TransientOperatorError` vs
:class:`~madam.core.PermanentOperatorError` to decide whether to retry:

.. code-block:: python

   from madam.core import (
       OperatorError,
       TransientOperatorError,
       PermanentOperatorError,
       UnsupportedFormatError,
   )

   try:
       result = operator(asset)
   except UnsupportedFormatError:
       # The format is not supported at all — discard.
       log.warning('Unsupported format: %s', asset.mime_type)
   except TransientOperatorError:
       # Temporary failure (e.g. out of memory) — retry later.
       queue.retry()
   except PermanentOperatorError:
       # Permanent failure (corrupt input, unsupported codec) — dead-letter.
       queue.dead_letter()
   except OperatorError:
       # Catch-all for unexpected operator errors.
       log.error('Operator failed', exc_info=True)


How to implement a robust batch processing loop
-------------------------------------------------

Combine the error classes to build a resilient pipeline that skips bad files,
retries transient failures, and dead-letters permanent failures:

.. code-block:: python

   import logging
   from madam.core import (
       UnsupportedFormatError,
       TransientOperatorError,
       PermanentOperatorError,
       OperatorError,
   )

   log = logging.getLogger(__name__)

   def process_file(path, max_retries=3):
       for attempt in range(1, max_retries + 1):
           try:
               with open(path, 'rb') as f:
                   asset = madam.read(f)
               processor = madam.get_processor(asset)
               result = processor.convert(mime_type='image/webp')(asset)
               return result
           except UnsupportedFormatError:
               log.warning('Skipping unsupported file: %s', path)
               return None
           except PermanentOperatorError:
               log.error('Permanent failure, dead-lettering: %s', path)
               dead_letter_queue.append(path)
               return None
           except TransientOperatorError:
               if attempt == max_retries:
                   log.error('Giving up after %d retries: %s', max_retries, path)
                   return None
               log.warning('Transient failure, retrying (%d/%d): %s', attempt, max_retries, path)
           except OperatorError as e:
               log.error('Unexpected operator error: %s — %s', path, e, exc_info=True)
               return None
