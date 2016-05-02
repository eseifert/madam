from .core import read
from .core import read_method_by_mime_type
from .audio import readMp3, readWav
from .image import readJpeg

supported_mime_types = read_method_by_mime_type.keys()
