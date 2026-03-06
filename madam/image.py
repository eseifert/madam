import io
import math
import warnings
from collections.abc import Callable, Iterable, Mapping
from enum import Enum, StrEnum
from typing import IO, Any

import PIL.ExifTags
import PIL.Image
import PIL.ImageDraw
import PIL.ImageEnhance
import PIL.ImageFilter
import PIL.ImageFont
import PIL.ImageOps
from bidict import bidict

from madam.core import Asset, OperatorError, ProcessingContext, Processor, UnsupportedFormatError, operator
from madam.mime import MimeType

# Formats whose Pillow encoder accepts an explicit icc_profile= keyword.
_ICC_PROFILE_FORMATS: frozenset[MimeType] = frozenset(
    {
        MimeType('image/avif'),
        MimeType('image/jpeg'),
        MimeType('image/png'),
        MimeType('image/tiff'),
        MimeType('image/webp'),
    }
)

_VALID_FORMAT_CONFIG_KEYS: dict[MimeType, frozenset[str]] = {
    MimeType('image/avif'): frozenset({'quality', 'speed'}),
    MimeType('image/jpeg'): frozenset({'quality', 'progressive'}),
    MimeType('image/png'): frozenset({'optimize', 'zopfli', 'zopfli_strategies'}),
    MimeType('image/tiff'): frozenset({'compression'}),
    MimeType('image/webp'): frozenset({'quality', 'method'}),
    MimeType('image/gif'): frozenset({'optimize'}),
}


def _resolve_gravity(
    canvas_width: int,
    canvas_height: int,
    source_width: int,
    source_height: int,
    gravity: 'Gravity | str',
) -> tuple[int, int]:
    """
    Return the ``(x, y)`` top-left offset at which to place a source image of
    ``(source_width, source_height)`` inside a canvas of
    ``(canvas_width, canvas_height)`` according to *gravity*.

    *gravity* may be a :class:`Gravity` member or a plain string with the
    same value (e.g. ``'center'``).
    """
    h_offsets = {
        'west': 0,
        'center': (canvas_width - source_width) // 2,
        'east': canvas_width - source_width,
    }
    v_offsets = {
        'north': 0,
        'center': (canvas_height - source_height) // 2,
        'south': canvas_height - source_height,
    }
    gravity_map: dict[str, tuple[int, int]] = {
        'north_west': (h_offsets['west'], v_offsets['north']),
        'north': (h_offsets['center'], v_offsets['north']),
        'north_east': (h_offsets['east'], v_offsets['north']),
        'west': (h_offsets['west'], v_offsets['center']),
        'center': (h_offsets['center'], v_offsets['center']),
        'east': (h_offsets['east'], v_offsets['center']),
        'south_west': (h_offsets['west'], v_offsets['south']),
        'south': (h_offsets['center'], v_offsets['south']),
        'south_east': (h_offsets['east'], v_offsets['south']),
    }
    if gravity not in gravity_map:
        raise ValueError(f'Unknown gravity: {gravity!r}')
    return gravity_map[gravity]


class ResizeMode(Enum):
    """
    Represents a behavior for image resize operations.
    """

    #: Image exactly matches the specified dimensions
    EXACT = 0
    #: Image is resized to fit completely into the specified dimensions
    FIT = 1
    #: Image is resized to completely fill the specified dimensions
    FILL = 2


class FlipOrientation(Enum):
    """
    Represents an axis for image flip operations.
    """

    #: Horizontal axis
    HORIZONTAL = 0
    #: Vertical axis
    VERTICAL = 1


class Gravity(StrEnum):
    """
    Named anchor positions for operators that place or crop images.

    Because :class:`Gravity` is a :class:`~enum.StrEnum`, each member
    compares equal to its string value and can be passed wherever a plain
    gravity string is accepted:

    .. code-block:: python

        from madam.image import Gravity

        crop = processor.crop(width=800, height=600, gravity=Gravity.CENTER)
        # equivalent to: processor.crop(width=800, height=600, gravity='center')

    Members and their string values:

    +-----------------+------------------+
    | Member          | String value     |
    +=================+==================+
    | ``NORTH_WEST``  | ``'north_west'`` |
    +-----------------+------------------+
    | ``NORTH``       | ``'north'``      |
    +-----------------+------------------+
    | ``NORTH_EAST``  | ``'north_east'`` |
    +-----------------+------------------+
    | ``WEST``        | ``'west'``       |
    +-----------------+------------------+
    | ``CENTER``      | ``'center'``     |
    +-----------------+------------------+
    | ``EAST``        | ``'east'``       |
    +-----------------+------------------+
    | ``SOUTH_WEST``  | ``'south_west'`` |
    +-----------------+------------------+
    | ``SOUTH``       | ``'south'``      |
    +-----------------+------------------+
    | ``SOUTH_EAST``  | ``'south_east'`` |
    +-----------------+------------------+

    .. versionadded:: 1.0
    """

    NORTH_WEST = 'north_west'
    NORTH = 'north'
    NORTH_EAST = 'north_east'
    WEST = 'west'
    CENTER = 'center'
    EAST = 'east'
    SOUTH_WEST = 'south_west'
    SOUTH = 'south'
    SOUTH_EAST = 'south_east'


class PillowContext(ProcessingContext):
    """
    Deferred in-memory state for a Pillow processing run.

    Holds a live :class:`PIL.Image.Image` and the target MIME type so that
    consecutive Pillow operators can be applied to the pixel data without
    intermediate encode/decode cycles.  Call :meth:`materialize` to produce
    the final encoded :class:`~madam.core.Asset`.

    Instances are created by :class:`PillowProcessor` and passed to
    :meth:`~madam.core.Processor.execute_run`.  Custom operator
    implementations can inspect or mutate :attr:`image` and :attr:`mime_type`
    before the result is materialised.

    :ivar image: The live Pillow image being transformed.  Operators may
        replace this attribute with a new :class:`PIL.Image.Image` object.
    :vartype image: PIL.Image.Image
    :ivar mime_type: MIME type string that controls the output format when
        :meth:`materialize` encodes the image.  Changing this attribute is
        equivalent to inserting a :meth:`~PillowProcessor.convert` step.
    :vartype mime_type: str

    .. versionadded:: 1.0
    """

    def __init__(self, processor: 'PillowProcessor', image: PIL.Image.Image, mime_type: str) -> None:
        self._proc = processor
        self.image = image
        self.mime_type = mime_type

    @property
    def processor(self) -> 'PillowProcessor':
        return self._proc

    def materialize(self) -> Asset:
        icc_profile = getattr(self.image, 'info', {}).get('icc_profile')
        return self._proc._image_to_asset(self.image, mime_type=self.mime_type, icc_profile=icc_profile)


