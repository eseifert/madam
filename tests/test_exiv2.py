import pytest

from exiv2 import Exiv2Processor


@pytest.fixture(name='processor')
def exiv2_processor():
    return Exiv2Processor()


def test_format_is_exif(processor):
    assert processor.format == 'exif'
