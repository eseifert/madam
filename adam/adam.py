class AssetStorage:
    def __init__(self):
        self.assets = []
        
    def add(self, *assets):
        for asset in assets:
            asset_count = len(self.assets)
            asset.id = asset_count
            self.assets.append(asset)
        
class Asset:
    def __init__(self):
        pass