class PillowProcessor(Processor):
    """
    Represents a processor that uses Pillow as a backend.
    """

    __mime_type_to_pillow_type = bidict(
        {
            MimeType('image/avif'): 'AVIF',
            MimeType('image/bmp'): 'BMP',
            MimeType('image/gif'): 'GIF',
            MimeType('image/jpeg'): 'JPEG',
            MimeType('image/png'): 'PNG',
            MimeType('image/tiff'): 'TIFF',
            MimeType('image/webp'): 'WEBP',
        }
    )

    # Register HEIC/HEIF support when the pillow-heif plugin is installed.
    # The plugin registers itself with Pillow's codec registry so that
    # PIL.Image.open() can decode HEIF files.  HEIC is used as the canonical
    # MIME type because it is the container Apple devices produce; both
    # image/heic and image/heif map to the same 'HEIF' Pillow format, but
    # bidict requires bijective mappings so only one entry is registered here.
    try:
        import pillow_heif as _pillow_heif  # type: ignore[import-unresolved]

        _pillow_heif.register_heif_opener()
        __mime_type_to_pillow_type[MimeType('image/heic')] = 'HEIF'
        del _pillow_heif
    except ImportError:
        pass

    __format_defaults = {
        MimeType('image/avif'): dict(
            quality=80,
            speed=6,
        ),
        MimeType('image/gif'): dict(
            optimize=True,
        ),
        MimeType('image/jpeg'): dict(
            optimize=True,
            progressive=True,
            quality=80,
        ),
        MimeType('image/png'): dict(
            optimize=True,
        ),
        MimeType('image/tiff'): dict(
            compression='tiff_deflate',
        ),
        MimeType('image/webp'): dict(
            method=6,
            quality=80,
        ),
    }

    __pillow_mode_to_color_mode = bidict(
        {
            '1': ('LUMA', 1, 'uint'),
            'L': ('LUMA', 8, 'uint'),
            'LA': ('LUMAA', 8, 'uint'),
            'P': ('PALETTE', 8, 'uint'),
            'RGB': ('RGB', 8, 'uint'),
            'RGBA': ('RGBA', 8, 'uint'),
            'RGBX': ('RGBX', 8, 'uint'),
            'CMYK': ('CMYK', 8, 'uint'),
            'YCbCr': ('YCbCr', 8, 'uint'),
            'LAB': ('LAB', 8, 'uint'),
            'HSV': ('HSV', 8, 'uint'),
            'I;16': ('LUMA', 16, 'uint'),
            'I': ('LUMA', 32, 'uint'),
            'F': ('LUMA', 32, 'float'),
        }
    )

    @property
    def supported_mime_types(self) -> frozenset:
        return frozenset(PillowProcessor.__mime_type_to_pillow_type.keys())

    def __init__(self, config: Mapping[str, Any] | None = None) -> None:
        """
        Initializes a new `PillowProcessor`.

        :param config: Mapping with settings.
        """
        super().__init__(config)

    def execute_run(self, steps, asset_or_context):
        """
        Apply a group of consecutive Pillow operators in a single decode/encode cycle.

        The input :class:`Asset` (or incoming :class:`PillowContext` from a prior
        run) is decoded once.  Each step's PIL image transform is applied in memory.
        The result is returned as a :class:`PillowContext`; :class:`~madam.core.Pipeline`
        encodes it only when a processor boundary or pipeline end is reached.
        """
        if isinstance(asset_or_context, PillowContext):
            image = asset_or_context.image
            mime_type = str(asset_or_context.mime_type)
        else:
            asset = asset_or_context
            mime_type = str(asset.mime_type)
            with PIL.Image.open(asset.essence) as img:
                img.load()  # force pixel decode so the file handle can be released
                image = img.copy()

        for step in steps:
            # Look up a PIL-level transform for this operator.
            op_name = getattr(step, 'func', None)
            op_name = op_name.__name__ if op_name is not None else None
            transform = getattr(self, f'_transform_{op_name}', None) if op_name else None

            if transform is not None:
                image, mime_type = transform(image, mime_type, **step.keywords)
            else:
                # Fallback: materialise the current context, apply the step, then decode back.
                tmp_ctx = PillowContext(self, image, mime_type)
                tmp_asset = tmp_ctx.materialize()
                result = step(tmp_asset)
                if isinstance(result, PillowContext):
                    image = result.image
                    mime_type = str(result.mime_type)
                else:
                    with PIL.Image.open(result.essence) as img:
                        img.load()
                        image = img.copy()
                    mime_type = str(result.mime_type)

        return PillowContext(self, image, mime_type)

    def _transform_resize(
        self,
        image: PIL.Image.Image,
        mime_type: str,
        *,
        width: int,
        height: int,
        mode: ResizeMode = ResizeMode.EXACT,
        gravity: Gravity | str = 'center',
    ) -> tuple[PIL.Image.Image, str]:
        """PIL-level resize transform (no encode/decode)."""
        if mode == ResizeMode.EXACT:
            resized_width, resized_height = width, height
        else:
            aspect = image.width / image.height
            aspect_target = width / height
            if (
                mode == ResizeMode.FIT
                and aspect >= aspect_target
                or mode == ResizeMode.FILL
                and aspect <= aspect_target
            ):
                resize_factor = width / image.width
            else:
                resize_factor = height / image.height
            resized_width = max(1, round(resize_factor * image.width))
            resized_height = max(1, round(resize_factor * image.height))

        depth = 32 if image.mode in ('I', 'F') else (16 if image.mode == 'I;16' else 8)
        resampling = PIL.Image.Resampling.LANCZOS if depth == 8 else PIL.Image.Resampling.NEAREST
        resized = image.resize((resized_width, resized_height), resample=resampling)

        if mode == ResizeMode.FILL and (resized_width != width or resized_height != height):
            crop_x, crop_y = _resolve_gravity(resized_width, resized_height, width, height, gravity)
            resized = resized.crop((crop_x, crop_y, crop_x + width, crop_y + height))

        return resized, mime_type

    def _transform_crop(
        self,
        image: PIL.Image.Image,
        mime_type: str,
        *,
        width: int,
        height: int,
        x: int | None = None,
        y: int | None = None,
        gravity: Gravity | str = 'north_west',
    ) -> tuple[PIL.Image.Image, str]:
        """PIL-level crop transform (no encode/decode)."""
        if x is None and y is None:
            x, y = _resolve_gravity(image.width, image.height, width, height, gravity)
        elif x is None or y is None:
            raise OperatorError('Both x and y must be provided together, or omit both to use gravity')

        if x == 0 and y == 0 and width == image.width and height == image.height:
            return image, mime_type

        max_x = max(0, min(image.width, width + x))
        max_y = max(0, min(image.height, height + y))
        min_x = max(0, min(image.width, x))
        min_y = max(0, min(image.height, y))

        if min_x == image.width or min_y == image.height or max_x <= min_x or max_y <= min_y:
            raise OperatorError(f'Invalid cropping area: <x={x!r}, y={y!r}, width={width!r}, height={height!r}>')

        return image.crop(box=(min_x, min_y, max_x, max_y)), mime_type

    def _transform_convert(
        self,
        image: PIL.Image.Image,
        current_mime_type: str,
        *,
        mime_type: MimeType | str,
        color_space: str | None = None,
        depth: int | None = None,
        data_type: str | None = None,
    ) -> tuple[PIL.Image.Image, str]:
        """PIL-level convert transform: update MIME type and optionally convert PIL mode."""
        target_mime = MimeType(mime_type)
        mode_lookup = PillowProcessor._PillowProcessor__pillow_mode_to_color_mode  # type: ignore[attr-defined]
        current_tuple = mode_lookup.get(image.mode, (None, None, None))
        color_mode = (
            color_space or current_tuple[0],
            depth or current_tuple[1],
            data_type or current_tuple[2],
        )
        pil_mode = mode_lookup.inv.get(color_mode)
        if pil_mode is not None and pil_mode != image.mode:
            image = image.convert(pil_mode)
        return image, str(target_mime)

    def read(self, file: IO) -> Asset:
        with PIL.Image.open(file) as image:
            mime_type = PillowProcessor.__mime_type_to_pillow_type.inv[image.format]
            color_space, bit_depth, data_type = PillowProcessor.__pillow_mode_to_color_mode[image.mode]
            metadata = dict(
                mime_type=str(mime_type),
                width=image.width,
                height=image.height,
                color_space=color_space,
                depth=bit_depth,
                data_type=data_type,
            )
            if getattr(image, 'is_animated', False):
                metadata['frame_count'] = getattr(image, 'n_frames', 0)
            icc_profile = image.info.get('icc_profile')
            if icc_profile:
                metadata['icc_profile'] = icc_profile
        file.seek(0)
        asset = Asset(file, **metadata)
        return asset

    def can_read(self, file: IO) -> bool:
        try:
            PIL.Image.open(file)
            return True
        except IOError:
            return False
        finally:
            file.seek(0)

    @operator
    def resize(
        self,
        asset: Asset,
        width: int,
        height: int,
        mode: ResizeMode = ResizeMode.EXACT,
        gravity: Gravity | str = 'center',
    ) -> Asset:
        """
        Creates a new Asset whose essence is resized according to the specified
        parameters.

        In ``FILL`` mode the image is scaled up until it covers the target
        dimensions, then cropped to the exact target size.  The ``gravity``
        parameter controls which part of the scaled image is kept; it has no
        effect in ``EXACT`` or ``FIT`` mode.

        *gravity* may be a :class:`Gravity` member or the equivalent
        plain string (see :class:`Gravity` for the full list of values).

        :param asset: Asset to be resized
        :type asset: Asset
        :param width: Target width in pixels
        :type width: int
        :param height: Target height in pixels
        :type height: int
        :param mode: Resize behavior
        :type mode: ResizeMode
        :param gravity: Crop anchor used in ``FILL`` mode
        :type gravity: Gravity or str
        :return: Asset with resized essence
        :rtype: Asset
        """
        mime_type = MimeType(asset.mime_type)
        with PIL.Image.open(asset.essence) as image:
            icc_profile: bytes | None = image.info.get('icc_profile')
            if mode == ResizeMode.EXACT:
                resized_width = width
                resized_height = height
            else:
                aspect = asset.width / asset.height
                aspect_target = width / height
                if (
                    mode == ResizeMode.FIT
                    and aspect >= aspect_target
                    or mode == ResizeMode.FILL
                    and aspect <= aspect_target
                ):
                    resize_factor = width / image.width
                else:
                    resize_factor = height / image.height
                resized_width = max(1, round(resize_factor * image.width))
                resized_height = max(1, round(resize_factor * image.height))
            # Pillow supports resampling only for 8-bit images
            resampling_method = PIL.Image.Resampling.LANCZOS if asset.depth == 8 else PIL.Image.Resampling.NEAREST
            resized_image = image.resize((resized_width, resized_height), resample=resampling_method)

        if mode == ResizeMode.FILL and (resized_width != width or resized_height != height):
            crop_x, crop_y = _resolve_gravity(resized_width, resized_height, width, height, gravity)
            with resized_image:
                resized_image = resized_image.crop((crop_x, crop_y, crop_x + width, crop_y + height))

        with resized_image:
            resized_asset = self._image_to_asset(resized_image, mime_type=mime_type, icc_profile=icc_profile)
        return resized_asset

    def _image_to_asset(
        self, image: PIL.Image.Image, mime_type: MimeType | str, *, icc_profile: bytes | None = None
    ) -> Asset:
        """
        Converts an PIL image to a MADAM asset. The conversion can also include
        a change in file type.

        :param image: PIL image
        :type image: PIL.Image.Image
        :param mime_type: MIME type of the target asset
        :type mime_type: MimeType or str
        :param icc_profile: Raw ICC profile bytes to embed in the output file, or ``None``
        :type icc_profile: bytes or None
        :return: MADAM asset with the specified MIME type
        :rtype: Asset
        """
        mime_type = MimeType(mime_type)

        pil_format = PillowProcessor.__mime_type_to_pillow_type[mime_type]
        pil_options = dict(PillowProcessor.__format_defaults.get(mime_type, {}))
        format_config = dict(self.config.get(mime_type.type or '', {}))
        format_config.update(self.config.get(str(mime_type), {}))

        valid_keys = _VALID_FORMAT_CONFIG_KEYS.get(mime_type, frozenset())
        for key in format_config:
            if key not in valid_keys:
                warnings.warn(
                    f'Unknown config key {key!r} for format {mime_type}. Valid keys: {sorted(valid_keys)}',
                    UserWarning,
                    stacklevel=4,
                )

        if icc_profile and mime_type in _ICC_PROFILE_FORMATS:
            pil_options['icc_profile'] = icc_profile

        image_buffer = io.BytesIO()

        if mime_type == MimeType('image/png') and image.mode != 'P':
            use_zopfli = format_config.get('zopfli', False)
            if use_zopfli:
                try:
                    import zopfli  # type: ignore[import-unresolved]
                except ImportError:
                    raise ImportError(
                        "zopfli PNG optimization requires the 'optimize' extra: pip install madam[optimize]"
                    ) from None

                zopfli_png = zopfli.ZopfliPNG()
                # Convert 16-bit per channel images to 8-bit per channel
                zopfli_png.lossy_8bit = False
                # Allow altering hidden colors of fully transparent pixels
                zopfli_png.lossy_transparent = True
                # Use all available optimization strategies
                zopfli_png.filter_strategies = format_config.get('zopfli_strategies', '0me')

                pil_options.pop('optimize', False)
                essence = io.BytesIO()
                image.save(essence, 'PNG', optimize=False, **pil_options)
                essence.seek(0)
                optimized_data = zopfli_png.optimize(essence.read())
                image_buffer.write(optimized_data)
            else:
                image.save(image_buffer, pil_format, **pil_options)
        elif mime_type == MimeType('image/jpeg'):
            pil_options['progressive'] = int(format_config.get('progressive', pil_options['progressive']))
            pil_options['quality'] = int(format_config.get('quality', pil_options['quality']))
            image.save(image_buffer, pil_format, **pil_options)
        elif mime_type == MimeType('image/tiff') and image.mode == 'P':
            pil_options.pop('compression', '')
            image.save(image_buffer, pil_format, **pil_options)
        elif mime_type == MimeType('image/avif'):
            pil_options['quality'] = int(format_config.get('quality', pil_options['quality']))
            pil_options['speed'] = int(format_config.get('speed', pil_options['speed']))
            image.save(image_buffer, pil_format, **pil_options)
        elif mime_type == MimeType('image/webp'):
            pil_options['method'] = int(format_config.get('method', pil_options['method']))
            pil_options['quality'] = int(format_config.get('quality', pil_options['quality']))
            image.save(image_buffer, pil_format, **pil_options)
        else:
            image.save(image_buffer, pil_format, **pil_options)

        image_buffer.seek(0)

        asset = self._buffer_to_asset(image_buffer, image, mime_type)
        return asset

    def _buffer_to_asset(
        self,
        image_buffer: io.BytesIO,
        image: PIL.Image.Image,
        mime_type: 'MimeType | str',
    ) -> Asset:
        """
        Construct an :class:`Asset` from an already-encoded *image_buffer* using
        *image* metadata to avoid a second :func:`PIL.Image.open` call.

        For formats where encoding may alter the PIL mode (e.g. GIF palette
        quantisation), fall back to :meth:`read` to obtain accurate metadata.
        """
        mime_type = MimeType(mime_type)
        # GIF encoding can change mode (RGB→P); use read() for accuracy there.
        _FALLBACK_FORMATS = frozenset({MimeType('image/gif')})
        if mime_type in _FALLBACK_FORMATS:
            asset = self.read(image_buffer)
            return asset

        mode_map = PillowProcessor._PillowProcessor__pillow_mode_to_color_mode  # type: ignore[attr-defined]
        color_space, bit_depth, data_type = mode_map.get(image.mode, ('RGB', 8, 'uint'))
        metadata: dict = dict(
            mime_type=str(mime_type),
            width=image.width,
            height=image.height,
            color_space=color_space,
            depth=bit_depth,
            data_type=data_type,
        )
        if getattr(image, 'is_animated', False):
            metadata['frame_count'] = getattr(image, 'n_frames', 0)
        icc_profile = image.info.get('icc_profile') if hasattr(image, 'info') else None
        if icc_profile and mime_type in _ICC_PROFILE_FORMATS:
            metadata['icc_profile'] = icc_profile
        return Asset(image_buffer, **metadata)

    def _rotate(self, asset: Asset, rotation: PIL.Image.Transpose) -> Asset:
        """
        Creates a new image asset from specified asset whose essence is rotated
        by the specified rotation.

        :param asset: Image asset to be rotated
        :type asset: Asset
        :param rotation: One of `PIL.Image.FLIP_LEFT_RIGHT`,
        `PIL.Image.FLIP_TOP_BOTTOM`, `PIL.Image.ROTATE_90`,
        `PIL.Image.ROTATE_180`, `PIL.Image.ROTATE_270`, or
        `PIL.Image.TRANSPOSE`
        :return: New image asset with rotated essence
        :rtype: Asset
        """
        mime_type = MimeType(asset.mime_type)
        with PIL.Image.open(asset.essence) as image:
            transposed_image = image.transpose(rotation)
        with transposed_image:
            transposed_asset = self._image_to_asset(transposed_image, mime_type=mime_type)
        return transposed_asset

    @operator
    def transpose(self, asset: Asset) -> Asset:
        """
        Creates a new image asset whose essence is the transpose of the
        specified asset's essence.

        :param asset: Image asset whose essence is to be transposed
        :type asset: Asset
        :return: New image asset with transposed essence
        :rtype: Asset
        """
        return self._rotate(asset, PIL.Image.Transpose.TRANSPOSE)

    @operator
    def flip(self, asset: Asset, orientation: FlipOrientation) -> Asset:
        """
        Creates a new asset whose essence is flipped according the specified orientation.

        :param asset: Asset whose essence is to be flipped
        :type asset: Asset
        :param orientation: axis of the flip operation
        :type orientation: FlipOrientation
        :return: Asset with flipped essence
        :rtype: Asset
        """
        if orientation == FlipOrientation.HORIZONTAL:
            flip_orientation = PIL.Image.Transpose.FLIP_LEFT_RIGHT
        else:
            flip_orientation = PIL.Image.Transpose.FLIP_TOP_BOTTOM
        return self._rotate(asset, flip_orientation)

    @operator
    def auto_orient(self, asset: Asset) -> Asset:
        """
        Creates a new asset whose essence is rotated according to the Exif
        orientation. If no orientation metadata exists or asset is not rotated,
        an identical asset object is returned.

        :param asset: Asset with orientation metadata
        :type asset: Asset
        :return: Asset with rotated essence
        :rtype: Asset
        """
        orientation = asset.metadata.get('exif', {}).get('orientation')
        if orientation is None or orientation == 1:
            return asset

        flip_horizontally: Callable[[Asset], Asset] = self.flip(orientation=FlipOrientation.HORIZONTAL)
        flip_vertically: Callable[[Asset], Asset] = self.flip(orientation=FlipOrientation.VERTICAL)

        if orientation == 2:
            oriented_asset = flip_horizontally(asset)
        elif orientation == 3:
            oriented_asset = self._rotate(asset, PIL.Image.Transpose.ROTATE_180)
        elif orientation == 4:
            oriented_asset = flip_vertically(asset)
        elif orientation == 5:
            oriented_asset = flip_vertically(self._rotate(asset, PIL.Image.Transpose.ROTATE_90))
        elif orientation == 6:
            oriented_asset = self._rotate(asset, PIL.Image.Transpose.ROTATE_270)
        elif orientation == 7:
            oriented_asset = flip_horizontally(self._rotate(asset, PIL.Image.Transpose.ROTATE_90))
        elif orientation == 8:
            oriented_asset = self._rotate(asset, PIL.Image.Transpose.ROTATE_90)
        else:
            raise OperatorError(f'Unable to correct image orientation with value {orientation}')

        return oriented_asset

    @operator
    def convert(
        self,
        asset: Asset,
        mime_type: MimeType | str,
        color_space: str | None = None,
        depth: int | None = None,
        data_type: str | None = None,
    ) -> Asset:
        """
        Creates a new asset of the specified MIME type from the essence of the
        specified asset.

        :param asset: Asset whose contents will be converted
        :type asset: Asset
        :param mime_type: Target MIME type
        :type mime_type: MimeType or str
        :param color_space: Name of color space
        :type color_space: str or None
        :param depth: Bit depth per channel
        :type depth: int or None
        :param data_type: Data type of the pixels, e.g. 'uint' or 'float'
        :type data_type: str or None
        :return: New asset with converted essence
        :rtype: Asset
        """
        mime_type = MimeType(mime_type)
        try:
            with PIL.Image.open(asset.essence) as image:
                icc_profile_bytes: bytes | None = image.info.get('icc_profile')
                color_mode = color_space or asset.color_space, depth or asset.depth, data_type or asset.data_type
                pil_mode = PillowProcessor.__pillow_mode_to_color_mode.inv.get(color_mode)
                if pil_mode is not None and pil_mode != image.mode:
                    image = image.convert(pil_mode)
                converted_asset = self._image_to_asset(image, mime_type, icc_profile=icc_profile_bytes)
        except (IOError, KeyError) as pil_error:
            raise OperatorError(f'Could not convert image to {mime_type}: {pil_error}')

        return converted_asset

    @operator
    def crop(
        self,
        asset: Asset,
        *,
        width: int,
        height: int,
        x: int | None = None,
        y: int | None = None,
        gravity: Gravity | str = 'north_west',
    ) -> Asset:
        """
        Creates a new asset whose essence is cropped to the specified
        rectangular area.

        When ``x`` and ``y`` are both ``None`` (the default), the crop window
        is positioned using ``gravity``.  When either coordinate is supplied
        explicitly, both must be provided and ``gravity`` is ignored.

        *gravity* may be a :class:`Gravity` member or the equivalent
        plain string (see :class:`Gravity` for the full list of values).

        :param asset: Asset whose contents will be cropped
        :type asset: Asset
        :param width: Width of the cropping area
        :type width: int
        :param height: Height of the cropping area
        :type height: int
        :param x: Horizontal offset of the cropping area from the left edge,
            or ``None`` to derive from ``gravity``
        :type x: int or None
        :param y: Vertical offset of the cropping area from the top edge,
            or ``None`` to derive from ``gravity``
        :type y: int or None
        :param gravity: Anchor position used when ``x`` and ``y`` are not
            specified
        :type gravity: Gravity or str
        :return: New asset with cropped essence
        :rtype: Asset
        """
        if x is None and y is None:
            x, y = _resolve_gravity(asset.width, asset.height, width, height, gravity)
        elif x is None or y is None:
            raise OperatorError('Both x and y must be provided together, or omit both to use gravity')

        if x == 0 and y == 0 and width == asset.width and height == asset.height:
            return asset

        max_x = max(0, min(asset.width, width + x))
        max_y = max(0, min(asset.height, height + y))
        min_x = max(0, min(asset.width, x))
        min_y = max(0, min(asset.height, y))

        if min_x == asset.width or min_y == asset.height or max_x <= min_x or max_y <= min_y:
            raise OperatorError(f'Invalid cropping area: <x={x!r}, y={y!r}, width={width!r}, height={height!r}>')

        with PIL.Image.open(asset.essence) as image:
            cropped_image = image.crop(box=(min_x, min_y, max_x, max_y))
        with cropped_image:
            cropped_asset = self._image_to_asset(cropped_image, mime_type=asset.mime_type)

        return cropped_asset

    @operator
    def composite(
        self,
        asset: Asset,
        overlay_asset: Asset,
        x: int = 0,
        y: int = 0,
        gravity: Gravity | str = 'north_west',
        opacity: float = 1.0,
    ) -> Asset:
        """
        Creates a new asset whose essence has another image composited on top.

        The ``overlay_asset`` is placed over the base image at the position
        determined by ``(x, y)`` or ``gravity``. When both ``x``/``y`` and
        ``gravity`` are specified, ``gravity`` is ignored and ``(x, y)`` is
        used directly. ``opacity`` scales the overlay's alpha channel.

        :param asset: Base image asset
        :type asset: Asset
        :param overlay_asset: Asset to composite over the base
        :type overlay_asset: Asset
        :param x: Horizontal offset of the overlay from the left edge
        :type x: int
        :param y: Vertical offset of the overlay from the top edge
        :type y: int
        :param gravity: Anchor position when ``x`` and ``y`` are both ``0``;
            valid values are ``'north_west'``, ``'north'``, ``'north_east'``,
            ``'west'``, ``'center'``, ``'east'``, ``'south_west'``,
            ``'south'``, ``'south_east'``
        :type gravity: Gravity or str
        :param opacity: Overlay opacity in the range ``[0.0, 1.0]``
        :type opacity: float
        :return: Asset with overlay composited onto the base
        :rtype: Asset
        """
        mime_type = MimeType(asset.mime_type)
        with PIL.Image.open(asset.essence) as base_image, PIL.Image.open(overlay_asset.essence) as overlay_image:
            base_rgba = base_image.convert('RGBA')
            overlay_rgba = overlay_image.convert('RGBA')

            if opacity < 1.0:
                r, g, b, a = overlay_rgba.split()
                a = a.point(lambda v: round(v * opacity))
                overlay_rgba = PIL.Image.merge('RGBA', (r, g, b, a))

            if x == 0 and y == 0:
                x, y = _resolve_gravity(
                    base_rgba.width,
                    base_rgba.height,
                    overlay_rgba.width,
                    overlay_rgba.height,
                    gravity,
                )

            result = base_rgba.copy()
            result.paste(overlay_rgba, (x, y), mask=overlay_rgba)
            final = result.convert(base_image.mode)
        with final:
            return self._image_to_asset(final, mime_type=mime_type)

    @operator
    def fill_background(self, asset: Asset, color: tuple[int, int, int]) -> Asset:
        """
        Creates a new asset whose alpha channel is merged into a solid colour
        background.

        Transparent and semi-transparent pixels are composited over the
        specified background colour. If the source image has no alpha channel,
        the pixels are returned unchanged. The output is always an opaque RGB
        image in the same format as the input.

        :param asset: Asset whose essence will have its background filled
        :type asset: Asset
        :param color: Background colour as an ``(red, green, blue)`` tuple
            with values in the range ``[0, 255]``
        :type color: tuple[int, int, int]
        :return: Asset with alpha composited over the fill colour
        :rtype: Asset
        """
        mime_type = MimeType(asset.mime_type)
        with PIL.Image.open(asset.essence) as image:
            if image.mode not in ('RGBA', 'LA', 'PA'):
                return self._image_to_asset(image, mime_type=mime_type)
            background = PIL.Image.new('RGB', image.size, color)
            background.paste(image.convert('RGBA'), mask=image.convert('RGBA'))
        with background:
            return self._image_to_asset(background, mime_type=mime_type)

    @operator
    def pad(
        self,
        asset: Asset,
        width: int,
        height: int,
        color: tuple[int, int, int] | tuple[int, int, int, int] = (0, 0, 0, 0),
        gravity: Gravity | str = 'center',
    ) -> Asset:
        """
        Creates a new asset whose essence is placed on a larger canvas.

        The source image is pasted onto a canvas of size ``(width, height)``
        filled with ``color``. The position on the canvas is determined by
        ``gravity``.

        *gravity* may be a :class:`Gravity` member or the equivalent
        plain string (see :class:`Gravity` for the full list of values).

        :param asset: Asset whose essence will be padded
        :type asset: Asset
        :param width: Canvas width; must be >= the source image width
        :type width: int
        :param height: Canvas height; must be >= the source image height
        :type height: int
        :param color: Fill color for the added area as an RGB or RGBA tuple
        :type color: tuple
        :param gravity: Anchor position of the source image on the canvas
        :type gravity: Gravity or str
        :return: Asset with padded essence
        :rtype: Asset
        :raises OperatorError: If the canvas is smaller than the source image
        """
        if width < asset.width or height < asset.height:
            raise OperatorError(f'Canvas ({width}×{height}) is smaller than source ({asset.width}×{asset.height})')
        mime_type = MimeType(asset.mime_type)
        with PIL.Image.open(asset.essence) as image:
            canvas_mode = 'RGBA' if len(color) == 4 else 'RGB'
            canvas = PIL.Image.new(canvas_mode, (width, height), color)
            x, y = _resolve_gravity(width, height, image.width, image.height, gravity)
            if image.mode in ('RGBA', 'LA'):
                canvas.paste(image, (x, y), mask=image)
            else:
                canvas.paste(image, (x, y))
        with canvas:
            return self._image_to_asset(canvas, mime_type=mime_type)

    @operator
    def vignette(self, asset: Asset, strength: float = 0.5) -> Asset:
        """
        Creates a new asset whose essence has a radial vignette applied.

        The vignette darkens the edges of the image while leaving the center
        unaffected. ``strength`` controls how much darkening is applied at the
        corners: ``0.0`` leaves the image unchanged; ``1.0`` makes the corners
        completely black.

        :param asset: Asset whose essence will receive the vignette
        :type asset: Asset
        :param strength: Vignette intensity in the range ``[0.0, 1.0]``
        :type strength: float
        :return: Asset with vignette applied
        :rtype: Asset
        """
        mime_type = MimeType(asset.mime_type)
        with PIL.Image.open(asset.essence) as image:
            rgb = image.convert('RGB')
            w, h = rgb.size
            cx, cy = w / 2.0, h / 2.0
            max_dist = math.sqrt(cx * cx + cy * cy)
            mask_pixels = []
            for y in range(h):
                for x in range(w):
                    dist = math.sqrt((x - cx) ** 2 + (y - cy) ** 2)
                    brightness = max(0.0, 1.0 - strength * dist / max_dist) if max_dist > 0 else 1.0
                    mask_pixels.append(round(brightness * 255))
            mask = PIL.Image.new('L', (w, h))
            mask.putdata(mask_pixels)
            black = PIL.Image.new('RGB', (w, h), (0, 0, 0))
            vignetted = PIL.Image.composite(rgb, black, mask)
        with vignetted:
            return self._image_to_asset(vignetted, mime_type=mime_type)

    @operator
    def tint(self, asset: Asset, color: tuple[int, int, int], opacity: float = 0.5) -> Asset:
        """
        Creates a new asset whose essence is tinted with the specified color.

        The tint is blended over the image at the given opacity. An ``opacity``
        of ``0.0`` leaves the image unchanged; ``1.0`` fills it entirely with
        ``color``. The output is always an RGB image in the same format as the
        input.

        :param asset: Asset whose essence will be tinted
        :type asset: Asset
        :param color: RGB tint color as a ``(red, green, blue)`` tuple with
            values in the range ``[0, 255]``
        :type color: tuple[int, int, int]
        :param opacity: Tint opacity in the range ``[0.0, 1.0]``
        :type opacity: float
        :return: Asset with tinted essence
        :rtype: Asset
        """
        mime_type = MimeType(asset.mime_type)
        with PIL.Image.open(asset.essence) as image:
            base = image.convert('RGB')
            tint_layer = PIL.Image.new('RGB', base.size, color)
            alpha = round(opacity * 255)
            tinted = PIL.Image.blend(base, tint_layer, alpha / 255)
        with tinted:
            return self._image_to_asset(tinted, mime_type=mime_type)

    @operator
    def sepia(self, asset: Asset) -> Asset:
        """
        Creates a new asset whose essence has a sepia tone applied.

        The image is first converted to greyscale, then colorised with warm
        brown tones characteristic of historical photographs. The output is
        always an RGB image in the same format as the input.

        :param asset: Asset whose essence will be toned
        :type asset: Asset
        :return: Asset with sepia-toned essence
        :rtype: Asset
        """
        mime_type = MimeType(asset.mime_type)
        with PIL.Image.open(asset.essence) as image:
            grey = image.convert('L')
            sepia_image = PIL.ImageOps.colorize(grey, black=(112, 66, 20), white=(255, 245, 210))
        with sepia_image:
            return self._image_to_asset(sepia_image, mime_type=mime_type)

    @operator
    def sharpen(self, asset: Asset, radius: float = 2, percent: int = 150, threshold: int = 3) -> Asset:
        """
        Creates a new asset whose essence is sharpened using an unsharp mask.

        The unsharp mask works by subtracting a blurred version of the image
        from itself. Higher ``percent`` values produce stronger sharpening;
        ``threshold`` controls which pixel differences are sharpened.

        :param asset: Asset whose essence will be sharpened
        :type asset: Asset
        :param radius: Blur radius for the unsharp mask
        :type radius: float
        :param percent: Strength of the sharpening effect as a percentage
        :type percent: int
        :param threshold: Minimum brightness difference to sharpen
        :type threshold: int
        :return: Asset with sharpened essence
        :rtype: Asset
        """
        mime_type = MimeType(asset.mime_type)
        with PIL.Image.open(asset.essence) as image:
            sharpened = image.filter(PIL.ImageFilter.UnsharpMask(radius, percent, threshold))
        with sharpened:
            return self._image_to_asset(sharpened, mime_type=mime_type)

    @operator
    def blur(self, asset: Asset, radius: float = 2) -> Asset:
        """
        Creates a new asset whose essence is blurred using a Gaussian kernel.

        Higher ``radius`` values produce stronger blur. A ``radius`` of ``0``
        leaves the image unchanged.

        :param asset: Asset whose essence will be blurred
        :type asset: Asset
        :param radius: Blur radius in pixels; ``0`` means no blur
        :type radius: float
        :return: Asset with blurred essence
        :rtype: Asset
        """
        mime_type = MimeType(asset.mime_type)
        with PIL.Image.open(asset.essence) as image:
            blurred = image.filter(PIL.ImageFilter.GaussianBlur(radius))
        with blurred:
            return self._image_to_asset(blurred, mime_type=mime_type)

    @operator
    def adjust_sharpness(self, asset: Asset, factor: float) -> Asset:
        """
        Creates a new asset whose essence has adjusted sharpness.

        A factor of ``0.0`` produces a blurred (smoothed) image. A factor of
        ``1.0`` returns an image identical to the input. Values above ``1.0``
        sharpen the image; values between ``0.0`` and ``1.0`` blur it.

        :param asset: Asset whose sharpness will be adjusted
        :type asset: Asset
        :param factor: Sharpness enhancement factor; ``1.0`` means no change
        :type factor: float
        :return: Asset with adjusted sharpness
        :rtype: Asset
        """
        mime_type = MimeType(asset.mime_type)
        with PIL.Image.open(asset.essence) as image:
            enhanced = PIL.ImageEnhance.Sharpness(image).enhance(factor)
        with enhanced:
            return self._image_to_asset(enhanced, mime_type=mime_type)

    @operator
    def adjust_saturation(self, asset: Asset, factor: float) -> Asset:
        """
        Creates a new asset whose essence has adjusted color saturation.

        A factor of ``0.0`` produces a greyscale image. A factor of ``1.0``
        returns an image identical to the input. Values above ``1.0`` increase
        saturation; values between ``0.0`` and ``1.0`` decrease it.

        :param asset: Asset whose saturation will be adjusted
        :type asset: Asset
        :param factor: Saturation enhancement factor; ``1.0`` means no change
        :type factor: float
        :return: Asset with adjusted saturation
        :rtype: Asset
        """
        mime_type = MimeType(asset.mime_type)
        with PIL.Image.open(asset.essence) as image:
            enhanced = PIL.ImageEnhance.Color(image).enhance(factor)
        with enhanced:
            return self._image_to_asset(enhanced, mime_type=mime_type)

    @operator
    def adjust_contrast(self, asset: Asset, factor: float) -> Asset:
        """
        Creates a new asset whose essence has adjusted contrast.

        A factor of ``0.0`` produces a solid gray image (the mean color of
        the original). A factor of ``1.0`` returns an image identical to the
        input. Values above ``1.0`` increase contrast; values between ``0.0``
        and ``1.0`` decrease it.

        :param asset: Asset whose contrast will be adjusted
        :type asset: Asset
        :param factor: Contrast enhancement factor; ``1.0`` means no change
        :type factor: float
        :return: Asset with adjusted contrast
        :rtype: Asset
        """
        mime_type = MimeType(asset.mime_type)
        with PIL.Image.open(asset.essence) as image:
            enhanced = PIL.ImageEnhance.Contrast(image).enhance(factor)
        with enhanced:
            return self._image_to_asset(enhanced, mime_type=mime_type)

    @operator
    def adjust_brightness(self, asset: Asset, factor: float) -> Asset:
        """
        Creates a new asset whose essence has adjusted brightness.

        A factor of ``0.0`` produces a black image. A factor of ``1.0``
        returns an image identical to the input. Values above ``1.0``
        increase brightness; values between ``0.0`` and ``1.0`` decrease it.

        :param asset: Asset whose brightness will be adjusted
        :type asset: Asset
        :param factor: Brightness enhancement factor; ``1.0`` means no change
        :type factor: float
        :return: Asset with adjusted brightness
        :rtype: Asset
        """
        mime_type = MimeType(asset.mime_type)
        with PIL.Image.open(asset.essence) as image:
            enhanced = PIL.ImageEnhance.Brightness(image).enhance(factor)
        with enhanced:
            return self._image_to_asset(enhanced, mime_type=mime_type)

    @operator
    def crop_to_focal_point(
        self,
        asset: Asset,
        width: int,
        height: int,
        focal_x: float,
        focal_y: float,
    ) -> Asset:
        """
        Creates a new asset cropped to the given dimensions, keeping the
        specified focal point as close to the center of the output as possible.

        The focal point is expressed as relative coordinates in the range
        ``[0.0, 1.0]``, where ``(0.0, 0.0)`` is the top-left corner and
        ``(1.0, 1.0)`` is the bottom-right corner.  The crop window is
        centered on the focal point and clamped so it stays within the image
        bounds.

        This operator is intentionally geometry-only: the caller is responsible
        for computing the focal-point coordinates via face detection, saliency
        analysis, or any other content-aware strategy.

        :param asset: Asset whose essence will be cropped
        :type asset: Asset
        :param width: Crop width in pixels; must not exceed the source width
        :type width: int
        :param height: Crop height in pixels; must not exceed the source height
        :type height: int
        :param focal_x: Horizontal focal-point coordinate in ``[0.0, 1.0]``
        :type focal_x: float
        :param focal_y: Vertical focal-point coordinate in ``[0.0, 1.0]``
        :type focal_y: float
        :return: Asset with cropped essence centered on the focal point
        :rtype: Asset
        :raises OperatorError: If the crop dimensions exceed the source dimensions
        """
        if width > asset.width or height > asset.height:
            raise OperatorError(f'Crop size ({width}x{height}) exceeds source size ({asset.width}x{asset.height})')

        # Pixel coordinates of the focal point
        fx = round(focal_x * (asset.width - 1))
        fy = round(focal_y * (asset.height - 1))

        # Ideal top-left: center the window on the focal point
        x = fx - width // 2
        y = fy - height // 2

        # Clamp to image bounds
        x = max(0, min(x, asset.width - width))
        y = max(0, min(y, asset.height - height))

        mime_type = MimeType(asset.mime_type)
        with PIL.Image.open(asset.essence) as image:
            cropped = image.crop((x, y, x + width, y + height))
        with cropped:
            return self._image_to_asset(cropped, mime_type=mime_type)

    @operator
    def round_corners(self, asset: Asset, radius: int) -> Asset:
        """
        Creates a new asset whose essence has rounded corners.

        The corners are cut to the specified ``radius`` using a smooth
        circular mask. Pixels outside the rounded rectangle become fully
        transparent. The output is always an RGBA PNG image.

        :param asset: Asset whose corners will be rounded
        :type asset: Asset
        :param radius: Corner radius in pixels
        :type radius: int
        :return: RGBA PNG Asset with rounded corners
        :rtype: Asset
        """
        with PIL.Image.open(asset.essence) as image:
            rgba = image.convert('RGBA')
            mask = PIL.Image.new('L', rgba.size, 0)
            draw = PIL.ImageDraw.Draw(mask)
            draw.rounded_rectangle([(0, 0), (rgba.width - 1, rgba.height - 1)], radius=radius, fill=255)
            rgba.putalpha(mask)
        with rgba:
            return self._image_to_asset(rgba, mime_type=MimeType('image/png'))

    @operator
    def apply_mask(self, asset: Asset, mask_asset: Asset) -> Asset:
        """
        Creates a new asset whose alpha channel is replaced by a mask image.

        The luminance of ``mask_asset`` controls the alpha of the output:
        white (255) is fully opaque and black (0) is fully transparent.
        ``mask_asset`` must have the same dimensions as the base image.
        The output is always an RGBA PNG image.

        :param asset: Base image Asset
        :type asset: Asset
        :param mask_asset: Greyscale mask Asset; must match the base dimensions
        :type mask_asset: Asset
        :return: RGBA PNG Asset with the mask applied as its alpha channel
        :rtype: Asset
        """
        with PIL.Image.open(asset.essence) as image, PIL.Image.open(mask_asset.essence) as mask_image:
            rgba = image.convert('RGBA')
            alpha = mask_image.convert('L')
            rgba.putalpha(alpha)
        with rgba:
            return self._image_to_asset(rgba, mime_type=MimeType('image/png'))

    @operator
    def rotate(self, asset: Asset, angle: float, expand: bool = False) -> Asset:
        """
        Creates an asset whose essence is rotated by the specified angle in
        degrees.

        :param asset: Asset whose contents will be rotated
        :type asset: Asset
        :param angle: Angle in degrees, counter clockwise
        :type angle: float
        :param expand: If true, changes the dimensions of the new asset so it
            can hold the entire rotated essence, otherwise the dimensions of
            the original asset will be used.
        :type expand: bool
        :return: New asset with rotated essence
        :rtype: Asset
        """
        if angle % 360.0 == 0.0:
            return asset

        with PIL.Image.open(asset.essence) as image:
            rotated_image = image.rotate(angle=angle, resample=PIL.Image.Resampling.BICUBIC, expand=expand)
        with rotated_image:
            rotated_asset = self._image_to_asset(rotated_image, mime_type=asset.mime_type)

        return rotated_asset

    @operator
    def extract_frame(self, asset: Asset, frame: int = 0) -> Asset:
        """
        Extracts a single frame from an animated image asset as a static image.

        The returned asset has the same MIME type as the source.  Use
        ``frame_count`` from the asset metadata to know how many frames are
        available.

        :param asset: Animated image asset (GIF, WebP, …)
        :type asset: Asset
        :param frame: Zero-based frame index
        :type frame: int
        :return: Static image asset for the requested frame
        :rtype: Asset
        :raises OperatorError: if *frame* is out of range
        """
        with PIL.Image.open(asset.essence) as image:
            n_frames = getattr(image, 'n_frames', 1)
            if frame < 0 or frame >= n_frames:
                raise OperatorError(f'Frame index {frame} is out of range for an image with {n_frames} frame(s)')
            image.seek(frame)
            frame_image = image.copy()

        with frame_image:
            return self._image_to_asset(frame_image, mime_type=asset.mime_type)

    # Output formats that accept a Pillow ``quality`` keyword argument.
    _LOSSY_FORMATS = frozenset(
        {
            MimeType('image/jpeg'),
            MimeType('image/webp'),
            MimeType('image/avif'),
        }
    )

    @operator
    def optimize_quality(
        self,
        asset: Asset,
        min_ssim_score: float = 80.0,
        mime_type: 'str | MimeType | None' = None,
        min_quality: int = 20,
        max_quality: int = 95,
    ) -> Asset:
        """
        Re-encodes *asset* at the lowest quality whose SSIMULACRA2 score against
        the original is at least *min_ssim_score*.

        SSIMULACRA2 is a perceptual quality metric in (−∞, 100] where 100 means
        identical.  Typical thresholds: ≥ 90 nearly imperceptible, ≥ 80 good
        quality, ≥ 70 acceptable.

        The operator binary-searches quality values in
        [*min_quality*, *max_quality*] (Pillow ``quality`` scale, 1–95) and
        returns the highest-compression encoding that still meets the score
        threshold.  If no quality value satisfies the constraint the result is
        encoded at *max_quality* (best achievable).

        Accepts lossless source formats (PNG, TIFF, …) when *mime_type* names a
        lossy target format.  Requires the ``ssimulacra2`` optional dependency
        (``pip install "madam[analysis]"``).

        Supported output formats: JPEG, WebP, AVIF.

        :param asset: Source image asset (any format readable by Pillow)
        :param min_ssim_score: Minimum acceptable SSIMULACRA2 score (default 80.0)
        :param mime_type: Output MIME type; defaults to the asset's own MIME type
        :param min_quality: Lower bound for Pillow quality value (1–95)
        :param max_quality: Upper bound for Pillow quality value (1–95)
        :return: Re-encoded image asset
        :raises OperatorError: if the target format does not support
            quality-based compression, or if ssimulacra2 is not installed
        """
        try:
            import ssimulacra2 as _s2_check  # type: ignore[import-unresolved]  # noqa: F401
        except ImportError as exc:
            raise OperatorError('optimize_quality requires ssimulacra2: pip install "madam[analysis]"') from exc

        target_mime = MimeType(mime_type) if mime_type is not None else MimeType(asset.mime_type)
        if target_mime not in PillowProcessor._LOSSY_FORMATS:
            raise OperatorError(
                f'optimize_quality requires a lossy output format (JPEG, WebP, or AVIF); '
                f'got {target_mime} — pass mime_type= to specify the output format'
            )

        pil_format = PillowProcessor.__mime_type_to_pillow_type[target_mime]
        base_opts: dict = {}
        if target_mime == MimeType('image/jpeg'):
            base_opts = {'optimize': True, 'progressive': True}
        elif target_mime == MimeType('image/webp'):
            base_opts = {'method': 6}

        with PIL.Image.open(asset.essence) as _src:
            _src.load()
            original_rgb = _src.convert('RGB')

        def _encode(quality: int) -> bytes:
            buf = io.BytesIO()
            original_rgb.save(buf, pil_format, quality=quality, **base_opts)
            return buf.getvalue()

        def _score(quality: int) -> float:
            decoded = PIL.Image.open(io.BytesIO(_encode(quality)))
            decoded.load()
            return _ssimulacra2_score(original_rgb, decoded)

        lo, hi = min_quality, max_quality
        best_quality = max_quality  # fallback: best available when nothing meets threshold
        while lo <= hi:
            mid = (lo + hi) // 2
            if _score(mid) >= min_ssim_score:
                best_quality = mid
                hi = mid - 1  # acceptable — try lower quality (more compression)
            else:
                lo = mid + 1  # score too low — need higher quality

        result_buf = io.BytesIO(_encode(best_quality))
        return self.read(result_buf)


