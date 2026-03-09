Configuration
#############

Setting default format options
==============================

MADAM has several configuration options that can modify the default settings
used when writing file formats.  The configuration is a dictionary passed to
:func:`madam.core.Madam.__init__`.  The structure of the dict depends on the
file type category (image, video, etc.).

A configuration option set under the broad media type key (e.g. ``'image'``)
applies to all formats of that type.  A more specific MIME-type key (e.g.
``'image/jpeg'``) overrides the broad setting for that format only:

.. code:: pycon

    >>> config = {
    ...     'image': {'quality': 80},          # applies to all image formats
    ...     'image/jpeg': {'progressive': True, 'quality': 85},  # JPEG override
    ... }
    >>> from madam import Madam
    >>> madam = Madam(config)

.. warning::

   :class:`~madam.image.PillowProcessor` emits a :exc:`UserWarning` when it
   encounters an unknown configuration key for a given format.  Check your
   configuration dict carefully if you see these warnings at startup.


Image options
=============

Image settings can be stored for all image formats or for a specific MIME type.

The following example sets a quality default for all image formats and enables
Zopfli compression for PNG specifically:

.. code:: pycon

    >>> config = {
    ...     'image': {
    ...         'quality': 80,
    ...     },
    ...     'image/png': {
    ...         'zopfli': True,
    ...     },
    ... }

The following list documents all available per-format options.

AVIF (image/avif)
-----------------
quality
    A compression factor as an integer in the range between 0 and 100. Smaller
    factors produce smaller files with lower quality.

    Defaults to 80.

speed
    An integer in the range between 0 and 10 that controls the encode speed/
    quality trade-off. 0 is the slowest and produces the best compression; 10
    is the fastest and produces the largest files at the same quality level.

    Defaults to 4.

    .. tip::

        For batch processing or CI pipelines where encode time matters more than
        file size, raise this to 6 or higher::

            config = {'image/avif': {'speed': 8}}


JPEG (image/jpeg)
-----------------
progressive
    A boolean value that defines whether progressive JPEG images should be
    written.  Progressive JPEGs appear to load gradually in browsers, which
    feels faster on slow connections.

    Defaults to True.

quality
    A compression factor as an integer in the range between 0 and 100. Smaller
    factors produce smaller files with lower quality.

    Defaults to 80.

subsampling
    Controls chroma subsampling.  ``2`` uses 4:2:0 (default Pillow behaviour
    for photographic content), ``1`` uses 4:2:2, and ``0`` uses 4:4:4 (no
    chroma subsampling).

    When unset the Pillow default (4:2:0) is used.

    .. tip::

        Use ``subsampling=0`` for images that contain sharp text, line art, or
        vivid solid colours, where 4:2:0 can cause visible colour fringing::

            config = {'image/jpeg': {'subsampling': 0, 'quality': 85}}


PNG (image/png)
---------------
zopfli
    Boolean that defines whether Zopfli should be used to further compress PNG
    images. Requires the ``optimize`` extra (``pip install "madam[optimize]"``).

    Defaults to False.

    .. warning::

        Enabling Zopfli can increase processing times dramatically depending on
        the input data.

zopfli_strategies
    String that lists all filter strategies to try when saving PNG images:

    -   0–4: Apply PNG filter type 0 to 4 to scanlines
    -   m: Minimum sum
    -   e: Entropy
    -   p: Predefined
    -   b: Brute force

    Defaults to '0me'.

WebP (image/webp)
-----------------
method
    An integer in the range between 0 and 6 that defines the quality/speed
    trade-off when optimizing WebP images. 0 means faster compression but
    larger files, 6 means slower compression but smaller files.

    Defaults to 6.

quality
    A compression factor as an integer in the range between 0 and 100.
    Smaller factors produce smaller files with lower quality.

    Defaults to 80.


GIF (image/gif)
---------------
optimize
    Boolean that defines whether Pillow should try to optimize the palette and
    frame order when saving animated GIF images.

    Defaults to ``True``.

TIFF (image/tiff)
-----------------
compression
    String specifying the TIFF compression algorithm.  Common values:
    ``'tiff_deflate'`` (lossless), ``'tiff_lzw'`` (lossless), ``'jpeg'``
    (lossy), or ``'raw'`` (no compression).

    Defaults to ``'tiff_deflate'``.


Video options
=============

Video content is split into two categories: container options are stored by
MIME type, and codec options are stored under a separate ``'codec/<name>'``
key.

