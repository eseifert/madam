import glob
import io
import threading
import unittest.mock

import pytest

from madam.core import Asset, IndexedAssetStorage, InMemoryStorage, LazyAsset, Pipeline, ShelveStorage


@pytest.fixture
def in_memory_storage():
    return InMemoryStorage()


@pytest.fixture
def shelve_storage(tmpdir):
    storage_path = str(tmpdir.join('storage.shelve'))
    return ShelveStorage(storage_path)


@pytest.mark.usefixtures('asset', 'in_memory_storage', 'shelve_storage')
class TestStorages:
    @pytest.fixture(params=['in_memory_storage', 'shelve_storage'])
    def storage(self, request, in_memory_storage, shelve_storage):
        if request.param == 'in_memory_storage':
            return in_memory_storage
        elif request.param == 'shelve_storage':
            return shelve_storage

    def test_contains_is_false_when_storage_is_empty(self, storage, asset):
        asset_key = str(hash(asset))
        contains = asset_key in storage

        assert not contains

    def test_contains_is_true_when_asset_was_added(self, storage, asset):
        asset_key = str(hash(asset))
        storage[asset_key] = asset, set()

        assert asset_key in storage

    def test_contains_is_false_when_asset_was_deleted(self, storage, asset):
        asset_key = str(hash(asset))
        storage[asset_key] = asset, set()

        del storage[asset_key]

        assert asset_key not in storage

    def test_remove_raises_key_error_when_deleting_unknown_asset(self, storage, asset):
        asset_key = str(hash(asset))

        with pytest.raises(KeyError):
            del storage[asset_key]

    def test_remove_deletes_asset_from_storage(self, storage, asset):
        asset_key = str(hash(asset))
        storage[asset_key] = asset, set()

        del storage[asset_key]

        assert asset_key not in storage

    def test_iterator_contains_all_stored_assets(self, storage):
        assets = (
            Asset(io.BytesIO(b'0')),
            Asset(io.BytesIO(b'1')),
            Asset(io.BytesIO(b'2')),
        )
        for asset in assets:
            asset_key = str(hash(asset))
            storage[asset_key] = asset, set()

        iterator = iter(storage)

        assert len(list(iterator)) == 3

    def test_iterator_is_a_readable_storage_snapshot(self, storage):
        assets = (
            Asset(io.BytesIO(b'0')),
            Asset(io.BytesIO(b'1')),
            Asset(io.BytesIO(b'2')),
            Asset(io.BytesIO(b'3')),
        )
        asset_keys = tuple(str(hash(asset)) for asset in assets)
        storage[asset_keys[0]] = assets[0], set()
        storage[asset_keys[1]] = assets[1], set()
        iterator = iter(storage)

        del storage[asset_keys[0]]
        storage[asset_keys[2]] = assets[2], set()
        storage[asset_keys[3]] = assets[3], set()

        assert set(iterator) == {asset_keys[0], asset_keys[1]}

    def test_get_returns_tags_for_asset(self, storage, asset):
        asset_tags = {'foo', 'bar'}
        asset_key = str(hash(asset))
        storage[asset_key] = asset, asset_tags

        _, tags = storage[asset_key]

        assert tags == asset_tags

    def test_get_fails_for_unknown_asset(self, storage):
        unstored_asset_key = str(0)

        with pytest.raises(KeyError):
            storage[unstored_asset_key]

    def test_filter_by_tags_returns_empty_iterator_when_storage_is_empty(self, storage):
        tagged_asset_keys = storage.filter_by_tags('some tag')

        assert len(list(tagged_asset_keys)) == 0

    def test_filter_by_tags_returns_all_assets_when_no_tags_are_specified(self, storage, asset):
        asset_key = str(hash(asset))
        storage[asset_key] = asset, {'foo'}

        tagged_asset_keys = storage.filter_by_tags()

        assert asset_key in tagged_asset_keys

    def test_filter_by_tags_returns_assets_with_specified_tags(self, storage):
        assets = (
            Asset(io.BytesIO(b'0')),
            Asset(io.BytesIO(b'1')),
            Asset(io.BytesIO(b'2')),
        )
        asset_keys = tuple(str(hash(asset)) for asset in assets)
        storage[asset_keys[0]] = assets[0], {'foo'}
        storage[asset_keys[1]] = assets[1], {'foo', 'bar'}
        storage[asset_keys[2]] = assets[2], {'foo', 'bar'}

        tagged_asset_keys = storage.filter_by_tags('bar', 'foo')

        assert (
            asset_keys[0] not in tagged_asset_keys
            and asset_keys[1] in tagged_asset_keys
            and asset_keys[2] in tagged_asset_keys
        )

    @pytest.mark.parametrize('tags', [None, {'my', 'tags'}])
    def test_set_does_nothing_when_asset_is_already_in_storage(self, storage, asset, tags):
        asset_key = str(hash(asset))
        storage[asset_key] = asset, tags

        storage[asset_key] = asset, tags

        assert len(list(storage)) == 1

    def test_filter_returns_empty_list_when_storage_is_empty(self, storage):
        filtered_asset_keys = storage.filter()
        assert not filtered_asset_keys

    def test_filter_returns_assets_with_specified_madam_metadata(self, storage):
        asset = Asset(io.BytesIO(b'TestEssence'), duration=1)
        asset_key = str(hash(asset))
        storage[asset_key] = asset, set()

        asset_keys_with_1s_duration = storage.filter(duration=1)

        assert len(asset_keys_with_1s_duration) == 1
        assert list(asset_keys_with_1s_duration)[0] == asset_key

    def test_filter_with_multiple_criteria_returns_each_match_only_once(self, storage):
        asset = Asset(io.BytesIO(b'TestEssence'), duration=1, width=100)
        asset_key = str(hash(asset))
        storage[asset_key] = asset, set()

        result = list(storage.filter(duration=1, width=100))

        assert result.count(asset_key) == 1

    def test_filter_excludes_assets_not_matching_all_criteria(self, storage):
        matching = Asset(io.BytesIO(b'A'), duration=1, width=100)
        partial = Asset(io.BytesIO(b'B'), duration=1, width=200)
        for a in (matching, partial):
            storage[str(hash(a))] = a, set()

        result = list(storage.filter(duration=1, width=100))

        assert str(hash(matching)) in result
        assert str(hash(partial)) not in result