def _ssimulacra2_score(img_a: PIL.Image.Image, img_b: PIL.Image.Image) -> float:
    """Compute an SSIMULACRA2 score between two PIL images without temporary files.

    Uses the ``ssimulacra2`` library's internal functions directly with numpy
    arrays to avoid disk I/O.  Both images are converted to RGB before scoring.

    :param img_a: Reference (original) image
    :param img_b: Distorted (compressed) image
    :return: SSIMULACRA2 score in (−∞, 100] where 100 means identical;
        typical thresholds: ≥ 90 nearly imperceptible, ≥ 80 good quality
    :raises ImportError: if ssimulacra2 is not installed
    """
    import numpy as np
    from ssimulacra2.ssimulacra2 import (  # type: ignore[import-unresolved]
        Msssim,
        MsssimScale,
        blur_image,
        downsample,
        edge_diff_map,
        kNumScales,
        linear_rgb_to_xyb,
        make_positive_xyb,
        srgb_to_linear,
        ssim_map,
    )

    orig_arr = np.array(img_a.convert('RGB'), dtype=np.float64)
    dist_arr = np.array(img_b.convert('RGB'), dtype=np.float64)

    orig_linear = srgb_to_linear(orig_arr)
    dist_linear = srgb_to_linear(dist_arr)
    img1 = make_positive_xyb(linear_rgb_to_xyb(orig_linear))
    img2 = make_positive_xyb(linear_rgb_to_xyb(dist_linear))

    msssim = Msssim()
    for scale in range(kNumScales):
        if img1.shape[0] < 8 or img1.shape[1] < 8:
            break
        mu1, mu2 = blur_image(img1), blur_image(img2)
        sd = MsssimScale()
        sd.avg_ssim = ssim_map(mu1, mu2, blur_image(img1 * img1), blur_image(img2 * img2), blur_image(img1 * img2))
        sd.avg_edgediff = edge_diff_map(img1, mu1, img2, mu2)
        msssim.scales.append(sd)
        if scale < kNumScales - 1:
            orig_linear = downsample(orig_linear, 2, 2)
            dist_linear = downsample(dist_linear, 2, 2)
            img1 = make_positive_xyb(linear_rgb_to_xyb(orig_linear))
            img2 = make_positive_xyb(linear_rgb_to_xyb(dist_linear))

    return msssim.score()


