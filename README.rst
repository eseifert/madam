MADAM
#####

Multimedia Advanced Digital Asset Management

|travis-badge|_ |coveralls-badge|_ |pypi-badge|_ |readthedocs-badge|_

.. |travis-badge| image:: https://api.travis-ci.org/eseifert/madam.svg?branch=master
.. _travis-badge: https://travis-ci.org/eseifert/madam
.. |coveralls-badge| image:: https://coveralls.io/repos/github/eseifert/madam/badge.svg?branch=master
.. _coveralls-badge: https://coveralls.io/github/eseifert/madam?branch=master
.. |pypi-badge| image:: https://img.shields.io/pypi/v/madam.svg?
.. _pypi-badge: https://pypi.python.org/pypi/MADAM
.. |readthedocs-badge| image:: https://readthedocs.org/projects/madam/badge/?version=latest
.. _readthedocs-badge: http://madam.readthedocs.io/en/latest/?badge=latest

MADAM is a digital asset management library. It aims to facilitate the handling
of image, audio, and video files by helping out with several tasks, like
storing, organizing, and transforming asset data.

.. quickstart_start

Installation
============
MADAM makes use of other software, which needs to be installed on your system. Make sure you have the following packages installed:

    - FFmpeg >=0.9
    - libexiv2 >=0.20 (with header files)
    - boost.python >=1.48 (with header files)

After you installed these, MADAM can be installed by grabbing the latest release from PyPI:

.. code:: shell

    pip install madam


Usage
=====

Initialization:

.. code:: pycon

    >>> from madam import Madam
    >>> manager = Madam()

Reading a JPEG image and extracting metadata:

.. code:: pycon

    >>> with open('path/to/file.jpg', 'rb') as file:
    ...     asset = manager.read(file)
    >>> asset.mime_type
    'image/jpeg'
    >>> asset.width
    800
    >>> asset.height
    600

Changing the size of an image asset:

.. code:: pycon

    >>> processor = manager.get_processor(asset.essence)
    >>> make_thumbnail = processor.resize(width=100, height=100)
    >>> resized_asset = make_thumbnail(asset)
    >>> resized_asset.width
    100
    >>> resized_asset.height
    100

Converting an image to a different file format and saving it to a file:

.. code:: pycon

    >>> convert_to_png = processor.convert(mime_type='image/png')
    >>> png_asset = convert_to_png(asset)
    >>> with open('path/to/file.png', 'wb') as file:
    ...     madam.write(png_asset, file)
