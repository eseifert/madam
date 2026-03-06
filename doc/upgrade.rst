Upgrade Guide
=============

This page documents all changes users of the MADAM library need to be aware
of when upgrading from one release to the next.

.. contents::
   :local:
   :depth: 2


0.26.0 → 1.0.0
---------------

All changes in this release are new features.  There are no breaking changes.


New features
~~~~~~~~~~~~

New: Optional processors auto-registered when extras are installed
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

:class:`~madam.pdf.PDFProcessor` and :class:`~madam.raw.RawImageProcessor` are
now registered automatically in the default :class:`~madam.core.Madam` registry
when the corresponding optional extra is installed.  This means you can use
the standard :meth:`~madam.core.Madam.read` / :meth:`~madam.core.Madam.get_processor`
entry points instead of instantiating the processors directly:

.. code-block:: python

   # With madam[pdf] installed — no import needed
   with open('document.pdf', 'rb') as f:
       pdf_asset = madam.read(f)

   processor = madam.get_processor(pdf_asset)   # → PDFProcessor
   image = processor.rasterize(page=0, dpi=150)(pdf_asset)

   # With madam[raw] installed
   with open('photo.dng', 'rb') as f:
       raw_asset = madam.read(f)

   processor = madam.get_processor(raw_asset)   # → RawImageProcessor
   tiff = processor.decode(mime_type='image/tiff')(raw_asset)

Direct instantiation (``PDFProcessor()``, ``RawImageProcessor()``) continues
to work and remains the only option when the extras are *not* installed.


New: Deferred pipeline execution
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

:class:`~madam.core.Pipeline` now groups consecutive operators that share the
same :class:`~madam.core.Processor` into a single *run* and dispatches them
via the new :meth:`~madam.core.Processor.execute_run` hook.  Built-in
processors (:class:`~madam.image.PillowProcessor`,
:class:`~madam.ffmpeg.FFmpegProcessor`, :class:`~madam.vector.SVGProcessor`)
exploit this to avoid intermediate encode/decode cycles — all chained operators
of the same type are fused into a single pass, preserving full pixel fidelity.

No changes are needed for existing pipelines.  The optimisation is transparent:

.. code-block:: python

   from madam.core import Pipeline

   pipeline = Pipeline()
   pipeline.add(processor.resize(width=1920, height=1080))
   pipeline.add(processor.crop(width=1280, height=720, x=0, y=0))
   pipeline.add(processor.convert(mime_type='image/webp'))

   # All three operators are now applied in a single Pillow pass — no
   # intermediate JPEG/PNG encode between resize and crop.
   for result in pipeline.process(asset):
       ...


New: ``madam.pdf.combine()`` — images to multi-page PDF
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

:func:`~madam.pdf.combine` assembles a sequence of image assets into a
multi-page PDF using Pillow (no external PDF library required for this
function):

.. code-block:: python

   from madam.pdf import combine, PAGE_SIZES

   pdf = combine([cover_asset, figure_asset], **PAGE_SIZES['a4'])
   # → Asset(mime_type='application/pdf', page_count=2)

Named page sizes (in PDF points) are available via
:data:`~madam.pdf.PAGE_SIZES`: ``'a4'``, ``'letter'``, ``'a3'``, ``'legal'``.
Pass custom dimensions as ``page_width=`` / ``page_height=`` keyword arguments.


New: ``madam.image.combine()`` — frames to animated GIF or WebP
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

:func:`~madam.image.combine` assembles a list of image assets into an animated
GIF or WebP:

.. code-block:: python

   from madam.image import combine

   gif  = combine([frame1, frame2, frame3], 'image/gif',  duration=200, loop=0)
   webp = combine([frame1, frame2],         'image/webp', duration=100)

``duration`` is the per-frame delay in milliseconds (default ``100``).
``loop=0`` means infinite looping.  :class:`~madam.core.UnsupportedFormatError`
is raised for any MIME type other than ``'image/gif'`` and ``'image/webp'``.


New: ``madam.ffmpeg.combine()`` — images to video
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

:func:`~madam.ffmpeg.combine` converts a sequence of image (or video) assets
into a video, treating each asset as one frame at a fixed frame rate:

.. code-block:: python

   from madam.ffmpeg import combine
   from madam.video import VideoCodec

   video = combine(
       [img1, img2, img3],
       'video/mp4',
       fps=2.0,
       video={'codec': VideoCodec.H264},
   )