def extract_palette(asset: Asset, count: int = 5) -> list[tuple[int, int, int]]:
    """Extract the dominant colors from an image asset.

    Quantizes the image to *count* representative colors using Pillow's median-cut
    algorithm and returns them as ``(r, g, b)`` tuples sorted by frequency (most
    frequent color first).

    The returned list contains at most *count* entries; it may be shorter if the
    image has fewer unique colors than *count*.

    :param asset: Source image asset (any format readable by Pillow)
    :param count: Maximum number of colors to return (default 5)
    :return: List of ``(r, g, b)`` tuples sorted by pixel frequency, descending

    .. versionadded:: 0.24
    """
    from collections import Counter

    with PIL.Image.open(asset.essence) as image:
        rgb = image.convert('RGB')

    quantized = rgb.quantize(colors=count)
    palette = quantized.getpalette()  # flat [r, g, b, r, g, b, …] for 256 slots
    if palette is None:
        return []

    pixel_counts: Counter[int] = Counter(quantized.get_flattened_data())  # type: ignore[arg-type]

    # Sort palette indices by descending frequency, then map to RGB tuples.
    sorted_indices = sorted(pixel_counts, key=lambda i: pixel_counts[i], reverse=True)
    return [(palette[i * 3], palette[i * 3 + 1], palette[i * 3 + 2]) for i in sorted_indices]


