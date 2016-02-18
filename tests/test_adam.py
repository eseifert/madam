from adam.adam import *

def test_asset_can_be_retrieved():
    storage = AssetStorage()
    a = Asset()
    storage['key'] = a
    assert storage['key'] == a