A default codec is selected per container when ``video`` is omitted.
:class:`~madam.core.UnsupportedFormatError` is raised for non-video MIME types
(audio, image).


New: ``Pipeline.flush()``
^^^^^^^^^^^^^^^^^^^^^^^^^^

:meth:`~madam.core.Pipeline.flush` returns a sentinel step that forces an
intermediate encode/decode cycle between two operators that would otherwise
be deferred together.  Insert it when the intermediate byte layout matters
(e.g. to measure file size between two encode steps):

.. code-block:: python

   pipeline = Pipeline()
   pipeline.add(processor.resize(width=800, height=600))
   pipeline.add(Pipeline.flush())   # force encode/decode here
   pipeline.add(processor.convert(mime_type='image/webp'))


New: ``ProcessingContext`` ABC
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

:class:`~madam.core.ProcessingContext` is the abstract base class for deferred
in-memory state.  Implement it alongside a :meth:`~madam.core.Processor.execute_run`
override to add deferred execution to a custom processor.


New: ``PillowContext``, ``FFmpegContext``, ``SVGContext``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Three concrete :class:`~madam.core.ProcessingContext` subclasses are now part
of the stable public API, documented with their full attribute contracts:

* :class:`~madam.image.PillowContext` — exposes the live
  :class:`PIL.Image.Image` (``image``) and target format (``mime_type``).
* :class:`~madam.ffmpeg.FFmpegContext` — exposes the source
  :class:`~madam.core.Asset` (``asset``) and the accumulating
  :class:`~madam.ffmpeg.FFmpegFilterGraph` (``graph``).
* :class:`~madam.vector.SVGContext` — exposes the live
  :class:`xml.etree.ElementTree.ElementTree` (``tree``).

Custom operator implementations may inspect or extend these objects before
the pipeline materialises the result.


New: ``FFmpegFilterGraph``
^^^^^^^^^^^^^^^^^^^^^^^^^^^

:class:`~madam.ffmpeg.FFmpegFilterGraph` accumulates FFmpeg video/audio
filters and codec options for a single deferred run.  It is now part of the
stable public API.  Custom FFmpeg operators can receive one via
:attr:`~madam.ffmpeg.FFmpegContext.graph` and call
:meth:`~madam.ffmpeg.FFmpegFilterGraph.add_video_filter`,
:meth:`~madam.ffmpeg.FFmpegFilterGraph.add_audio_filter`,
:meth:`~madam.ffmpeg.FFmpegFilterGraph.set_codec_options`, etc.


----


0.25.0 → 0.26.0
----------------

Breaking changes
~~~~~~~~~~~~~~~~

``crop()`` parameters are now keyword-only
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

:meth:`~madam.image.PillowProcessor.crop` and
:meth:`~madam.ffmpeg.FFmpegProcessor.crop` now require all parameters after
``asset`` to be passed as keyword arguments.  Positional calls will raise a
``TypeError``:

.. code-block:: python

   # Before (positional — no longer valid)
   cropped = processor.crop(asset, 100, 100, 10, 10)

   # After (keyword-only — required)
   cropped = processor.crop(asset, width=100, height=100, x=10, y=10)

This change makes call sites self-documenting and prevents silent argument
transposition bugs.  The ``@operator`` decorator already requires users to call
processor methods with ``**kwargs``, so most existing code is unaffected.


0.24.0 → 0.25.0
----------------

Breaking changes
~~~~~~~~~~~~~~~~

Zopfli PNG compression is now opt-in
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

``zopflipy`` has been moved from a required dependency to the optional
``optimize`` extra.  The ``zopfli`` configuration key now **defaults to**
``False`` instead of ``True``.

If you relied on Zopfli compression, install the extra and explicitly
enable it in your configuration:

.. code-block:: bash

   pip install "madam[optimize]"

.. code-block:: python

   madam = Madam({'image/png': {'zopfli': True}})

Code that sets ``'zopfli': True`` but does *not* install ``madam[optimize]``
will now raise an ``ImportError`` with a clear installation hint instead of
silently falling back.


New features
~~~~~~~~~~~~

New: ``Madam.strip()`` removes all metadata
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

:meth:`~madam.core.Madam.strip` is the new canonical way to produce a
metadata-free copy of any asset.  It strips both the Python-level metadata
dict *and* the embedded bytes (EXIF APP1, XMP APP1, IPTC APP13, ID3 tags,
FFmpeg container atoms, SVG RDF, …), then returns a clean asset whose
structural properties (``mime_type``, ``width``, ``height``, ``duration``,
…) are preserved:

