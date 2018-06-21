from functools import total_ordering

@total_ordering
class MimeType:
    type = None
    subtype = None

    def __init__(self, type, subtype=None):
        if not isinstance(type, str) and type is not None:
            raise TypeError('MIME type can only store strings or None')
        if type:
            delimiter_count = type.count('/')
            if delimiter_count:
                if subtype is not None:
                    raise ValueError('Cannot pass MIME type string and subtype string')
                if delimiter_count > 1:
                    raise ValueError('Too many delimiters in %r' % type)
                type, subtype = type.split('/')
            if type != '*':
                self.type = str(type).lower()
        if subtype:
            if subtype != '*':
                if '/' in subtype:
                    raise ValueError('Subtype cannot contain delimiters')
                self.subtype = str(subtype).lower()

    def __str__(self):
        return '/'.join((self.type or '*',self.subtype or '*'))

    def __hash__(self):
        return hash((self.type, self.subtype))

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