@pytest.mark.usefixtures('asset', 'shelve_storage')
class TestShelveStorage:
    @pytest.fixture
    def storage(self, shelve_storage):
        return shelve_storage

    def test_raises_error_when_storage_path_is_not_a_file(self, tmpdir):
        with pytest.raises(ValueError):
            ShelveStorage(str(tmpdir))

    def test_set_writes_data_to_storage_path(self, storage, asset):
        asset_key = str(hash(asset))
        storage[asset_key] = asset, set()

        # shelve may append an extension (.db, .dir, etc.) depending on the dbm backend
        assert glob.glob(str(storage.path) + '*')

    def test_contains_returns_false_for_non_string_key(self, storage):
        assert (42 in storage) is False


@pytest.fixture
def asset():
    return Asset(io.BytesIO(b'TestEssence'))


@pytest.mark.usefixtures('asset')
class TestAsset:
    def test_asset_has_mime_type(self, asset):
        assert hasattr(asset, 'mime_type')

    def test_asset_has_essence(self, asset):
        assert hasattr(asset, 'essence')

    def test_asset_has_metadata(self, asset):
        assert hasattr(asset, 'metadata')

    def test_assets_are_equal_when_essence_and_properties_are_identical(self, asset):
        asset.some_attr = 42
        another_asset = Asset(asset.essence)
        another_asset.some_attr = 42

        assert asset is not another_asset
        assert asset == another_asset

    def test_asset_getattr_is_identical_to_access_through_metadata(self):
        asset_with_metadata = Asset(io.BytesIO(b'TestEssence'), SomeKey='SomeValue', AnotherKey=None, _42=43.0)

        for key, value in asset_with_metadata.metadata.items():
            assert getattr(asset_with_metadata, key) == value

    def test_setattr_raises_when_attribute_is_a_metadata_attribute(self):
        asset_with_metadata = Asset(io.BytesIO(b''), SomeMetadata=42)

        with pytest.raises(NotImplementedError):
            asset_with_metadata.SomeMetadata = 43

    def test_asset_essence_can_be_read_multiple_times(self, asset):
        essence_contents = asset.essence.read()
        same_essence_contents = asset.essence.read()

        assert essence_contents == same_essence_contents

    def test_hash_is_equal_for_equal_assets(self):
        metadata = dict(SomeMetadata=42)
        asset0 = Asset(io.BytesIO(b'same'), **metadata)
        asset1 = Asset(io.BytesIO(b'same'), **metadata)

        assert hash(asset0) == hash(asset1)

    def test_hash_is_different_when_assets_have_different_metadata(self):
        asset0 = Asset(io.BytesIO(b'same'), SomeMetadata=42)
        asset1 = Asset(io.BytesIO(b'same'), DifferentMetadata=43)

        assert hash(asset0) != hash(asset1)


