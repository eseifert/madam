import io
import pickle

import pytest

from madam.core import Asset, LazyAsset


@pytest.fixture
def sample_bytes():
    return b'lazy essence content'


@pytest.fixture
def loader(sample_bytes):
    def _load(uri: str) -> io.IOBase:
        return io.BytesIO(sample_bytes)

    return _load


class TestLazyAsset:
    def test_lazy_asset_can_be_created_with_uri_and_metadata(self, loader):
        asset = LazyAsset('file:///tmp/test.jpg', loader, mime_type='image/jpeg')
        assert asset.uri == 'file:///tmp/test.jpg'

    def test_lazy_asset_metadata_is_accessible_as_attributes(self, loader):
        asset = LazyAsset('file:///tmp/test.jpg', loader, mime_type='image/jpeg', width=100)
        assert asset.width == 100

    def test_lazy_asset_essence_loads_bytes_from_loader(self, loader, sample_bytes):
        asset = LazyAsset('file:///tmp/test.jpg', loader)
        assert asset.essence.read() == sample_bytes

    def test_lazy_asset_essence_is_readable_multiple_times(self, loader, sample_bytes):
        asset = LazyAsset('file:///tmp/test.jpg', loader)
        first = asset.essence.read()
        second = asset.essence.read()
        assert first == second == sample_bytes

    def test_lazy_asset_is_a_subclass_of_asset(self, loader):
        assert issubclass(LazyAsset, Asset)

    def test_lazy_asset_pickle_does_not_include_raw_bytes(self, loader, sample_bytes):
        asset = LazyAsset('file:///tmp/test.jpg', loader, mime_type='image/jpeg')
        pickled = pickle.dumps(asset)
        # Payload must be much smaller than the actual bytes if content were embedded;
        # verify the sample bytes themselves are NOT in the pickle stream.
        assert sample_bytes not in pickled

    def test_lazy_asset_pickle_round_trip_preserves_uri_and_metadata(self, loader):
        original = LazyAsset('file:///tmp/test.jpg', loader, mime_type='image/jpeg', width=800)
        restored = pickle.loads(pickle.dumps(original))
        assert restored.uri == original.uri
        assert restored.mime_type == original.mime_type
        assert restored.width == original.width

    def test_lazy_asset_raises_when_loader_is_none_and_essence_accessed(self):
        asset = LazyAsset('file:///tmp/test.jpg', None)
        with pytest.raises(RuntimeError):
            asset.essence

    def test_lazy_asset_content_id_equals_sha256_of_loaded_bytes(self, loader, sample_bytes):
        import hashlib

        asset = LazyAsset('file:///tmp/test.jpg', loader)
        expected = hashlib.sha256(sample_bytes).hexdigest()
        assert asset.content_id == expected
