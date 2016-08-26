MADAM
#####

Multimedia Advanced Digital Asset Management

|travis-badge|_ |coveralls-badge|_

.. |travis-badge| image:: https://api.travis-ci.org/eseifert/madam.svg?branch=master
.. _travis-badge: https://travis-ci.org/eseifert/madam
.. |coveralls-badge| image:: https://coveralls.io/repos/github/eseifert/madam/badge.svg?branch=master
.. _coveralls-badge: https://coveralls.io/github/eseifert/madam?branch=master

MADAM is a digital asset management library. It aims to facilitate the handling
of image, audio, and video files by helping out with several tasks, like
storing, organizing, and transforming asset data.

Usage
=====

Reading a JPEG image and extracting metadata:

.. code:: pycon

    >>> with open('path/to/file.jpg', 'rb') as file:
    ...     asset = madam.read(file)
    >>> asset.mime_type
    'image/jpeg'

Changing the size of an image asset:

.. code:: pycon

    >>> asset.width
    800
    >>> asset.height
    600
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
