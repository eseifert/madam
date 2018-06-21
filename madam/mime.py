class MimeType:
    type = None
    subtype = None

    def __init__(self, type, subtype=None):
        if isinstance(type, str) and '/' in type:
            type, subtype = type.split('/')
        if type and type != '*':
            self.type = str(type).lower()
        if subtype and subtype != '*':
            self.subtype = str(subtype).lower()

    def __str__(self):
        return '/'.join((self.type or '*',self.subtype or '*'))

    def __hash__(self):
        return hash((self.type, self.subtype))

    def __eq__(self, other):
        if isinstance(other, MimeType):
            return self.type == other.type and self.subtype == other.subtype
        return NotImplemented
