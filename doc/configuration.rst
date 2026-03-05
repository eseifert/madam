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
    quality trade-off. 0 is the slowest and highest-quality setting; 10 is the
    fastest and lowest-quality setting.

    Defaults to 6.


JPEG (image/jpeg)
-----------------
progressive
    A boolean value that defines whether progressive JPEG images should be
    written.

    Defaults to True.

quality
    A compression factor as an integer in the range between 0 and 100. Smaller
    factors produce smaller files with lower quality.

    Defaults to 80.


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

The following example sets the ``faststart`` flag for QuickTime/MPEG-4
containers and lowers the CRF for h.265 encoding:

.. code:: pycon

    >>> config = {
    ...     'video/quicktime': {
    ...         'faststart': True,
    ...     },
    ...     'codec/libx265': {
    ...         'crf': 24,
    ...     },
    ... }

To cap the number of threads used by FFmpeg, add an ``'ffmpeg'`` key:

.. code:: pycon

    >>> config = {
    ...     'ffmpeg': {'threads': 4},
    ... }

When ``threads`` is ``0`` or absent, MADAM uses ``multiprocessing.cpu_count()``
threads by default.

The following list documents all available options for video containers.

Quicktime/MPEG4 (video/quicktime)
---------------------------------
faststart
    Boolean that defines whether the video and audio files should be written in
    a way that allows a fast start when streaming.

    Defaults to True.

The following list shows all available options for video codecs.

AVC/h.264 (libx264)
-------------------
crf
    An integer that defines the Constant Rate Factor (CRF) for quality and
    rate control in videos. 0 would encode slowly to lossless quality, while 51
    would encode fast to the worst quality. A sane range for AVC/h.264 is
    between 18 and 28.

    Defaults to 23.

HEVC/h.265 (libx265)
--------------------
crf
    An integer that defines the Constant Rate Factor (CRF) for quality and
    rate control in videos. 0 would encode slowly to lossless quality, while 51
    would encode fast to the worst quality. A sane range for HEVC/h.265 is
    between 18 and 28.

    Defaults to 28.

VP8 (libvpx)
------------
crf
    An integer that defines the Constant Rate Factor (CRF) for quality and
    rate control in videos. 0 would encode very slowly to lossless quality,
    while 63 would encode very fast to the worst quality. A sane range for VP8
    is between 4 and 63.

    Defaults to 10.

VP9 (libvpx-vp9 or vp9)
-----------------------
crf
    An integer that defines the Constant Rate Factor (CRF) for quality and
    rate control in videos. 0 would encode very slowly to lossless quality,
    while 63 would encode very fast to the worst quality. A sane range for VP9
    is between 4 and 63.

    Defaults to 32.