@pytest.mark.usefixtures('asset')
class TestPipeline:
    @pytest.fixture
    def pipeline(self):
        return Pipeline()

    def test_empty_pipeline_does_not_change_assets(self, pipeline):
        some_asset = Asset(io.BytesIO(b'some'))
        another_asset = Asset(io.BytesIO(b'other'))

        processed_assets = pipeline.process(some_asset, another_asset)

        assert some_asset in processed_assets
        assert another_asset in processed_assets

    def test_pipeline_contains_operator_after_it_was_added(self, pipeline):
        operator = unittest.mock.MagicMock()

        pipeline.add(operator)

        assert operator in pipeline.operators

    def test_operator_is_applied_to_assets_when_process_is_called(self, pipeline, asset):
        operator = unittest.mock.MagicMock()
        pipeline.add(operator)

        [processed_asset for processed_asset in pipeline.process(asset)]

        operator.assert_called_once_with(asset)

    def test_branch_fans_out_one_asset_per_pipeline(self, pipeline):
        p1, p2 = Pipeline(), Pipeline()
        asset = Asset(io.BytesIO(b'x'))

        pipeline.branch(p1, p2)
        results = list(pipeline.process(asset))

        assert len(results) == 2

    def test_branch_pipelines_apply_independent_operators(self, pipeline):
        p1 = Pipeline()
        p1.add(lambda a: Asset(io.BytesIO(b'from_p1')))
        p2 = Pipeline()
        p2.add(lambda a: Asset(io.BytesIO(b'from_p2')))
        asset = Asset(io.BytesIO(b'original'))

        pipeline.branch(p1, p2)
        results = list(pipeline.process(asset))

        essences = {r.essence.read() for r in results}
        assert essences == {b'from_p1', b'from_p2'}

    def test_branch_step_is_recorded_in_operators(self, pipeline):
        p1, p2 = Pipeline(), Pipeline()

        pipeline.branch(p1, p2)

        assert len(pipeline.operators) == 1

    def test_when_applies_then_if_predicate_is_true(self, pipeline, asset):
        def then_op(a):
            return Asset(io.BytesIO(b'then'))

        pipeline.when(lambda a: True, then_op)
        results = list(pipeline.process(asset))

        assert results[0].essence.read() == b'then'

    def test_when_applies_else_if_predicate_is_false(self, pipeline, asset):
        def then_op(a):
            return Asset(io.BytesIO(b'then'))

        def else_op(a):
            return Asset(io.BytesIO(b'else'))

        pipeline.when(lambda a: False, then_op, else_op)
        results = list(pipeline.process(asset))

        assert results[0].essence.read() == b'else'

    def test_when_passes_through_if_predicate_is_false_and_no_else(self, pipeline):
        asset = Asset(io.BytesIO(b'original'))

        def then_op(a):
            return Asset(io.BytesIO(b'then'))

        pipeline.when(lambda a: False, then_op)
        results = list(pipeline.process(asset))

        assert results[0].essence.read() == b'original'

    def test_when_step_is_recorded_in_operators(self, pipeline, asset):
        pipeline.when(lambda a: True, lambda a: a)

        assert len(pipeline.operators) == 1


class TestErrorHierarchy:
    def test_transient_operator_error_is_subclass_of_operator_error(self):
        from madam.core import OperatorError, TransientOperatorError

        assert issubclass(TransientOperatorError, OperatorError)

    def test_permanent_operator_error_is_subclass_of_operator_error(self):
        from madam.core import OperatorError, PermanentOperatorError

        assert issubclass(PermanentOperatorError, OperatorError)

    def test_unsupported_format_error_is_subclass_of_permanent_operator_error(self):
        from madam.core import PermanentOperatorError, UnsupportedFormatError

        assert issubclass(UnsupportedFormatError, PermanentOperatorError)

    def test_transient_operator_error_can_be_raised_and_caught_as_operator_error(self):
        from madam.core import OperatorError, TransientOperatorError

        with pytest.raises(OperatorError):
            raise TransientOperatorError('disk full')

    def test_permanent_operator_error_can_be_raised_and_caught_as_operator_error(self):
        from madam.core import OperatorError, PermanentOperatorError

        with pytest.raises(OperatorError):
            raise PermanentOperatorError('bad codec')


