"""
Multi-file output abstractions for segmented media formats (HLS, DASH).

These classes provide a consistent interface for writing a collection of
related files (segments, manifests) to different storage backends without
the caller needing to know where the data ends up.

Usage example::

    import io
    from madam.streaming import ZipOutput

    buf = io.BytesIO()
    with ZipOutput(buf) as output:
        processor.to_hls(video_asset, output=output)
    buf.seek(0)
    # buf now contains a zip archive with all HLS files.
"""

from __future__ import annotations

import abc
import os
import zipfile
from typing import IO


class MultiFileOutput(abc.ABC):
    """Abstract sink for multi-file media output (HLS segments, DASH chunks, etc.).

    Implementations must be usable as context managers.  The ``write``
    method is called once per output file with a relative path and the
    file's raw bytes.
    """

    @abc.abstractmethod
    def write(self, relative_path: str, data: bytes) -> None:
        """Write *data* to *relative_path* within this output.

        :param relative_path: Relative path of the file (forward-slash
            separated; no leading slash)
        :type relative_path: str
        :param data: Raw file contents
        :type data: bytes
        """

    def __enter__(self) -> MultiFileOutput:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        """Finalize and flush the output.  Called automatically by the context manager."""


class DirectoryOutput(MultiFileOutput):
    """Writes each file to a directory on the local filesystem.

    The directory must already exist.

    :param path: Destination directory path
    :type path: str or os.PathLike
    """

    def __init__(self, path: str | os.PathLike) -> None:
        self._path = os.fspath(path)

    def write(self, relative_path: str, data: bytes) -> None:
        dest = os.path.join(self._path, relative_path)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, 'wb') as fh:
            fh.write(data)


class ZipOutput(MultiFileOutput):
    """Writes each file as a zip entry into a file-like object.

    Useful for in-memory testing and for download APIs that stream a
    zip archive containing all HLS or DASH output files.

    :param file: Writable binary file-like object that will receive the
        zip archive
    :type file: IO[bytes]
    """

    def __init__(self, file: IO[bytes]) -> None:
        self._file = file
        self._entries: dict[str, bytes] = {}

    def write(self, relative_path: str, data: bytes) -> None:
        self._entries[relative_path] = data

    def close(self) -> None:
        """Write all accumulated entries into the zip archive and finalize it."""
        with zipfile.ZipFile(self._file, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
            for relative_path, data in self._entries.items():
                zf.writestr(relative_path, data)
