Configuration
#############

Setting default format options
==============================

MADAM has several configuration options that can modify the default settings
which are used to write file formats. The configuration is stored in a
dictionary that can be passed to :func:`madam.core.Madam.__init__`. The
structure of the dict depends on the file type category (e.g. audio, image, or
video).


Image options
=============

Image settings can be stored for all image formats or for a certain MIME type.

The following example shows how to set the quality factor for all images and
how to enable Zopfli compression for PNG images:

.. code:: pycon

    >>> config = {
    ...     'image': {
    ...         'quality': 80,
    ...     },
    ...     'image/png': {
    ...         'zopfli': True,
    ...     },
    ... }

The following list shows all available options for file formats.

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
    images.

    Defaults to True.

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


Video options
=============

Video content is split in two categories: Container options are stored by MIME
type and codec options are stored in a separate MIME type category ``codec``.

The following example shows how to set the Constant Rate Factor (CRF) for the
h.264 codec (using ``libx265``):

.. code:: pycon

    >>> config = {
    ...     'video/quicktime': {
    ...         'faststart': True,
    ...     },
    ...     'codec/libx265': {
    ...         'crf': 24,
    ...     },
    ... }

The following list shows all available options for video containers.

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
