import pytest

from exiv2 import Exiv2Processor


class TestExiv2Processor:
    @pytest.fixture(name='processor')
    def exiv2_processor(self):
        return Exiv2Processor()

    def test_format_is_exif(self, processor):
        assert processor.format == 'exif'
