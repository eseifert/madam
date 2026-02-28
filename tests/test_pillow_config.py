"""Tests for R10: PillowProcessor warns on unknown config keys."""
import io
import warnings

import PIL.Image

import madam.image


def _make_small_jpeg() -> io.BytesIO:
    buf = io.BytesIO()
    img = PIL.Image.new('RGB', (4, 4), color=(128, 64, 32))
    img.save(buf, 'JPEG')
    buf.seek(0)
    return buf


class TestPillowProcessorConfigWarnings:
    def test_unknown_jpeg_config_key_emits_user_warning(self):
        config = {'image/jpeg': {'typo_key': 99}}
        proc = madam.image.PillowProcessor(config)
        asset = proc.read(_make_small_jpeg())

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter('always')
            convert_op = proc.convert(mime_type='image/jpeg')
            convert_op(asset)

        user_warnings = [x for x in w if issubclass(x.category, UserWarning)]
        assert user_warnings, 'Expected a UserWarning for unknown config key'
        assert any('typo_key' in str(x.message) for x in user_warnings)

    def test_known_jpeg_config_key_does_not_warn(self):
        config = {'image/jpeg': {'quality': 80}}
        proc = madam.image.PillowProcessor(config)
        asset = proc.read(_make_small_jpeg())

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter('always')
            convert_op = proc.convert(mime_type='image/jpeg')
            convert_op(asset)

        user_warnings = [x for x in w if issubclass(x.category, UserWarning)]
        assert not user_warnings, f'Unexpected UserWarning(s): {[str(x.message) for x in user_warnings]}'

    def test_unknown_png_config_key_emits_user_warning(self):
        config = {'image/png': {'unknown_key': True}}
        proc = madam.image.PillowProcessor(config)
        buf = io.BytesIO()
        PIL.Image.new('RGB', (4, 4)).save(buf, 'PNG')
        buf.seek(0)
        asset = proc.read(buf)

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter('always')
            convert_op = proc.convert(mime_type='image/png')
            convert_op(asset)

        user_warnings = [x for x in w if issubclass(x.category, UserWarning)]
        assert user_warnings, 'Expected a UserWarning for unknown config key'
        assert any('unknown_key' in str(x.message) for x in user_warnings)
