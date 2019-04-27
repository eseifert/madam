Overview
########

Main registry
=============

The class :class:`madam.core.Madam` manages the extensions that can be used to
process different file formats. It provides convenience methods to read and to
write files.


Media assets
============

At the core of MADAM are **assets** in the form of :class:`madam.core.Asset`
objects. Asset objects are immutable and provide access the raw data via the
file-like attribute ``essence`` and to the metadata via the dictionary
``metadata``.


Processors
==========

The extensions used to read, process, and write file formats are called
**processors**. Usually, they are interfaces to external libraries that are
used in the background to do all the heavy lifting. There are two types of
processors in MADAM:

Essence processors (or just processors)
    Represented by :class:`madam.core.Processor` objects. Essence processors
    are responsible to read and write the actual data in a specific file
    format. They also offer various operations that can be performed to modify
    the data, e.g. to resize or to rotate an image. One implementation of this
    interface is the :class:`madam.image.PillowProcessor` class.

Metadata processors
    Represented by :class:`madam.core.MetadataProcessor` objects.
    Metadata processors are responsible to read and write metadata only.
    Prominent examples of such metadata could be ID3 in MP3 audio files, or
    Exif in JPEG images. For example, the implementation for Exif metadata is
    the :class:`madam.exif.ExifMetadataProcessor` class.


Operators
=========

Essence processors provide methods to modify assets, which are called
**operators**. As operations are usually performed on many media assets,
operators are implemented as partial methods that can be pre-configured and
then applied to one or many assets.

.. note:: Operators can raise exceptions of the type
    :class:`madam.core.OperatorError` if something goes wrong.


Pipelines
=========

The utility class :class:`madam.core.Pipeline` makes it easy to apply a
sequence of operators to one or many assets.

.. code:: python

    portrait_pipeline = Pipeline()
    portrait_pipeline.add(processor.resize(width=300, height=300, mode=ResizeMode.FIT))
    portrait_pipeline.add(processor.sharpen())

    for processed_asset in portrait_pipeline.process(*portrait_assets):
        with open(processed_asset.filename, 'wb') as file:
            file.write(processed_asset.essence.read())


Storage
=======

In MADAM, media assets are organized using modular **storage backends**.
Backends have to subclass :class:`madam.core.AssetStorage` and behave like
Python dictionaries. It will store a media asset together with its metadata and
a set of tags using a unique key. The basic expression to store an asset would
be ``backend[asset_key] = asset, tags``. Here is a short explanation of the
elements in this expression:

-   **asset_key** is a unique value. Its data type depends on the storage
    backend.

-   The **asset** is an :class:`madam.core.Asset` object with essence and
    metadata.

-   The set **tags** stores strings that can be used to filter assets.

Storage bakends also support filtering of assets by metadata or tags with the
methods :func:`madam.core.AssetStorage.filter` and
:func:`madam.core.AssetStorage.filter_by_tags`.


.. note:: Two basic backend implementations are provided:

    -   :class:`madam.core.InMemoryStorage` uses a Python dictionary to store
        assets
    -   :class:`madam.core.ShelveStorage` uses Python :mod:`shelve` module to
        store a serialized version of all assets and tags on disk
