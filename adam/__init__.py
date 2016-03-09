from .core import read, readMp3, readWav
from .core import read_method_by_mime_type

supported_mime_types = read_method_by_mime_type.keys()