.. code-block:: python

   with open('photo.jpg', 'rb') as f:
       asset = madam.read(f)

   clean = madam.strip(asset)

   assert 'exif' not in clean.metadata
   assert 'xmp'  not in clean.metadata
   assert clean.width  == asset.width
   assert clean.height == asset.height

   with open('clean.jpg', 'wb') as f:
       madam.write(clean, f)

See the :doc:`howto` guide for a worked example.


Bug fixes
~~~~~~~~~

SVG: ``shrink()`` zero-value detection
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

:meth:`~madam.vector.SVGProcessor.shrink` previously only recognised the
exact string ``"0"`` when removing invisible elements (zero-radius circles,
zero-dimension rectangles, opacity-zero elements, etc.).  Values such as
``"0.0"`` or ``"0px"`` were missed and those elements were left in the
output.  All zero-value checks now use the unit-aware ``svg_length_to_px``
converter.

SVG: ``shrink()`` removes zero-length ``<line>`` elements
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

``<line>`` elements where both endpoints are identical (``x1 == x2`` and
``y1 == y2``) are now removed by :meth:`~madam.vector.SVGProcessor.shrink`.

SVG: ``shrink()`` no longer crashes on deeply nested documents
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The internal whitespace-removal pass was recursive and raised
``RecursionError`` on SVG files with a nesting depth exceeding Python's
call-stack limit (~1000 levels).  The implementation is now iterative.


0.23.0 → 0.24.0
----------------

All changes in this release are new features.  There are no breaking changes.


New features
~~~~~~~~~~~~

New: ``get_processor()`` accepts ``Asset`` and MIME type strings
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

:meth:`~madam.core.Madam.get_processor` now accepts three kinds of input:

* **An** :class:`~madam.core.Asset` *(preferred)* — performs an O(1) MIME type
  look-up; no I/O or byte-probing is needed because the type is already known.
* **A MIME type string** — also O(1), useful when you know the format without
  holding an asset.
* **A file-like object** — the original byte-probe loop (unchanged).

The preferred calling form is now:

.. code-block:: python

   # Before (still works, but triggers a byte-probe)
   processor = madam.get_processor(asset.essence)

   # After (O(1) lookup — preferred)
   processor = madam.get_processor(asset)

   # Also new: look up by MIME type string
   processor = madam.get_processor('image/jpeg')

Additionally, ``get_processor()`` now **raises** :class:`~madam.core.UnsupportedFormatError`
when no processor can handle the input instead of returning ``None``.
Update any code that checks the return value:

.. code-block:: python

   # Before
   processor = madam.get_processor(file)
   if processor is None:
       handle_unknown()

   # After
   try:
       processor = madam.get_processor(file)
   except UnsupportedFormatError:
       handle_unknown()


New: Image adjustment operators
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

:class:`~madam.image.PillowProcessor` gained four tonal and colour adjustment
operators.  Each returns an ``Asset → Asset`` callable and accepts a *factor*
of ``1.0`` to produce an output identical to the input:

.. code-block:: python

   processor = madam.get_processor(asset)

   # Increase brightness by 40 %
   brighter = processor.adjust_brightness(factor=1.4)
   result = brighter(asset)

   # Increase contrast by 20 %
   more_contrast = processor.adjust_contrast(factor=1.2)
   result = more_contrast(asset)

   # Desaturate to 50 % colour intensity
   faded = processor.adjust_saturation(factor=0.5)
   result = faded(asset)

   # Slightly sharpen the image
   sharpened = processor.adjust_sharpness(factor=1.5)
   result = sharpened(asset)

Available operators:

* :meth:`~madam.image.PillowProcessor.adjust_brightness` — ``factor``:
  ``0.0`` → black image, ``1.0`` → no change, ``2.0`` → doubled brightness.
* :meth:`~madam.image.PillowProcessor.adjust_contrast` — ``factor``:
  ``0.0`` → solid grey, ``1.0`` → no change.
* :meth:`~madam.image.PillowProcessor.adjust_saturation` — ``factor``:
  ``0.0`` → greyscale, ``1.0`` → no change.
* :meth:`~madam.image.PillowProcessor.adjust_sharpness` — ``factor``:
  ``0.0`` → blurred, ``1.0`` → no change, ``>1.0`` → sharpened.


