class MimeType:
    type = None
    subtype = None

    def __init__(self, type, subtype=None):
        if type:
            self.type = str(type).lower()
        if subtype:
            self.subtype = str(subtype).lower()