The following example tightens quality for H.265 and caps FFmpeg's thread
count to 4:

.. code:: pycon

    >>> config = {
    ...     'codec/libx265': {
    ...         'crf': 22,
    ...     },
    ...     'ffmpeg': {'threads': 4},
    ... }

When ``ffmpeg.threads`` is ``0`` or absent, MADAM uses
``multiprocessing.cpu_count()`` threads by default.

The following list documents all available options for video containers.

MP4 (video/mp4) and QuickTime (video/quicktime)
------------------------------------------------
faststart
    Boolean that defines whether the ``moov`` atom is moved to the beginning of
    the file so that playback can start before the entire file is downloaded.
    This is required for progressive web delivery and HTTP streaming — leave it
    enabled for any content served over the web.

    Defaults to ``True``.

    .. tip::

        Disable faststart only for files that are always downloaded in full
        before playback (e.g. local archives), where the extra seek saved by
        faststart has no benefit::

            config = {'video/mp4': {'faststart': False}}

Matroska / MKV (video/x-matroska)
----------------------------------
There are no user-configurable container options for Matroska.  The encoder
automatically sets ``-avoid_negative_ts make_zero`` to prevent timestamp
issues when muxing streams from multiple sources.

The following list shows all available options for video codecs.

AVC/H.264 (libx264)
-------------------
crf
    An integer that defines the Constant Rate Factor (CRF) for quality and
    rate control. 0 encodes to lossless quality; 51 produces the smallest but
    worst-looking output.  A sane range for H.264 is between 18 and 28.

    Defaults to 22.

    .. note::

        MADAM encodes H.264 with ``preset=medium``, ``pix_fmt=yuv420p``,
        ``profile:v=high``, and ``level:v=4.1`` by default.  These settings
        maximise compatibility with browsers, mobile devices, and streaming
        platforms.  They are not currently user-configurable.

    .. tip::

        Lower the CRF for archival masters or content with a lot of fine
        detail; raise it when bandwidth or storage is the priority::

            # Archival quality
            config = {'codec/libx264': {'crf': 18}}

            # Small file size for previews
            config = {'codec/libx264': {'crf': 28}}

HEVC/H.265 (libx265)
--------------------
crf
    An integer that defines the Constant Rate Factor (CRF) for quality and
    rate control. 0 encodes to lossless quality; 51 produces the smallest but
    worst-looking output.  A sane range for H.265 is between 18 and 28.

    Defaults to 26.

    .. note::

        MADAM encodes H.265 with ``preset=medium``, ``pix_fmt=yuv420p``, and
        ``tag:v=hvc1`` by default.  The ``hvc1`` tag is required for Safari and
        iOS to play H.265 video in MP4 containers.  These settings are not
        currently user-configurable.

    .. tip::

        H.265 achieves roughly the same visual quality as H.264 at about half
        the bitrate.  Use it when storage or bandwidth is critical and broad
        legacy-device support is not required::

            # Equivalent perceived quality to H.264 crf=22:
            config = {'codec/libx265': {'crf': 26}}

VP8 (libvpx)
------------
crf
    An integer that defines the Constant Rate Factor (CRF) for quality and
    rate control. 0 encodes very slowly to lossless quality; 63 encodes very
    fast to the worst quality.  A sane range for VP8 is between 4 and 63.

    Defaults to 10.

VP9 (libvpx-vp9)
----------------
crf
    An integer that defines the Constant Rate Factor (CRF) for quality and
    rate control. 0 encodes very slowly to lossless quality; 63 encodes very
    fast to the worst quality.  A sane range for VP9 is between 15 and 44.

    Defaults to 33.

    .. note::

        MADAM enables true constant-quality mode (``-b:v 0 -crf N``) and sets
        ``tile-columns=2`` and ``cpu-used=2`` by default.  Without ``-b:v 0``
        the CRF value is silently ignored by FFmpeg and VP9 falls back to
        variable bitrate mode; MADAM prevents this automatically.
        ``cpu-used=2`` is the VOD sweet spot — it is 3-4× faster than the
        default (0) with minimal quality loss.  These settings are not
        currently user-configurable.

    .. tip::

        VP9 is the open-source alternative to H.265.  Use it when you need
        good compression without patent-encumbered codecs (e.g. for WebM
        delivery in browsers)::

            convert = processor.convert(
                mime_type='video/webm',
                video={'codec': 'libvpx-vp9'},
                audio={'codec': 'libopus'},
            )