New: Artistic effect operators
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Three new operators apply artistic visual effects to image assets:

.. code-block:: python

   # Vintage sepia tone
   make_sepia = processor.sepia()
   sepia_asset = make_sepia(asset)

   # Warm orange colour tint at 30 % opacity
   warm_tint = processor.tint(color=(255, 180, 80), opacity=0.3)
   tinted = warm_tint(asset)

   # Radial vignette that darkens the corners by 50 %
   add_vignette = processor.vignette(strength=0.5)
   vignetted = add_vignette(asset)

* :meth:`~madam.image.PillowProcessor.sepia` — no parameters; converts the
  image to greyscale and recolorises it with warm brown tones.
* :meth:`~madam.image.PillowProcessor.tint` — ``color`` (RGB tuple),
  ``opacity`` in ``[0.0, 1.0]``.
* :meth:`~madam.image.PillowProcessor.vignette` — ``strength`` in
  ``[0.0, 1.0]``; ``0.0`` leaves the image unchanged, ``1.0`` makes the
  corners completely black.


New: ``blur`` and ``sharpen`` operators
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Two new filter operators complement the adjustment operators above:

.. code-block:: python

   # Gaussian blur with a 3-pixel radius
   make_blur = processor.blur(radius=3)
   blurred = make_blur(asset)

   # Unsharp mask: radius, sharpening strength (%), minimum pixel difference
   do_sharpen = processor.sharpen(radius=2, percent=150, threshold=3)
   result = do_sharpen(asset)

* :meth:`~madam.image.PillowProcessor.blur` — Gaussian blur; ``radius`` in
  pixels, ``0`` means no blur.
* :meth:`~madam.image.PillowProcessor.sharpen` — unsharp mask; ``percent``
  controls strength (100 = 100 % of the mask added back), ``threshold`` is
  the minimum brightness difference (0–255) that will be sharpened.


New: Canvas and compositing operators
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Several new operators handle canvas manipulation and multi-image compositing:

.. code-block:: python

   # Place an image on a white canvas with a 20 px border on all sides
   add_border = processor.pad(
       width=asset.width + 40,
       height=asset.height + 40,
       color=(255, 255, 255),
       gravity='center',
   )
   padded = add_border(asset)

   # Flatten a transparent PNG onto a solid white background
   flatten = processor.fill_background(color=(255, 255, 255))
   opaque = flatten(asset)

   # Composite a watermark at 70 % opacity in the bottom-right corner
   add_watermark = processor.composite(
       overlay_asset=watermark,
       gravity='south_east',
       opacity=0.7,
   )
   watermarked = add_watermark(asset)

* :meth:`~madam.image.PillowProcessor.pad` — ``width``, ``height``, ``color``
  (RGB or RGBA tuple), ``gravity``.  Raises :exc:`~madam.core.OperatorError`
  if the canvas is smaller than the source image.
* :meth:`~madam.image.PillowProcessor.fill_background` — ``color`` (RGB
  tuple); composites alpha pixels over a solid background.  If the source has
  no alpha channel the image is returned unchanged.
* :meth:`~madam.image.PillowProcessor.composite` — ``overlay_asset``, ``x``,
  ``y``, ``gravity``, ``opacity`` in ``[0.0, 1.0]``.

Valid gravity strings for all operators: ``'north_west'``, ``'north'``,
``'north_east'``, ``'west'``, ``'center'``, ``'east'``, ``'south_west'``,
``'south'``, ``'south_east'``.


New: Masking and rounded corners
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Two new operators create shaped images; both always produce RGBA PNG assets:

.. code-block:: python

   # Cut rounded corners with a 20 px radius (output is RGBA PNG)
   rounded = processor.round_corners(radius=20)(asset)

   # Replace the alpha channel with a greyscale mask image
   masked = processor.apply_mask(mask_asset=mask)(asset)

* :meth:`~madam.image.PillowProcessor.round_corners` — ``radius`` in pixels.
* :meth:`~madam.image.PillowProcessor.apply_mask` — ``mask_asset`` must have
  the same dimensions as the base image; white (255) → fully opaque, black
  (0) → fully transparent.


New: Gravity parameter on ``crop`` and ``resize(FILL)``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

:meth:`~madam.image.PillowProcessor.crop` now accepts a ``gravity`` parameter
so callers no longer need to compute ``x``/``y`` manually:

