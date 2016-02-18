class AssetStorage:
    def __init__(self):
        self.assets = {}
        
    def __setitem__(self, id, asset):
        self.assets[id] = asset
        
    def __getitem__(self, id):
        return self.assets[id]
    
    def __contains__(self, id):
        return id in self.assets
        
class Asset:
    def __init__(self):
        pass