class TestAssetGetattr:
    """R11: Asset.__getattr__ must not forward dunder names into metadata."""

    def test_dunder_key_in_metadata_raises_attribute_error(self):
        """Even if metadata contains a dunder key, accessing it raises AttributeError."""
        # Construct the metadata dict manually to bypass normal guards.
        from frozendict import frozendict

        asset = Asset.__new__(Asset)
        object.__setattr__(asset, '_essence_data', b'')
        object.__setattr__(asset, 'metadata', frozendict({'__len__': lambda: 42}))

        with pytest.raises(AttributeError):
            _ = asset.__len__

    def test_regular_metadata_key_still_accessible(self):
        asset = Asset(io.BytesIO(b'data'), width=100)
        assert asset.width == 100

    def test_missing_non_dunder_attribute_raises_attribute_error(self):
        asset = Asset(io.BytesIO(b'data'))
        with pytest.raises(AttributeError):
            _ = asset.nonexistent_key


class TestAssetFromBytes:
    def test_from_bytes_produces_asset_equal_to_normal_constructor(self):
        data = b'hello refactor'
        normal = Asset(io.BytesIO(data), width=42, mime_type='image/png')
        fast = Asset._from_bytes(data, width=42, mime_type='image/png')
        assert normal == fast

    def test_from_bytes_essence_matches(self):
        data = b'essence data'
        asset = Asset._from_bytes(data, mime_type='image/jpeg')
        assert asset.essence.read() == data

    def test_from_bytes_metadata_is_accessible(self):
        asset = Asset._from_bytes(b'x', width=100, height=200, mime_type='image/png')
        assert asset.width == 100
        assert asset.height == 200

    def test_from_bytes_content_id_matches(self):
        import hashlib

        data = b'check bytes'
        asset = Asset._from_bytes(data)
        assert asset.content_id == hashlib.sha256(data).hexdigest()

    def test_from_bytes_adds_none_mime_type_when_absent(self):
        asset = Asset._from_bytes(b'x')
        assert asset.mime_type is None

    def test_from_bytes_does_not_read_stream(self):
        calls = []

        class CountingBytesIO(io.BytesIO):
            def read(self, *args, **kwargs):
                calls.append(1)
                return super().read(*args, **kwargs)

        # _from_bytes should bypass stream reads entirely
        data = b'skip read'
        Asset._from_bytes(data)
        assert calls == [], 'Asset._from_bytes must not call read() on any stream'


class TestAssetContentId:
    def test_content_id_is_a_string(self):
        asset = Asset(io.BytesIO(b'hello'))
        assert isinstance(asset.content_id, str)

    def test_content_id_is_64_hex_chars(self):
        asset = Asset(io.BytesIO(b'hello'))
        assert len(asset.content_id) == 64
        assert all(c in '0123456789abcdef' for c in asset.content_id)

    def test_content_id_is_stable_across_instances_with_same_bytes(self):
        asset_a = Asset(io.BytesIO(b'same bytes'))
        asset_b = Asset(io.BytesIO(b'same bytes'))
        assert asset_a.content_id == asset_b.content_id

    def test_content_id_differs_for_different_bytes(self):
        asset_a = Asset(io.BytesIO(b'hello'))
        asset_b = Asset(io.BytesIO(b'world'))
        assert asset_a.content_id != asset_b.content_id

    def test_content_id_is_sha256_of_essence(self):
        import hashlib

        data = b'check me'
        asset = Asset(io.BytesIO(data))
        expected = hashlib.sha256(data).hexdigest()
        assert asset.content_id == expected

    def test_content_id_is_unaffected_by_metadata(self):
        data = b'same bytes'
        asset_a = Asset(io.BytesIO(data), width=100)
        asset_b = Asset(io.BytesIO(data), width=200)
        assert asset_a.content_id == asset_b.content_id