.. code-block:: python

   from madam.image import ResizeMode

   processor = madam.get_processor(asset)

   # Crop 800×600 from the centre of the image
   center_crop = processor.crop(width=800, height=600, gravity='center')
   result = center_crop(asset)

:meth:`~madam.image.PillowProcessor.resize` with ``mode=ResizeMode.FILL``
now accepts a ``gravity`` parameter that controls which part of the
over-cropped image is preserved (default: ``'center'``):

.. code-block:: python

   # Cover-fill to 400×400, keeping the top of the image
   cover_top = processor.resize(
       width=400, height=400,
       mode=ResizeMode.FILL,
       gravity='north',
   )
   result = cover_top(asset)

Existing code that passes explicit ``x`` and ``y`` to ``crop`` continues to
work unchanged.


New: ``crop_to_focal_point``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

:meth:`~madam.image.PillowProcessor.crop_to_focal_point` crops to the given
dimensions while keeping a focal point — expressed as relative ``[0.0, 1.0]``
coordinates — as close to the centre of the output as possible:

.. code-block:: python

   # Crop to 640×480 keeping the subject at 60 % across and 30 % down
   crop_face = processor.crop_to_focal_point(
       width=640, height=480,
       focal_x=0.6, focal_y=0.3,
   )
   result = crop_face(portrait)

The caller is responsible for supplying the focal-point coordinates (e.g. via
face detection or saliency analysis); the operator only handles the geometry.


New: ``extract_frame`` and ``frame_count`` for animated images
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

:meth:`~madam.image.PillowProcessor.read` now stores ``frame_count`` in the
asset metadata for animated images (GIF, animated WebP):

.. code-block:: python

   with open('animation.gif', 'rb') as f:
       animated = madam.read(f)

   print(animated.frame_count)   # e.g. 24

The new :meth:`~madam.image.PillowProcessor.extract_frame` operator extracts a
single frame as a static image:

.. code-block:: python

   # Extract the fifth frame (zero-based index)
   get_frame = processor.extract_frame(frame=4)
   static = get_frame(animated)

Raises :exc:`~madam.core.OperatorError` when the frame index is out of range.


New: ``render_text`` module-level function
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

:func:`~madam.image.render_text` creates a new RGBA PNG
:class:`~madam.core.Asset` from a text string.  The canvas is automatically
sized to fit the text, with optional padding:

.. code-block:: python

   from madam.image import render_text

   label = render_text(
       'Hello, MADAM!',
       font_path='/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
       font_size=48,
       color=(255, 255, 255),
       background=(0, 0, 0, 200),   # semi-transparent black background
       padding=16,
   )
   # label is an RGBA PNG Asset sized to the text + padding

When ``font_path`` is ``None``, Pillow's built-in default font is used
(``font_size`` is then ignored).


New: ``optimize_quality`` operator
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

:meth:`~madam.image.PillowProcessor.optimize_quality` re-encodes an image at
the lowest quality level whose perceptual quality (measured by SSIMULACRA2)
still meets a given threshold.

Requires the ``ssimulacra2`` optional dependency::

   pip install "madam[analysis]"

.. code-block:: python

   # Smallest JPEG that scores ≥ 85 on the SSIMULACRA2 scale
   optimize = processor.optimize_quality(
       min_ssim_score=85.0,
       mime_type='image/jpeg',
   )
   small_jpeg = optimize(png_asset)

SSIMULACRA2 scores are in ``(−∞, 100]`` where ``100`` means identical.
Typical thresholds: ≥ 90 nearly imperceptible, ≥ 80 good, ≥ 70 acceptable.
Supported output formats: JPEG, WebP, AVIF.


New: ``extract_palette`` module-level function
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

:func:`~madam.image.extract_palette` returns the *count* dominant colors in
an image as a list of ``(r, g, b)`` tuples sorted by pixel frequency:

.. code-block:: python

   from madam.image import extract_palette

   colors = extract_palette(asset, count=5)
   # [(255, 200, 0), (10, 60, 120), …]  — most frequent first


New: HEIC/HEIF format support
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

:class:`~madam.image.PillowProcessor` now supports HEIC/HEIF images when the
``pillow-heif`` optional dependency is installed::

   pip install "madam[heif]"

After installation, ``madam.read()`` automatically recognises HEIC files and
returns assets with ``mime_type='image/heic'``.  All standard image operators
(``resize``, ``convert``, ``crop``, etc.) work on the resulting asset.

.. note::

   HEIC read and conversion to other formats are supported.  Writing back to
   HEIC/HEIF is not supported by the ``pillow-heif`` plugin.


