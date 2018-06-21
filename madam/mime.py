class MimeType:
    type = None
    subtype = None

    def __init__(self, type, subtype=None):
        if type and type != '*':
            self.type = str(type).lower()
        if subtype and subtype != '*':
            self.subtype = str(subtype).lower()
