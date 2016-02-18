from adam.adam import *

def test_contains_asset():
    storage = AssetStorage()
    a = Asset()
    storage['key'] = a
    assert storage['key'] == a
    
def test_contains_key():
    storage = AssetStorage()
    a = Asset()
    assert 'key' not in storage
    storage['key'] = a
    assert 'key' in storage
    
def test_asset_is_versioned():
    storage = AssetStorage()
    a = Asset()
    updated_a = Asset()
    storage['key'] = a
    storage['key'] = updated_a
    versions = storage.versions_of('key')
    assert len(versions) == 2
    assert versions[0] == a
    assert versions[1] == updated_a

def test_asset_is_deleted():
    storage = AssetStorage()
    a = Asset()
    storage['key'] = a
    del storage['key']
    assert 'key' not in storage