New: PDF support
^^^^^^^^^^^^^^^^

A new :class:`~madam.pdf.PDFProcessor` is available with the ``[pdf]``
optional extra::

   pip install "madam[pdf]"

.. code-block:: python

   from madam.pdf import PDFProcessor

   processor = PDFProcessor()

   with open('document.pdf', 'rb') as f:
       pdf_asset = processor.read(f)

   print(pdf_asset.page_count)   # total number of pages

   # Rasterize the second page (0-based) at 150 DPI as PNG
   rasterize = processor.rasterize(page=1, dpi=150, mime_type='image/png')
   image_asset = rasterize(pdf_asset)

Metadata set by ``read()``: ``mime_type='application/pdf'``, ``page_count``.
The default output format for ``rasterize`` is ``'image/jpeg'`` at 72 DPI.


New: Raw camera format support
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

A new :class:`~madam.raw.RawImageProcessor` is available with the ``[raw]``
optional extra (requires LibRaw to be installed system-wide)::

   pip install "madam[raw]"

.. code-block:: python

   from madam.raw import RawImageProcessor

   processor = RawImageProcessor()

   with open('photo.dng', 'rb') as f:
       raw_asset = processor.read(f)

   # Decode the raw Bayer data to a standard image format
   decode = processor.decode(mime_type='image/tiff')
   image_asset = decode(raw_asset)

``read()`` returns an asset with ``mime_type='image/x-raw'`` and the sensor
``width`` / ``height``.  Supported raw formats depend on LibRaw; common ones
include DNG, CR2, NEF, and ARW.


New: ``IPTCMetadataProcessor``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

:class:`~madam.iptc.IPTCMetadataProcessor` reads and writes IPTC Application
Record (record 2) metadata stored in JPEG APP13 segments:

.. code-block:: python

   from madam.iptc import IPTCMetadataProcessor

   processor = IPTCMetadataProcessor()

   with open('photo.jpg', 'rb') as f:
       metadata = processor.read(f)

   iptc = metadata.get('iptc', {})
   print(iptc.get('headline'))
   print(iptc.get('keywords'))   # list of strings
   print(iptc.get('copyright'))

Supported keys: ``object_name``, ``category``, ``keywords`` (list),
``instructions``, ``author``, ``author_title``, ``city``, ``sublocation``,
``state``, ``country_code``, ``country``, ``headline``, ``credit``,
``source``, ``copyright``, ``caption``.

``IPTCMetadataProcessor`` is registered in :class:`~madam.core.Madam` by
default, so IPTC values appear automatically in assets returned by
:meth:`~madam.core.Madam.read`:

.. code-block:: python

   asset = madam.read(open('photo.jpg', 'rb'))
   print(asset.metadata.get('iptc', {}).get('headline'))


New: ``XMPMetadataProcessor``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

:class:`~madam.xmp.XMPMetadataProcessor` reads and writes XMP sidecar data
stored in JPEG APP1 segments:

.. code-block:: python

   from madam.xmp import XMPMetadataProcessor

   processor = XMPMetadataProcessor()

   with open('photo.jpg', 'rb') as f:
       metadata = processor.read(f)

   xmp = metadata.get('xmp', {})
   print(xmp.get('title'))
   print(xmp.get('subject'))      # list of strings
   print(xmp.get('create_date'))

Supported keys: ``title``, ``description``, ``subject`` (list), ``rights``,
``creator``, ``create_date``, ``modify_date``.

Like ``IPTCMetadataProcessor``, ``XMPMetadataProcessor`` is registered in
:class:`~madam.core.Madam` by default.


New: ``created_at`` unified timestamp in ``Madam.read()``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

:meth:`~madam.core.Madam.read` now sets a top-level ``created_at`` key on
the returned asset when a creation timestamp can be found in the media.  The
value is a normalised ISO 8601 string and is resolved from the first available
source in priority order:

1. EXIF ``DateTimeOriginal``
2. XMP ``CreateDate``
3. FFmpeg ``creation_time`` tag (video/audio)

.. code-block:: python

   asset = madam.read(open('photo.jpg', 'rb'))
   print(asset.created_at)   # e.g. '2024-06-15T10:30:00'

The attribute is absent (not ``None``) when no creation timestamp is found in
any metadata source.


New: EXIF ``datetime_original`` and ``datetime_digitized`` as ``datetime`` objects
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