def render_text(
    text: str,
    font_path: str | None = None,
    font_size: int = 24,
    color: tuple[int, int, int] = (0, 0, 0),
    background: tuple[int, int, int, int] = (0, 0, 0, 0),
    padding: int = 0,
) -> Asset:
    """
    Renders the given text into a new RGBA PNG image Asset.

    The canvas is sized to fit the text exactly, with an optional uniform
    ``padding`` added on all sides. A system font is used when ``font_path``
    is ``None``.

    :param text: Text string to render
    :type text: str
    :param font_path: Path to a TrueType or OpenType font file, or ``None``
        to use the default Pillow font
    :type font_path: str or None
    :param font_size: Font size in points (ignored when ``font_path`` is
        ``None`` because the default font has a fixed size)
    :type font_size: int
    :param color: Text color as an ``(red, green, blue)`` tuple
    :type color: tuple[int, int, int]
    :param background: Canvas background color as an ``(r, g, b, alpha)``
        tuple; defaults to fully transparent
    :type background: tuple[int, int, int, int]
    :param padding: Uniform padding in pixels added around the text
    :type padding: int
    :return: RGBA PNG Asset containing the rendered text
    :rtype: Asset

    .. versionadded:: 0.24
    """
    if font_path is not None:
        font = PIL.ImageFont.truetype(font_path, size=font_size)
    else:
        font = PIL.ImageFont.load_default(size=font_size)

    # Measure text extents using a temporary draw surface
    dummy = PIL.Image.new('RGBA', (1, 1))
    draw = PIL.ImageDraw.Draw(dummy)
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    canvas_width = int(text_width + 2 * padding)
    canvas_height = int(text_height + 2 * padding)
    image = PIL.Image.new('RGBA', (max(1, canvas_width), max(1, canvas_height)), background)
    draw = PIL.ImageDraw.Draw(image)
    draw.text((padding - bbox[0], padding - bbox[1]), text, font=font, fill=color + (255,))

    essence = io.BytesIO()
    image.save(essence, 'PNG')
    essence.seek(0)
    return Asset(
        essence,
        mime_type='image/png',
        width=image.width,
        height=image.height,
        color_space='RGBA',
        depth=8,
        data_type='uint',
    )


