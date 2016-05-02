from .core import read
from .core import read_method_by_mime_type
from .audio import readMp3, readWav

supported_mime_types = read_method_by_mime_type.keys()