:class:`~madam.exif.ExifMetadataProcessor` now returns ``datetime_original``
and ``datetime_digitized`` as :class:`datetime.datetime` objects instead of
raw EXIF date strings:

.. code-block:: python

   asset = madam.read(open('photo.jpg', 'rb'))
   dt = asset.metadata.get('exif', {}).get('datetime_original')
   if dt:
       print(f'Taken on {dt.strftime("%Y-%m-%d at %H:%M")}')

Code that previously compared or parsed these values as strings must be
updated to use the ``datetime`` interface.


New: FFmpegMetadataProcessor key coverage for MKV, MOV, and AVI
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

:class:`~madam.ffmpeg.FFmpegMetadataProcessor` now maps common metadata keys
for the following containers:

* **MKV / WebM** — title (lowercase), plus uppercase tags such as
  ``DESCRIPTION``, ``ARTIST``, ``ALBUM``, ``DATE``, etc.
* **MOV / MP4 / QuickTime** — title, artist, album, date, comment, copyright,
  etc.
* **AVI** — INAM (title), IART (artist), ICRD (date), etc.

Previously these containers returned an empty metadata dict from ``read()``.
No changes are needed for existing code; the new keys are simply available
where they were absent before.


New: ICC profile preservation in ``PillowProcessor``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

:class:`~madam.image.PillowProcessor` now extracts an embedded ICC profile
during ``read()`` and re-embeds it when writing.  All image operators
(``resize``, ``convert``, ``crop``, ``pad``, ``composite``, etc.) propagate
the ICC profile transparently through the transformation chain.

The raw profile bytes are stored in ``asset.metadata['icc_profile']``.  They
are automatically re-embedded when writing to formats that support ICC
profiles: JPEG, PNG, TIFF, WebP, and AVIF.

No action is required for existing code; the change is transparent.  To
strip an ICC profile, remove the ``'icc_profile'`` key from the metadata
dict before passing the asset to an operator.


New: FFmpeg audio/video operators
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The following operators were added to
:class:`~madam.ffmpeg.FFmpegProcessor`:

**set_speed** — scale playback speed:

.. code-block:: python

   processor = madam.get_processor(video_asset)

   slow_mo = processor.set_speed(factor=0.5)    # half-speed slow motion
   time_lapse = processor.set_speed(factor=4.0) # 4× timelapse

   slowed = slow_mo(video_asset)

The ``atempo`` filter is chained automatically for extreme factors outside
the ``[0.5, 2.0]`` range.

**normalize_audio** — loudness-normalize to a target LUFS level (EBU R128):

.. code-block:: python

   # Broadcast standard: −23 LUFS
   normalize = processor.normalize_audio(target_lufs=-23.0)
   normalized = normalize(asset)

Uses a two-pass FFmpeg ``loudnorm`` filter for accurate linear correction.

**overlay** — burn a static image or time-bounded graphic onto a video:

.. code-block:: python

   # Watermark in the bottom-right corner, visible only for the first 5 s
   burn_in = processor.overlay(
       overlay_asset=logo,
       gravity='south_east',
       to_seconds=5.0,
   )
   watermarked = burn_in(video_asset)

**thumbnail_sprite** — extract evenly-spaced frames into a sprite sheet:

.. code-block:: python

   # 5×4 grid of 160×90 px thumbnails
   make_sprite = processor.thumbnail_sprite(
       columns=5, rows=4,
       thumb_width=160, thumb_height=90,
   )
   sheet = make_sprite(video_asset)

   # sheet.sprite contains: columns, rows, thumb_width, thumb_height,
   # interval_seconds — enough to generate a WebVTT thumbnail track.

**to_hls / to_dash** — package a video for adaptive HTTP streaming:

.. code-block:: python

   from madam.streaming import DirectoryOutput

   output = DirectoryOutput('/var/www/streams/video1')
   processor.to_hls(video_asset, output, segment_duration=6)
   # Writes: index.m3u8 + segment_000.ts, segment_001.ts, …

   output = DirectoryOutput('/var/www/streams/video1')
   processor.to_dash(video_asset, output, segment_duration=4)
   # Writes: manifest.mpd + media segment files

Both methods accept optional ``video`` and ``audio`` dicts with ``codec`` and
``bitrate`` keys, using the same :class:`~madam.video.VideoCodec` /
:class:`~madam.audio.AudioCodec` constants.


New: ``concatenate`` function
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