_ANIMATED_MIME_TYPES: frozenset[str] = frozenset({'image/gif', 'image/webp'})
_MIME_TYPE_TO_PIL_FORMAT: dict[str, str] = {
    'image/gif': 'GIF',
    'image/webp': 'WEBP',
}


def combine(
    assets: Iterable[Asset],
    mime_type: str,
    *,
    duration: int = 100,
    loop: int = 0,
) -> Asset:
    """
    Assembles a sequence of image assets into an animated GIF or WebP.

    :param assets: Iterable of image assets to use as frames; must be non-empty
    :type assets: Iterable[Asset]
    :param mime_type: Output format: ``'image/gif'`` or ``'image/webp'``
    :type mime_type: str
    :param duration: Per-frame delay in milliseconds (default 100)
    :type duration: int
    :param loop: Number of animation loops; 0 means infinite (default 0)
    :type loop: int
    :return: Animated image asset
    :rtype: Asset
    :raises ValueError: If *assets* is empty
    :raises UnsupportedFormatError: If *mime_type* is not ``'image/gif'`` or ``'image/webp'``
    :raises OperatorError: If Pillow cannot decode an asset

    .. versionadded:: 1.0
    """
    asset_list = list(assets)
    if not asset_list:
        raise ValueError('Cannot combine an empty sequence of assets')

    if mime_type not in _ANIMATED_MIME_TYPES:
        raise UnsupportedFormatError(
            f'Unsupported animated format: {mime_type!r}. '
            f'Supported formats: {sorted(_ANIMATED_MIME_TYPES)}'
        )

    pil_format = _MIME_TYPE_TO_PIL_FORMAT[mime_type]
    frames: list[PIL.Image.Image] = []
    for asset in asset_list:
        try:
            img = PIL.Image.open(asset.essence)
            img.load()
            asset.essence.seek(0)
        except Exception as exc:
            raise OperatorError(f'Cannot decode image asset: {exc}') from exc

        if mime_type == 'image/webp':
            if img.mode not in ('RGB', 'RGBA'):
                img = img.convert('RGBA' if 'A' in img.mode or img.mode == 'P' else 'RGB')
        else:
            # GIF: Pillow handles palette conversion internally
            if img.mode == 'RGBA':
                img = img.convert('RGB')
        frames.append(img)

    buf = io.BytesIO()
    frames[0].save(
        buf,
        format=pil_format,
        save_all=True,
        append_images=frames[1:],
        duration=duration,
        loop=loop,
    )
    buf.seek(0)
    return PillowProcessor().read(buf)
