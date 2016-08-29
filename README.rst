MADAM
#####

Multimedia Advanced Digital Asset Management

|travis-badge|_ |coveralls-badge|_ |pypi-badge|_ |readthedocs-badge|_

.. |travis-badge| image:: https://api.travis-ci.org/eseifert/madam.svg?branch=master
.. _travis-badge: https://travis-ci.org/eseifert/madam
.. |coveralls-badge| image:: https://coveralls.io/repos/github/eseifert/madam/badge.svg?branch=master
.. _coveralls-badge: https://coveralls.io/github/eseifert/madam?branch=master
.. |pypi-badge| image:: https://badge.fury.io/py/madam.svg?
.. _pypi-badge: https://pypi.python.org/pypi/MADAM
.. |readthedocs-badge| image:: https://readthedocs.org/projects/madam/badge/?version=latest
.. _readthedocs-badge: http://madam.readthedocs.io/en/latest/?badge=latest

MADAM is a digital asset management library. It aims to facilitate the handling
of image, audio, and video files by helping out with several tasks, like
storing, organizing, and transforming asset data.

.. quickstart_start

Installation
============
MADAM can be installed by grabbing the latest release from PyPI:

.. code:: shell

    pip install MADAM


External requirements
=====================
The base installation bundles as much functionality as possible. However, support for audio and video data requires FFmpeg v0.9 or higher to be installed on the system.


Usage
=====

Initialization:

.. code:: pycon

    >>> from madam import Madam
    >>> madam = Madam()

Reading a JPEG image and extracting metadata:

.. code:: pycon

    >>> with open('path/to/file.jpg', 'rb') as file:
    ...     asset = madam.read(file)
    >>> asset.mime_type
    'image/jpeg'
    >>> asset.width
    800
    >>> asset.height
    600

Changing the size of an image asset:

.. code:: pycon

    >>> from madam.image import PillowProcessor
    >>> pillow_processor = PillowProcessor()
    >>> make_thumbnail = pillow_processor.resize(width=100, height=100)
    >>> resized_asset = make_thumbnail(asset)
    >>> resized_asset.width
    100
    >>> resized_asset.height
    100

Converting an image to a different file format and saving it to a file:

.. code:: pycon

    >>> convert_to_png = pillow_processor.convert(mime_type='image/png')
    >>> png_asset = convert_to_png(asset)
    >>> with open('path/to/file.png', 'wb') as file:
    ...     madam.write(png_asset, file)
