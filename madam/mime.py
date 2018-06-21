from functools import total_ordering


@total_ordering
class MimeType:
    type = None
    subtype = None

    def __init__(self, mediatype, subtype=None):
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
                        raise ValueError('Too many delimiters in %r' % mediatype)
                    mediatype, subtype = mediatype.split('/')
                if mediatype != '*':
                    self.type = str(mediatype).lower()
        elif mediatype is not None:
            raise TypeError('%r type is not allowed for initialization of MIME type' %
                            type(mediatype).__name__)

        if isinstance(subtype, str):
            if subtype and subtype != '*':
                if '/' in subtype:
                    raise ValueError('Subtype cannot contain delimiters')
                self.subtype = str(subtype).lower()
        elif subtype is not None:
            raise TypeError('%r type is not allowed for initialization of MIME subtype' %
                            type(subtype).__name__)

    def __str__(self):
        return '/'.join((self.type or '*', self.subtype or '*'))

    def __repr__(self):
        return '%s(mediatype=%r, subtype=%r)' % (
            self.__class__.__name__, self.type, self.subtype
        )

    def __hash__(self):
        return hash(str(self))

    def __eq__(self, other):
        if isinstance(other, str):
            return self == MimeType(other)
        if isinstance(other, MimeType):
            return self.type == other.type and self.subtype == other.subtype
        return NotImplemented

    def __lt__(self, other):
        if isinstance(other, str):
            return self < MimeType(other)
        if isinstance(other, MimeType):
            if self.type == other.type:
                if self.subtype == other.subtype:
                    return False
                else:
                    if self.subtype is None:
                        return True
                    return self.subtype < other.subtype
            else:
                if self.type is None:
                    return True
                return self.type < other.type
        return NotImplemented
