"""Tests for madam.streaming (MultiFileOutput, ZipOutput, DirectoryOutput)."""

import io
import zipfile
from pathlib import Path

from madam.streaming import DirectoryOutput, ZipOutput


class TestZipOutputContextManager:
    def test_context_manager_produces_valid_zip(self):
        buf = io.BytesIO()
        with ZipOutput(buf) as output:
            output.write('hello.txt', b'hello world')

        buf.seek(0)
        with zipfile.ZipFile(buf) as zf:
            assert 'hello.txt' in zf.namelist()
            assert zf.read('hello.txt') == b'hello world'

    def test_context_manager_calls_close(self):
        buf = io.BytesIO()
        with ZipOutput(buf) as output:
            output.write('a.bin', b'\x00\x01')

        buf.seek(0)
        assert zipfile.is_zipfile(buf)

    def test_multiple_files_in_zip(self):
        buf = io.BytesIO()
        with ZipOutput(buf) as output:
            output.write('seg0.ts', b'segment0')
            output.write('seg1.ts', b'segment1')
            output.write('index.m3u8', b'#EXTM3U\n')

        buf.seek(0)
        with zipfile.ZipFile(buf) as zf:
            assert set(zf.namelist()) == {'seg0.ts', 'seg1.ts', 'index.m3u8'}


class TestDirectoryOutput:
    def test_write_creates_file(self, tmp_path):
        output = DirectoryOutput(tmp_path)
        output.write('output.bin', b'\xde\xad\xbe\xef')

        assert (tmp_path / 'output.bin').read_bytes() == b'\xde\xad\xbe\xef'

    def test_write_creates_subdirectory(self, tmp_path):
        output = DirectoryOutput(tmp_path)
        output.write('sub/dir/file.txt', b'data')

        assert (tmp_path / 'sub' / 'dir' / 'file.txt').read_bytes() == b'data'

    def test_context_manager_returns_self(self, tmp_path):
        output = DirectoryOutput(tmp_path)
        with output as ctx:
            assert ctx is output

    def test_context_manager_write(self, tmp_path):
        with DirectoryOutput(tmp_path) as output:
            output.write('hello.txt', b'hello')

        assert (tmp_path / 'hello.txt').exists()

    def test_accepts_path_object(self, tmp_path):
        output = DirectoryOutput(Path(tmp_path))
        output.write('test.bin', b'bytes')

        assert (tmp_path / 'test.bin').exists()
