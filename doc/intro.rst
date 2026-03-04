Introduction
############

Welcome to MADAM
================

MADAM is a digital asset management library. It aims to facilitate the handling
of image, audio, and video files by helping out with several tasks:

Processing
    MADAM has a very extensible processing architecture. With the various
    operators offered by MADAM, for example, images can be optimized for
    display on mobile devices by resizing them, converting them to a different
    file format, or sharpening them.

Organization
    MADAM helps you to organize media data by customizable backends to read and
    store media files. Once the files are stored, the backend can be queried
    based on the metadata that is present in the media files (e.g. XMP, Exif,
    …) or based on derived properties such as file size or the duration of a
    sound file.

The :doc:`overview` section will give an introduction to the concepts and
vocabulary used in MADAM. If you rather want to get started immediately, have a
look at the :doc:`quickstart` section.


File format support
===================

MADAM supports a wide range of file formats for video, image, audio, and
document data.  This is achieved by using several external open source
libraries.  `Pillow`_ and `piexif`_ (for EXIF metadata) are used to read,
process, or write raster image files.  `FFmpeg`_ is used to read, process, or
write audio and video files.  Additional optional libraries extend support to
HEIC/HEIF, PDF, raw camera formats, and more.

.. note:: The support of file formats heavily depends on the configuration of
    your local system.  The formats shown in the following list should be
    available on most configurations.  However, they represent only a fraction
    of the formats supported by the underlying libraries.

Audio
    -   AAC (ADTS)
    -   FLAC
    -   MP3
    -   OGG / Opus
    -   WAV / RIFF WAVE
    -   WebM (audio-only)

Image
    -   AVIF
    -   BMP
    -   GIF (including animated GIF)
    -   HEIC / HEIF *(requires* ``pillow-heif``; install with*
        ``pip install "madam[heif]"``)*
    -   JPEG / JFIF
    -   PNG
    -   Raw camera formats: DNG, CR2, NEF, ARW, and others *(requires*
        ``rawpy`` *and LibRaw; install with* ``pip install "madam[raw]"``)*
    -   TIFF
    -   WebP

Documents
    -   PDF *(read and rasterize individual pages; requires* ``pdf2image`` *and*
        ``pypdf``; *install with* ``pip install "madam[pdf]"``)*

Video
    -   AVI
    -   Matroska (MKV), WebM
    -   MPEG2 transport stream
    -   MPEG4 / MP4
    -   OGG
    -   Quicktime

Vector graphics
    -   SVG

Embedded metadata
    -   EXIF (JPEG, WebP) — via :class:`~madam.exif.ExifMetadataProcessor`
    -   IPTC Application Record 2 (JPEG APP13) — via
        :class:`~madam.iptc.IPTCMetadataProcessor`
    -   XMP (JPEG APP1) — via :class:`~madam.xmp.XMPMetadataProcessor`
    -   ID3 / FFmpeg tags (audio/video) — via
        :class:`~madam.ffmpeg.FFmpegMetadataProcessor`
    -   RDF/Dublin Core (SVG) — via
        :class:`~madam.vector.SVGMetadataProcessor`

Adding support for a new format often just means adding a mapping of the
library format name to a MIME type to one of the existing processors. If you
want to integrate a new library or tool into MADAM, a new
:class:`madam.core.Processor` or :class:`madam.core.MetadataProcessor` will
have to be implemented. See :doc:`overview` section for more details.


.. _FFmpeg: https://ffmpeg.org/
.. _Pillow: https://python-pillow.org/
.. _piexif: https://piexif.readthedocs.io/
