MADAM
#####

Multimedia Advanced Digital Asset Management

|ci-badge|_ |codecov-badge|_ |pypi-badge|_ |readthedocs-badge|_

.. |ci-badge| image:: https://github.com/eseifert/madam/actions/workflows/ci.yml/badge.svg?
.. _ci-badge: https://github.com/eseifert/madam/actions/workflows/ci.yml
.. |codecov-badge| image:: https://codecov.io/gh/eseifert/madam/branch/master/graph/badge.svg?token=x0aF4xnSz5
.. _codecov-badge: https://codecov.io/gh/eseifert/madam
.. |pypi-badge| image:: https://img.shields.io/pypi/v/madam.svg?
.. _pypi-badge: https://pypi.python.org/pypi/MADAM
.. |readthedocs-badge| image:: https://readthedocs.org/projects/madam/badge/?version=latest
.. _readthedocs-badge: https://madam.readthedocs.io/en/latest/?badge=latest

MADAM is a digital asset management library.  It aims to facilitate the
handling of image, audio, and video files by helping out with several tasks,
like storing, organizing, and transforming asset data.

.. quickstart_start

Installation
============
MADAM requires Python 3.11 or later and the following system packages:

    - ``FFmpeg`` >=3.3 for audio and video processing

After you have installed these, MADAM can be installed from PyPI::

    pip install madam

Optional extras enable additional format support::

    pip install "madam[analysis]"  # SSIMULACRA2 quality optimization
    pip install "madam[heif]"      # HEIC/HEIF images (requires pillow-heif)
    pip install "madam[optimize]"  # Zopfli PNG compression
    pip install "madam[pdf]"       # PDF rasterization (requires poppler)
    pip install "madam[raw]"       # Raw camera formats (requires LibRaw)
    pip install "madam[all]"       # All of the above


Usage
=====

Initialization
--------------

.. code:: pycon

    >>> from madam import Madam
    >>> madam = Madam()

To set format-specific defaults, pass a configuration dictionary:

.. code:: pycon

    >>> config = {
    ...     'image/jpeg': {'quality': 85},
    ...     'image/webp': {'quality': 80, 'method': 6},
    ... }
    >>> madam = Madam(config)


Reading and inspecting assets
------------------------------

.. code:: pycon

    >>> with open('path/to/photo.jpg', 'rb') as f:
    ...     asset = madam.read(f)
    >>> asset.mime_type
    'image/jpeg'
    >>> asset.width
    4000
    >>> asset.height
    3000
    >>> asset.color_space
    'RGB'
    >>> asset.content_id   # SHA-256 of the essence bytes
    'a3f5c8...'


Reading embedded metadata
--------------------------

``madam.read()`` automatically extracts EXIF, IPTC, and XMP metadata:

.. code:: pycon

    >>> exif = asset.metadata.get('exif', {})
    >>> exif.get('camera.model')
    'Canon EOS 5D Mark III'
    >>> exif.get('focal_length')
    85.0
    >>> exif.get('datetime_original')
    datetime.datetime(2024, 6, 15, 10, 30, 0)
    >>> asset.created_at    # unified ISO 8601 timestamp
    '2024-06-15T10:30:00'


Resizing images
---------------

Operators are configured once and then applied to any number of assets:

.. code:: pycon

    >>> from madam.image import ResizeMode
    >>> processor = madam.get_processor(asset)
    >>> make_thumbnail = processor.resize(width=200, height=200, mode=ResizeMode.FIT)
    >>> thumbnail = make_thumbnail(asset)
    >>> thumbnail.width
    200


Applying image effects
-----------------------

.. code:: pycon

    >>> # Brighten by 20 %, add a warm tint, then apply a vignette
    >>> brighten = processor.adjust_brightness(factor=1.2)
    >>> add_tint = processor.tint(color=(255, 180, 80), opacity=0.2)
    >>> add_vignette = processor.vignette(strength=0.4)
    >>> result = add_vignette(add_tint(brighten(asset)))


Converting format and saving
-----------------------------

.. code:: pycon

    >>> convert_to_webp = processor.convert(mime_type='image/webp')
    >>> webp_asset = convert_to_webp(asset)
    >>> with open('path/to/output.webp', 'wb') as f:
    ...     madam.write(webp_asset, f)


Building a pipeline
--------------------

Use ``Pipeline`` to chain operators and process batches:

.. code:: pycon

    >>> from madam.core import Pipeline
    >>> pipeline = Pipeline()
    >>> pipeline.add(processor.resize(width=800, height=600, mode=ResizeMode.FIT))
    >>> pipeline.add(processor.sharpen(radius=2, percent=120))
    >>> pipeline.add(processor.convert(mime_type='image/jpeg'))
    >>> for processed in pipeline.process(asset_a, asset_b, asset_c):
    ...     with open(f'{processed.content_id}.jpg', 'wb') as f:
    ...         f.write(processed.essence.read())


Audio processing
-----------------

.. code:: pycon

    >>> from madam.audio import AudioCodec
    >>> audio_processor = madam.get_processor(audio)
    >>> with open('track.mp3', 'rb') as f:
    ...     audio = madam.read(f)
    >>> audio.duration          # seconds
    243.7
    >>> audio.metadata['audio']['codec']
    'mp3'
    >>> # Normalize loudness to EBU R128 broadcast standard (−23 LUFS)
    >>> normalize = audio_processor.normalize_audio(target_lufs=-23.0)
    >>> loud_normalized = normalize(audio)
    >>> # Convert to Opus
    >>> to_opus = audio_processor.convert(
    ...     mime_type='audio/ogg',
    ...     audio={'codec': AudioCodec.OPUS, 'bitrate': 128},
    ... )
    >>> opus_asset = to_opus(audio)
    >>> with open('track.opus', 'wb') as f:
    ...     madam.write(opus_asset, f)


Video processing
-----------------

.. code:: pycon

    >>> from madam.video import VideoCodec, concatenate
    >>> video_processor = madam.get_processor(video)
    >>> with open('clip.mp4', 'rb') as f:
    ...     video = madam.read(f)
    >>> video.duration
    30.0
    >>> # Trim to the first 10 seconds
    >>> trim = video_processor.trim(start=0.0, duration=10.0)
    >>> short_clip = trim(video)
    >>> # Create a 4× timelapse
    >>> speed_up = video_processor.set_speed(factor=4.0)
    >>> timelapse = speed_up(video)
    >>> # Concatenate clips
    >>> combined = concatenate([clip_a, clip_b], mime_type='video/mp4')
    >>> # Extract a thumbnail sprite sheet (5 columns × 4 rows, 160×90 px each)
    >>> make_sprite = video_processor.thumbnail_sprite(
    ...     columns=5, rows=4, thumb_width=160, thumb_height=90
    ... )
    >>> sprite = make_sprite(video)


Storing assets
---------------

.. code:: pycon

    >>> from madam.core import InMemoryStorage
    >>> storage = InMemoryStorage()
    >>> storage['hero'] = (asset, {'homepage', 'featured'})
    >>> retrieved_asset, tags = storage['hero']
    >>> # Filter by metadata
    >>> jpegs = list(storage.filter(mime_type='image/jpeg'))
    >>> # Filter by tags
    >>> featured = list(storage.filter_by_tags({'featured'}))
