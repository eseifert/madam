import madam
from madam.core import Madam


class TestDefaultMadam:
    def test_default_madam_is_a_madam_instance(self):
        assert isinstance(madam.default_madam, Madam)

    def test_default_madam_is_same_object_on_repeated_access(self):
        first = madam.default_madam
        second = madam.default_madam
        assert first is second

    def test_default_madam_is_lazily_initialised(self):
        # Accessing the attribute must not raise and must be truthy.
        assert madam.default_madam is not None
