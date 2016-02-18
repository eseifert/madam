def test_identical_assets_have_different_id():
    storage = AssetStorage()
    a = Asset()
    b = Asset()
    storage.add(a, b)
    assert(a.id != b.id)