from functools import total_ordering
from typing import Optional, Union


@total_ordering
class MimeType:
    """
    Represents a MIME type according to RFC 2045. This class behaves identical
    to its string representation in ``dict`` and ``set``.

    Limitations:

    - Suffixes are considered a part of the subtype
    - Parameters like ``charset`` are not supported and will be treated as part
      of the subtype
    """
    __slots__ = 'type', 'subtype'

    def __init__(self, mediatype: Optional[Union[str, 'MimeType']], subtype: Optional[str] = None):
        """
        Initializes a new MIME type with either

        - both, *media type* and *subtype* strings
        - a complete MIME type string like ``'audio/opus'``
        - another ``MimeType`` object

        :param mediatype: Can define either the media type, or the complete MIME
            type by passing a MIME type string or another ``MimeType`` instance.
        :type mediatype: str or MimeType or None
        :param subtype: Defines the subtype.
        :type subtype: str or None
        """
        self.type = None
        self.subtype = None
        if isinstance(mediatype, MimeType):
            if subtype is not None:
                raise ValueError('Cannot pass MimeType object and subtype string for initialization.')
            self.type = mediatype.type
            self.subtype = mediatype.subtype
        elif isinstance(mediatype, str):
            if mediatype:
                delimiter_count = mediatype.count('/')
                if delimiter_count:
                    if subtype is not None:
                        raise ValueError('Cannot pass MIME type string and subtype string for initialization.')
                    if delimiter_count > 1:
                        raise ValueError(f'Too many delimiters in {mediatype!r}')
                    mediatype, subtype = mediatype.split('/')
                if mediatype != '*':
                    self.type = str(mediatype).lower()
        elif mediatype is not None:
            raise TypeError(f'{type(mediatype).__qualname__!r} type is not allowed for initialization of MIME type')

        if isinstance(subtype, str):
            if subtype and subtype != '*':
                if '/' in subtype:
                    raise ValueError('Subtype cannot contain delimiters')
                self.subtype = str(subtype).lower()
        elif subtype is not None:
            raise TypeError(f'{type(subtype).__qualname__!r} type is not allowed for initialization of MIME subtype')

    def __str__(self) -> str:
        return '/'.join((self.type or '*', self.subtype or '*'))

    def __repr__(self) -> str:
        return f'{self.__class__.__qualname__}(mediatype={self.type!r}, subtype={self.subtype!r})'

    def __hash__(self) -> int:
        return hash(str(self))

    def __eq__(self, other: object) -> bool:
        if isinstance(other, str):
            return self == MimeType(other)
        if isinstance(other, MimeType):
            return self.type == other.type and self.subtype == other.subtype
        return NotImplemented

    def __lt__(self, other: object) -> bool:
        if isinstance(other, str):
            return self < MimeType(other)
        if isinstance(other, MimeType):
            if self.type == other.type:
                if self.subtype == other.subtype:
                    return False
                else:
                    if self.subtype is None:
                        return True
                    return str(self.subtype) < str(other.subtype)
            else:
                if self.type is None:
                    return True
                return str(self.type) < str(other.type)
        return NotImplemented
