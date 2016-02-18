from adam.adam import *

def test_asset_can_be_retrieved():
    storage = AssetStorage()
    a = Asset()
    storage['key'] = a
    assert storage['key'] == a
    
def test_contains_asset():
    storage = AssetStorage()
    a = Asset()
    assert 'key' not in storage
    storage['key'] = a
    assert 'key' in storage