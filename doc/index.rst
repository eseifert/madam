Welcome to MADAM
================

MADAM is a digital asset management library. It aims to facilitate the handling
of image, audio, and video files by helping out with several tasks:

-   **Processing:** MADAM has a very extensible processing architecture.
    With the various operators offered by MADAM, for example, images can be
    optimized for display on mobile devices by resizing them, converting them
    to a different file format, or sharpening them.

-   **Organization:** MADAM helps you to organize media data by customizable
    backends to read and store media files. Once the files are stored, the
    backend can be queried based on the metadata that is present in the media
    files (e.g. XMP, Exif, …) or based on derived properties such as file size
    or the duration of a sound file.

The :doc:`overview` section will give an introduction to the concepts and
vocabulary used in MADAM. If you rather want to get started immediately, have a
look at the :doc:`quickstart` section.


File format support
===================

MADAM supports a wide range of file formats for video, image, and audio data.
This is achieved by using several external open source libraries. `Pillow`_
and `exiv2`_ (for metadata) are used to read, process, or write image files.
`FFmpeg`_ is used to read, process, or write audio and video files.

The support of file formats heavily depends on the configuration of your local
system. The formats shown in the following list should be available on most
configurations. However, it represents only a fraction of the formats supported
by the underlying libraries.

Audio:
    -   MP3
    -   OGG
    -   WAV / RIFF WAVE

Image:
    -   PNG
    -   JPEG / JFIF
    -   GIF

Video:
    -   AVI
    -   Matroska (MKV), WebM
    -   MPEG2 transport stream
    -   OGG
    -   Quicktime, MPEG4

Vector graphics:
    -   SVG

Adding support for a new format often just means adding a mapping of the
library format name to a MIME type to one of the existing processors. If you
want to integrate a new library or tool into MADAM, a new
:class:`madam.core.Processor` or :class:`madam.core.MetadataProcessor` will
have to be implemented. See :doc:`overview` section for more details.


Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`


.. _FFmpeg: https://ffmpeg.org/
.. _Pillow: https://python-pillow.org/
.. _exiv2: http://www.exiv2.org/