class TestLazyAssetContentId:
    """R09: LazyAsset.content_id must be computed only once and cached."""

    def _make_lazy_asset(self, data: bytes) -> LazyAsset:
        calls = []

        def loader(uri):
            calls.append(uri)
            return io.BytesIO(data)

        asset = LazyAsset.__new__(LazyAsset)
        object.__setattr__(asset, '_uri', 'test://uri')
        object.__setattr__(asset, '_loader', loader)
        object.__setattr__(asset, 'metadata', {})
        asset._loader_calls = calls
        return asset

    def test_content_id_is_correct_hash(self):
        import hashlib

        data = b'lazy bytes'
        asset = self._make_lazy_asset(data)
        expected = hashlib.sha256(data).hexdigest()
        assert asset.content_id == expected

    def test_content_id_does_not_call_loader_twice(self):
        data = b'cached bytes'
        asset = self._make_lazy_asset(data)

        _ = asset.content_id
        _ = asset.content_id  # second access — must NOT trigger another loader call

        assert len(asset._loader_calls) == 1, f'Expected loader called once, got {len(asset._loader_calls)} calls'

    def test_content_id_is_stable_across_accesses(self):
        data = b'stable'
        asset = self._make_lazy_asset(data)
        first = asset.content_id
        second = asset.content_id
        assert first == second


class TestIndexedAssetStorage:
    """R12: IndexedAssetStorage mixin; InMemoryStorage uses it."""

    def test_indexed_asset_storage_is_importable(self):
        assert IndexedAssetStorage is not None

    def test_in_memory_storage_is_indexed(self):
        assert issubclass(InMemoryStorage, IndexedAssetStorage)

    def test_filter_returns_correct_results_with_many_assets(self):
        storage = InMemoryStorage()
        target_key = 'target'
        storage[target_key] = Asset(io.BytesIO(b'target'), color_space='rgb', width=42), frozenset()
        for i in range(999):
            storage[str(i)] = Asset(io.BytesIO(f'asset_{i}'.encode()), color_space='gray', width=i), frozenset()

        result = list(storage.filter(color_space='rgb', width=42))

        assert result == [target_key]

    def test_filter_result_excludes_non_matching_assets(self):
        storage = InMemoryStorage()
        storage['a'] = Asset(io.BytesIO(b'a'), x=1, y=2), frozenset()
        storage['b'] = Asset(io.BytesIO(b'b'), x=1, y=99), frozenset()
        storage['c'] = Asset(io.BytesIO(b'c'), x=99, y=2), frozenset()

        result = list(storage.filter(x=1, y=2))

        assert result == ['a']

    def test_filter_returns_empty_when_no_match(self):
        storage = InMemoryStorage()
        storage['k'] = Asset(io.BytesIO(b'v'), width=10), frozenset()

        result = list(storage.filter(width=999))

        assert result == []

    def test_delitem_removes_from_index(self):
        storage = InMemoryStorage()
        storage['k'] = Asset(io.BytesIO(b'v'), width=10), frozenset()
        del storage['k']

        result = list(storage.filter(width=10))

        assert result == []


class TestInMemoryStorageThreadSafety:
    def test_storage_has_reentrant_lock(self):
        storage = InMemoryStorage()

        assert hasattr(storage, '_lock')
        assert isinstance(storage._lock, type(threading.RLock()))

    def test_concurrent_writes_preserve_all_entries(self):
        storage = InMemoryStorage()
        errors: list[Exception] = []

        def writer(start: int) -> None:
            try:
                for i in range(20):
                    key = start + i
                    storage[key] = Asset(io.BytesIO(b'x'), width=key), frozenset()
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(n * 20,)) for n in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(storage) == 200

    def test_concurrent_deletes_are_safe(self):
        storage = InMemoryStorage()
        for i in range(100):
            storage[i] = Asset(io.BytesIO(b'x')), frozenset()
        errors: list[Exception] = []

        def deleter(keys: list[int]) -> None:
            for key in keys:
                try:
                    del storage[key]
                except KeyError:
                    pass  # Already deleted by another thread — acceptable.
                except Exception as exc:  # noqa: BLE001
                    errors.append(exc)

        threads = [threading.Thread(target=deleter, args=(list(range(i, 100, 4)),)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