:func:`madam.ffmpeg.concatenate` (also importable from :mod:`madam.audio` and
:mod:`madam.video`) joins an iterable of audio or video assets end-to-end
into a single asset.  By default streams are copied without re-encoding:

.. code-block:: python

   from madam.video import concatenate, VideoCodec
   from madam.audio import AudioCodec

   # Fast stream copy when all clips share the same codec
   result = concatenate(
       [intro, main_clip, outro],
       mime_type='video/mp4',
   )

   # Force re-encoding when clips use different codecs
   result = concatenate(
       clips,
       mime_type='video/mp4',
       video={'codec': VideoCodec.H264},
       audio={'codec': AudioCodec.AAC},
   )

Raises :exc:`ValueError` if the asset list is empty.


New: ``Pipeline.branch`` and ``Pipeline.when``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

:class:`~madam.core.Pipeline` gained two control-flow methods.

**branch** — fan each input asset through several independent sub-pipelines,
yielding one output per sub-pipeline per input:

.. code-block:: python

   from madam.core import Pipeline
   from madam.image import ResizeMode

   processor = madam.get_processor(asset)

   thumbnail_pipe = Pipeline()
   thumbnail_pipe.add(processor.resize(width=150, height=150, mode=ResizeMode.FILL))

   preview_pipe = Pipeline()
   preview_pipe.add(processor.resize(width=800, height=600, mode=ResizeMode.FIT))

   pipeline = Pipeline()
   pipeline.branch(thumbnail_pipe, preview_pipe)

   for asset in pipeline.process(*originals):
       # yields 2 × len(originals) assets: thumbnail and preview for each
       manager.write(asset, open(f'out_{asset.width}.jpg', 'wb'))

**when** — apply one operator when a predicate returns ``True``, another
when it returns ``False`` (optional):

.. code-block:: python

   pipeline = Pipeline()
   pipeline.when(
       predicate=lambda a: a.width > 1920,
       then=processor.resize(width=1920, height=1080, mode=ResizeMode.FIT),
   )
   # Assets narrower than 1920 px pass through unchanged.

   # With an else_ branch:
   pipeline.when(
       predicate=lambda a: a.mime_type == 'image/png',
       then=processor.convert(mime_type='image/webp'),
       else_=processor.convert(mime_type='image/jpeg'),
   )


----


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
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

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
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The private attribute ``_FFmpegProcessor__threads`` (name-mangled) no longer
exists.  It has been replaced by the ``_threads`` property, which evaluates
``multiprocessing.cpu_count()`` fresh on each access so that containerised
deployments that change CPU affinity at runtime are handled correctly.

If you accessed ``processor._FFmpegProcessor__threads`` in your code, update
it to ``processor._threads``.


New features
~~~~~~~~~~~~

New: retry-aware error hierarchy
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

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
^^^^^^^^^^^^^^^^^^^^^^^^^

:class:`~madam.core.Asset` now exposes a ``content_id`` property that returns
a hex-encoded SHA-256 digest of the asset's essence bytes.  Two assets with
identical binary content share the same ``content_id``, making it suitable as
an object-store key or a cache lookup key.

.. code-block:: python

   asset = madam.read(open('photo.jpg', 'rb'))
   print(asset.content_id)
   # 'e3b0c44298fc1c149afb…'

New: ``madam.default_madam`` singleton
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

A module-level lazy singleton is now available for scripts that do not need a
custom configuration:

.. code-block:: python

   import madam
   asset = madam.default_madam.read(open('photo.jpg', 'rb'))

The singleton is created on first access and reused thereafter.

New: ``FFmpegProcessor`` thread count configuration
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The number of threads used by FFmpeg can be capped via the processor config:

.. code-block:: python

   from madam.ffmpeg import FFmpegProcessor
   processor = FFmpegProcessor(config={'ffmpeg': {'threads': 4}})

When unset (or set to ``0``), the default is ``multiprocessing.cpu_count()``.

New: ``LazyAsset``
^^^^^^^^^^^^^^^^^^

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
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

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
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

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
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The following formats are now supported out of the box:

* **Image**: AVIF (read and write via Pillow; default quality 80, speed 6)
* **Audio**: AAC (ADTS), FLAC (read); AAC, FLAC, Opus, WebM audio (encode targets)
* **Video**: MP4 (``video/mp4``), WebM (``video/webm``) as encode targets

New: ``VideoCodec`` and ``AudioCodec`` constant classes
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

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

