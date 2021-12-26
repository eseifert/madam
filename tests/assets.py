import datetime
import io
import subprocess
from xml.etree import ElementTree as ET

import PIL.Image
import pytest

import madam.core


DEFAULT_WIDTH = 24
DEFAULT_HEIGHT = 12
DEFAULT_DURATION = 0.2


def image_rgb(width, height, alpha=False, transpositions=None):
    if not transpositions:
        transpositions = []
    pil_mode = {
        False: 'RGB',
        True: 'RGBA',
    }.get(alpha)
    if pil_mode is None:
        raise ValueError(f'Unsupported color mode: {alpha!r}')
    image = PIL.Image.new(pil_mode, (width, height))
    # Fill the image with a shape which is (probably) not invariant towards
    # rotations or flips as long as the image has a size of (2, 2) or greater
    max_value = 255
    for y in range(0, height):
        alpha_value = round(y / height * max_value)
        for x in range(0, width):
            if y == 0 or x == 0:
                color = max_value, max_value, max_value
            else:
                color = 0, 0, 0
            if alpha:
                color = tuple(list(color) + [alpha_value])
            image.putpixel((x, y), color)
    for transposition in transpositions:
        image = image.transpose(transposition)
    return image


def image_gray(width, height, depth=8, alpha=False):
    pil_mode = {
        (8, False): 'L',
        (8, True): 'LA',
        (16, False): 'I;16',
        (32, False): 'I',
    }.get((depth, alpha))
    if pil_mode is None:
        raise ValueError(f'Unsupported color mode: {(depth, alpha)!r}')
    image = PIL.Image.new(pil_mode, (width, height))
    # Fill the image with a shape which is (probably) not invariant towards
    # rotations or flips as long as the image has a size of (2, 2) or greater
    max_value = 2 ** depth - 1
    black = 0
    white = max_value
    for y in range(0, height):
        alpha_value = round(y / height * max_value)
        for x in range(0, width):
            if y == 0 or x == 0:
                color = white
            else:
                color = black
            if alpha:
                color = color, alpha_value
            image.putpixel((x, y), color)
    return image


def image_palette(width, height, colors=7):
    if colors > 256:
        raise ValueError('Too many colors: maximum is 256')
    image = PIL.Image.new('P', (width, height))
    max_value = 255
    palette = []
    for i in range(colors):
        palette.extend((max_value - i, i % width, i))
    image.putpalette(palette)
    color_index = 0
    for y in range(0, height):
        for x in range(0, width):
            image.putpixel((x, y), color_index)
            color_index = (color_index + 1) % colors
    return image


def image_cmyk(width, height):
    image = PIL.Image.new('CMYK', (width, height))
    # Fill the image with a shape which is (probably) not invariant towards
    # rotations or flips as long as the image has a size of (2, 2) or greater
    max_value = 255
    for y in range(0, height):
        for x in range(0, width):
            if y == 0 or x == 0:
                color = 0, 0, 0, 0
            else:
                color = 0, 0, 0, max_value
            image.putpixel((x, y), color)
    return image


def get_jpeg_image_asset(width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT, transpositions=None, **additional_metadata):
    if not transpositions:
        transpositions = []
    image = image_rgb(width=width, height=height, transpositions=transpositions)
    essence = io.BytesIO()
    image.save(essence, 'JPEG', quality=100)
    essence.seek(0)
    metadata = dict(
        exif={
            'aperture': 0.02,
            'artist': 'Test Artist',
            'brightness': 2.15,
            'camera.manufacturer': 'Test Manufacturer, Inc.',
            'camera.model': 'TestCamera 40 Mark II',
            'description': 'A plastic bag in the street',
            'exposure_time': 0.4,
            'firmware': 'TestCamera v1.07',
            'fnumber': 2.8,
            'focal_length': 28,
            'focal_length_35mm': 42,
            'gps.altitude': 519,
            'gps.altitude_ref': 'm_above_sea_level',
            'gps.latitude': (48, 8, 6),
            'gps.latitude_ref': 'north',
            'gps.longitude': (11, 34, 55),
            'gps.longitude_ref': 'east',
            'gps.map_datum': 'WGS-84',
            'gps.speed': 0.042,
            'gps.speed_ref': 'km/h',
            'gps.date_stamp': datetime.date(2000, 1, 1),
            'gps.time_stamp': datetime.time(23, 59, 42),
            'lens.manufacturer': 'Yeiss',
            'lens.model': 'Yokton AF 17-50mm F2.8',
            'shutter_speed': 0.01,
            'software': 'MADAM',
        },
        iptc={
            'bylines': ('The', 'Creators'),
            'byline_titles': ('Dr.', 'Prof.'),
            'caption': 'A test image.',
            'contacts': ('Me', 'Myself'),
            'copyright': 'Nobody',
            'creation_date': datetime.date(2000, 1, 1),
            'creation_time': datetime.time(23, 59, 43),
            'credit': 'Devs',
            'expiration_date': datetime.date(2100, 1, 1),
            'expiration_time': datetime.time(23, 59, 44),
            'headline': 'Wonderful Test Image',
            'keywords': ('test', 'image', 'kws'),
            'language': 'English',
            'release_date': datetime.date(2016, 1, 1),
            'release_time': datetime.time(23, 59, 45),
            'source': 'Test suite',
            'subjects': ('The', 'topics'),
        },
        mime_type='image/jpeg',
        width=width,
        height=height,
        color_space='RGB',
        depth=8,
        data_type='uint',
    )
    metadata.update(additional_metadata)
    return madam.core.Asset(essence, **metadata)


@pytest.fixture(scope='session')
def jpeg_image_asset():
    return get_jpeg_image_asset(width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT, transpositions=None)


@pytest.fixture(scope='session')
def jpeg_data_with_exif():
    with open('tests/resources/image_with_exif.jpg', 'rb') as file:
        binary_data = file.read()
    return io.BytesIO(binary_data)


@pytest.fixture(scope='session')
def png_image_asset_rgb(width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT):
    image = image_rgb(width=width, height=height)
    essence = io.BytesIO()
    image.save(essence, 'PNG')
    essence.seek(0)
    metadata = dict(
        mime_type='image/png',
        width=image.width,
        height=image.height,
        color_space='RGB',
        depth=8,
        data_type='uint',
    )
    return madam.core.Asset(essence, **metadata)


@pytest.fixture(scope='session')
def png_image_asset_rgb_alpha(width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT):
    image = image_rgb(width=width, height=height, alpha=True)
    essence = io.BytesIO()
    image.save(essence, 'PNG')
    essence.seek(0)
    metadata = dict(
        mime_type='image/png',
        width=image.width,
        height=image.height,
        color_space='RGBA',
        depth=8,
        data_type='uint',
    )
    return madam.core.Asset(essence, **metadata)


@pytest.fixture(scope='session')
def png_image_asset_palette(width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT):
    image = image_palette(width=width, height=height)
    essence = io.BytesIO()
    image.save(essence, 'PNG')
    essence.seek(0)
    metadata = dict(
        mime_type='image/png',
        width=image.width,
        height=image.height,
        color_space='PALETTE',
        depth=8,
        data_type='uint',
    )
    return madam.core.Asset(essence, **metadata)


@pytest.fixture(scope='session')
def png_image_asset_gray(width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT):
    depth = 8
    image = image_gray(width=width, height=height, depth=depth)
    essence = io.BytesIO()
    image.save(essence, 'PNG')
    essence.seek(0)
    metadata = dict(
        mime_type='image/png',
        width=image.width,
        height=image.height,
        color_space='LUMA',
        depth=depth,
        data_type='uint',
    )
    return madam.core.Asset(essence, **metadata)


@pytest.fixture(scope='session')
def png_image_asset_gray_alpha(width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT):
    depth = 8
    image = image_gray(width=width, height=height, depth=depth, alpha=True)
    essence = io.BytesIO()
    image.save(essence, 'PNG')
    essence.seek(0)
    metadata = dict(
        mime_type='image/png',
        width=image.width,
        height=image.height,
        color_space='LUMAA',
        depth=depth,
        data_type='uint',
    )
    return madam.core.Asset(essence, **metadata)


@pytest.fixture(scope='session', params=['png_image_asset_rgb', 'png_image_asset_rgb_alpha', 'png_image_asset_palette',
                                         'png_image_asset_gray', 'png_image_asset_gray_alpha'])
def png_image_asset(request, png_image_asset_rgb, png_image_asset_rgb_alpha, png_image_asset_palette,
                    png_image_asset_gray, png_image_asset_gray_alpha):
    if request.param == 'png_image_asset_rgb':
        return png_image_asset_rgb
    if request.param == 'png_image_asset_rgb_alpha':
        return png_image_asset_rgb_alpha
    if request.param == 'png_image_asset_palette':
        return png_image_asset_palette
    if request.param == 'png_image_asset_gray':
        return png_image_asset_gray
    if request.param == 'png_image_asset_gray_alpha':
        return png_image_asset_gray_alpha
    raise ValueError()


@pytest.fixture(scope='session')
def gif_image_asset(width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT):
    image = image_rgb(width=width, height=height)
    essence = io.BytesIO()
    image.save(essence, 'GIF')
    essence.seek(0)
    metadata = dict(
        mime_type='image/gif',
        width=image.width,
        height=image.height,
        color_space='PALETTE',
        depth=8,
        data_type='uint',
    )
    return madam.core.Asset(essence, **metadata)


@pytest.fixture(scope='session')
def bmp_image_asset(width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT):
    image = image_rgb(width=width, height=height)
    essence = io.BytesIO()
    image.save(essence, 'BMP')
    essence.seek(0)
    metadata = dict(
        mime_type='image/bmp',
        width=image.width,
        height=image.height,
        color_space='RGB',
        depth=8,
        data_type='uint',
    )
    return madam.core.Asset(essence, **metadata)


@pytest.fixture(scope='session')
def tiff_image_asset_rgb(width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT):
    image = image_rgb(width=width, height=height)
    essence = io.BytesIO()
    image.save(essence, 'TIFF')
    essence.seek(0)
    metadata = dict(
        mime_type='image/tiff',
        width=image.width,
        height=image.height,
        color_space='RGB',
        depth=8,
        data_type='uint',
    )
    return madam.core.Asset(essence, **metadata)


@pytest.fixture(scope='session')
def tiff_image_asset_rgb_alpha(width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT):
    image = image_rgb(width=width, height=height, alpha=True)
    essence = io.BytesIO()
    image.save(essence, 'TIFF')
    essence.seek(0)
    metadata = dict(
        mime_type='image/tiff',
        width=image.width,
        height=image.height,
        color_space='RGBA',
        depth=8,
        data_type='uint',
    )
    return madam.core.Asset(essence, **metadata)


@pytest.fixture(scope='session')
def tiff_image_asset_palette(width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT):
    image = image_palette(width=width, height=height)
    essence = io.BytesIO()
    image.save(essence, 'TIFF')
    essence.seek(0)
    metadata = dict(
        mime_type='image/tiff',
        width=image.width,
        height=image.height,
        color_space='PALETTE',
        depth=8,
        data_type='uint',
    )
    return madam.core.Asset(essence, **metadata)


@pytest.fixture(scope='session')
def tiff_image_asset_gray_8bit(width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT):
    depth = 8
    image = image_gray(width=width, height=height, depth=depth)
    essence = io.BytesIO()
    image.save(essence, 'TIFF')
    essence.seek(0)
    metadata = dict(
        mime_type='image/tiff',
        width=image.width,
        height=image.height,
        color_space='LUMA',
        depth=depth,
        data_type='uint',
    )
    return madam.core.Asset(essence, **metadata)


@pytest.fixture(scope='session')
def tiff_image_asset_gray_8bit_alpha(width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT):
    depth = 8
    image = image_gray(width=width, height=height, depth=depth, alpha=True)
    essence = io.BytesIO()
    image.save(essence, 'TIFF')
    essence.seek(0)
    metadata = dict(
        mime_type='image/tiff',
        width=image.width,
        height=image.height,
        color_space='LUMAA',
        depth=depth,
        data_type='uint',
    )
    return madam.core.Asset(essence, **metadata)


@pytest.fixture(scope='session')
def tiff_image_asset_gray_16bit(width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT):
    depth = 16
    image = image_gray(width=width, height=height, depth=depth)
    essence = io.BytesIO()
    image.save(essence, 'TIFF')
    essence.seek(0)
    metadata = dict(
        mime_type='image/tiff',
        width=image.width,
        height=image.height,
        color_space='LUMA',
        depth=depth,
        data_type='uint',
    )
    return madam.core.Asset(essence, **metadata)


@pytest.fixture(scope='session')
def tiff_image_asset_cmyk(width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT):
    image = image_cmyk(width=width, height=height)
    essence = io.BytesIO()
    image.save(essence, 'TIFF')
    essence.seek(0)
    metadata = dict(
        mime_type='image/tiff',
        width=image.width,
        height=image.height,
        color_space='CMYK',
        depth=8,
        data_type='uint',
    )
    return madam.core.Asset(essence, **metadata)


@pytest.fixture(scope='session', params=['tiff_image_asset_rgb', 'tiff_image_asset_rgb_alpha',
                                         'tiff_image_asset_palette', 'tiff_image_asset_gray_8bit',
                                         'tiff_image_asset_gray_8bit_alpha', 'tiff_image_asset_gray_16bit',
                                         'tiff_image_asset_cmyk'])
def tiff_image_asset(request, tiff_image_asset_rgb, tiff_image_asset_rgb_alpha, tiff_image_asset_palette,
                     tiff_image_asset_gray_8bit, tiff_image_asset_gray_8bit_alpha, tiff_image_asset_gray_16bit,
                     tiff_image_asset_cmyk):
    if request.param == 'tiff_image_asset_rgb':
        return tiff_image_asset_rgb
    if request.param == 'tiff_image_asset_rgb_alpha':
        return tiff_image_asset_rgb_alpha
    if request.param == 'tiff_image_asset_palette':
        return tiff_image_asset_palette
    if request.param == 'tiff_image_asset_gray_8bit':
        return tiff_image_asset_gray_8bit
    if request.param == 'tiff_image_asset_gray_8bit_alpha':
        return tiff_image_asset_gray_8bit_alpha
    if request.param == 'tiff_image_asset_gray_16bit':
        return tiff_image_asset_gray_16bit
    if request.param == 'tiff_image_asset_cmyk':
        return tiff_image_asset_cmyk
    raise ValueError()


@pytest.fixture(scope='session')
def webp_image_asset_rgb(width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT):
    image = image_rgb(width=width, height=height)
    essence = io.BytesIO()
    image.save(essence, 'WebP')
    essence.seek(0)
    metadata = dict(
        mime_type='image/webp',
        width=image.width,
        height=image.height,
        color_space='RGB',
        depth=8,
        data_type='uint',
    )
    return madam.core.Asset(essence, **metadata)


@pytest.fixture(scope='session')
def webp_image_asset_rgb_alpha(width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT):
    image = image_rgb(width=width, height=height, alpha=True)
    essence = io.BytesIO()
    image.save(essence, 'WebP')
    essence.seek(0)
    metadata = dict(
        mime_type='image/webp',
        width=image.width,
        height=image.height,
        color_space='RGBA',
        depth=8,
        data_type='uint',
    )
    return madam.core.Asset(essence, **metadata)


@pytest.fixture(scope='session', params=['webp_image_asset_rgb', 'webp_image_asset_rgb_alpha'])
def webp_image_asset(request, webp_image_asset_rgb, webp_image_asset_rgb_alpha):
    if request.param == 'webp_image_asset_rgb':
        return webp_image_asset_rgb
    if request.param == 'webp_image_asset_rgb_alpha':
        return webp_image_asset_rgb_alpha
    raise ValueError()


@pytest.fixture(scope='session')
def svg_vector_asset():
    metadata = dict(rdf=
        dict(xml=
             '<rdf:Description rdf:about="svg_with_metadata.svg">'
             '<dc:format>image/svg+xml</dc:format>'
             '<dc:type>Image</dc:type>'
             '<dc:creator opf:role="aut">John Doe</dc:creator>'
             '<dc:description>Example SVG file with metadata</dc:description>'
             '<dc:rights>Copyright 2016 Erich Seifert</dc:rights>'
             '<dc:date opf:event="creation">2016-11-01</dc:date>'
             '<dc:title>SVG metadata example</dc:title>'
             '<dc:subject>SVG, metadata, RDF, Dublin Core, example</dc:subject>'
             '<dc:source>Various</dc:source>'
             '<dc:date opf:event="publication">2016-11-02</dc:date>'
             '<dc:date opf:event="expiration">2020-11-01</dc:date>'
             '<dc:language>en</dc:language>'
             '<dc:subject>test resources</dc:subject>'
             '</rdf:Description>'
        )
    )

    xml_ns = dict(
        svg='http://www.w3.org/2000/svg'
    )
    for ns_prefix, ns_uri in xml_ns.items():
        if ns_prefix == 'svg':
            ns_prefix = ''
        ET.register_namespace(ns_prefix, ns_uri)

    with open('tests/resources/svg_with_metadata.svg', 'rb') as file:
        tree = ET.parse(file)

    # Remove metadata from essence
    root = tree.getroot()
    metadata_elem = root.find('./svg:metadata', xml_ns)
    if metadata_elem is not None:
        root.remove(metadata_elem)

    # Write SVG without metadata
    essence = io.BytesIO()
    tree.write(essence, xml_declaration=False, encoding='utf-8')
    essence.seek(0)

    return madam.core.Asset(essence=essence, mime_type='image/svg+xml',
                            width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT,
                            **metadata)


@pytest.fixture(scope='session')
def unknown_xml_asset():
    essence = io.BytesIO()
    essence.write(b'<foo><bar/></foo>')
    essence.seek(0)
    return madam.core.Asset(essence, mime_type='text/xml')


@pytest.fixture(scope='session', params=['jpeg_image_asset', 'png_image_asset', 'gif_image_asset',
                                         'bmp_image_asset', 'tiff_image_asset', 'webp_image_asset'])
def image_asset(request, jpeg_image_asset, png_image_asset, gif_image_asset,
                bmp_image_asset, tiff_image_asset, webp_image_asset):
    if request.param == 'jpeg_image_asset':
        return jpeg_image_asset
    if request.param == 'png_image_asset':
        return png_image_asset
    if request.param == 'gif_image_asset':
        return gif_image_asset
    if request.param == 'bmp_image_asset':
        return bmp_image_asset
    if request.param == 'tiff_image_asset':
        return tiff_image_asset
    if request.param == 'webp_image_asset':
        return webp_image_asset
    raise ValueError()


@pytest.fixture(scope='session')
def wav_audio_asset(tmpdir_factory):
    duration = DEFAULT_DURATION
    command = ('ffmpeg -loglevel error -f lavfi -i sine=frequency=440:duration=%.1f '
               '-vn -sn -c:a pcm_s16le -f wav' % duration).split()
    tmpfile = tmpdir_factory.mktemp('wav_asset').join('without_metadata.wav')
    command.append(str(tmpfile))
    subprocess.run(command, check=True, stderr=subprocess.PIPE)
    with tmpfile.open('rb') as file:
        essence = file.read()
    return madam.core.Asset(essence=io.BytesIO(essence), mime_type='audio/wav',
                            duration=duration, audio=dict(codec='pcm_s16le'))


@pytest.fixture(scope='session')
def mp3_audio_asset(tmpdir_factory):
    duration = DEFAULT_DURATION
    command = ('ffmpeg -loglevel error -f lavfi -i sine=frequency=440:duration=%.1f '
               '-write_xing 0 -id3v2_version 0 -write_id3v1 0 '
               '-vn -sn -f mp3' % duration).split()
    tmpfile = tmpdir_factory.mktemp('mp3_asset').join('without_metadata.mp3')
    command.append(str(tmpfile))
    subprocess.run(command, check=True, stderr=subprocess.PIPE)
    with tmpfile.open('rb') as file:
        essence = file.read()
    return madam.core.Asset(essence=io.BytesIO(essence), mime_type='audio/mpeg',
                            duration=duration, audio=dict(codec='mp3'))


@pytest.fixture(scope='session')
def opus_audio_asset(tmpdir_factory):
    duration = DEFAULT_DURATION
    command = ('ffmpeg -loglevel error -f lavfi -i sine=frequency=440:duration=%.1f '
               '-vn -sn -f opus' % duration).split()
    tmpfile = tmpdir_factory.mktemp('opus_asset').join('without_metadata.opus')
    command.append(str(tmpfile))
    subprocess.run(command, check=True, stderr=subprocess.PIPE)
    with tmpfile.open('rb') as file:
        essence = file.read()
    return madam.core.Asset(essence=io.BytesIO(essence), mime_type='audio/ogg',
                            duration=duration, audio=dict(codec='opus'))


@pytest.fixture(scope='session')
def nut_audio_asset(tmpdir_factory):
    duration = DEFAULT_DURATION
    command = ('ffmpeg -loglevel error -f lavfi -i sine=frequency=440:duration=%.1f '
               '-vn -sn -c:a pcm_s16le -f nut' % duration).split()
    tmpfile = tmpdir_factory.mktemp('nut_asset').join('without_metadata.nut')
    command.append(str(tmpfile))
    subprocess.run(command, check=True, stderr=subprocess.PIPE)
    with tmpfile.open('rb') as file:
        essence = file.read()
    return madam.core.Asset(essence=io.BytesIO(essence), mime_type='audio/x-nut',
                            duration=duration, audio=dict(codec='pcm_s16le'))


@pytest.fixture(scope='session', params=['mp3_audio_asset', 'nut_audio_asset', 'opus_audio_asset', 'wav_audio_asset'])
def audio_asset(request, mp3_audio_asset, nut_audio_asset, opus_audio_asset, wav_audio_asset):
    if request.param == 'mp3_audio_asset':
        return mp3_audio_asset
    if request.param == 'nut_audio_asset':
        return nut_audio_asset
    if request.param == 'opus_audio_asset':
        return opus_audio_asset
    if request.param == 'wav_audio_asset':
        return wav_audio_asset
    raise ValueError()


@pytest.fixture(scope='session')
def mp4_video_asset(tmpdir_factory):
    ffmpeg_params = dict(
        width=DEFAULT_WIDTH,
        height=DEFAULT_HEIGHT,
        duration=DEFAULT_DURATION,
        subtitle_path='tests/resources/subtitle.vtt',
    )
    command = ('ffmpeg -loglevel error '
               '-f lavfi -i color=color=red:size=%(width)dx%(height)d:duration=%(duration).1f:rate=15 '
               '-f lavfi -i sine=frequency=440:duration=%(duration).1f '
               '-f webvtt -i %(subtitle_path)s '
               '-strict -2 -c:v h264 -preset ultrafast -qp 0 -c:a aac -c:s mov_text '
               '-f mp4' % ffmpeg_params).split()
    tmpfile = tmpdir_factory.mktemp('mp4_video_asset').join('h264-aac-mov_text.mp4')
    command.append(str(tmpfile))
    subprocess.run(command, check=True, stderr=subprocess.PIPE)
    with tmpfile.open('rb') as file:
        essence = file.read()
    return madam.core.Asset(essence=io.BytesIO(essence), mime_type='video/quicktime',
                            width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT, duration=DEFAULT_DURATION,
                            video=dict(codec='h264', color_space='YUV', depth=8, data_type='uint'),
                            audio=dict(codec='aac'),
                            subtitle=dict(codec='mov_text'))


@pytest.fixture(scope='session')
def avi_video_asset(tmpdir_factory):
    ffmpeg_params = dict(
        width=DEFAULT_WIDTH,
        height=DEFAULT_HEIGHT,
        duration=DEFAULT_DURATION,
    )
    command = ('ffmpeg -loglevel error '
               '-f lavfi -i color=color=red:size=%(width)dx%(height)d:duration=%(duration).1f:rate=15 '
               '-f lavfi -i sine=frequency=440:duration=%(duration).1f '
               '-c:v h264 -c:a mp3 -sn '
               '-f avi' % ffmpeg_params).split()
    tmpfile = tmpdir_factory.mktemp('avi_video_asset').join('h264-mp3.avi')
    command.append(str(tmpfile))
    subprocess.run(command, check=True, stderr=subprocess.PIPE)
    with tmpfile.open('rb') as file:
        essence = file.read()
    return madam.core.Asset(essence=io.BytesIO(essence), mime_type='video/x-msvideo',
                            width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT, duration=DEFAULT_DURATION,
                            video=dict(codec='h264', color_space='YUV', depth=8, data_type='uint'),
                            audio=dict(codec='mp3'))


@pytest.fixture(scope='session')
def mkv_video_asset(tmpdir_factory):
    ffmpeg_params = dict(
        width=DEFAULT_WIDTH,
        height=DEFAULT_HEIGHT,
        duration=DEFAULT_DURATION,
        subtitle_path='tests/resources/subtitle.vtt',
    )
    command = ('ffmpeg -loglevel error '
               '-f lavfi -i color=color=red:size=%(width)dx%(height)d:duration=%(duration).1f:rate=15 '
               '-f lavfi -i sine=frequency=440:duration=%(duration).1f '
               '-f webvtt -i %(subtitle_path)s '
               '-c:v vp9 -c:a libopus -c:s webvtt '
               '-f matroska' % ffmpeg_params).split()
    tmpfile = tmpdir_factory.mktemp('mkv_video_asset').join('vp9-opus-webvtt.mkv')
    command.append(str(tmpfile))
    subprocess.run(command, check=True, stderr=subprocess.PIPE)
    with tmpfile.open('rb') as file:
        essence = file.read()
    return madam.core.Asset(essence=io.BytesIO(essence), mime_type='video/x-matroska',
                            width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT, duration=DEFAULT_DURATION,
                            video=dict(codec='vp9', color_space='YUV', depth=8, data_type='uint'),
                            audio=dict(codec='libopus'),
                            subtitle=dict(codec='webvtt'))


@pytest.fixture(scope='session')
def mp2_video_asset(tmpdir_factory):
    ffmpeg_params = dict(
        width=DEFAULT_WIDTH,
        height=DEFAULT_HEIGHT,
        duration=DEFAULT_DURATION,
    )
    command = ('ffmpeg -loglevel error '
               '-f lavfi -i color=color=red:size=%(width)dx%(height)d:duration=%(duration).1f:rate=15 '
               '-f lavfi -i sine=frequency=440:duration=%(duration).1f '
               '-c:v mpeg2video -c:a mp2 -sn '
               '-f mpegts' % ffmpeg_params).split()
    tmpfile = tmpdir_factory.mktemp('mp2_video_asset').join('mpeg2-mp2-dvbsub.ts')
    command.append(str(tmpfile))
    subprocess.run(command, check=True, stderr=subprocess.PIPE)
    with tmpfile.open('rb') as file:
        essence = file.read()
    return madam.core.Asset(essence=io.BytesIO(essence), mime_type='video/mp2t',
                            width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT, duration=DEFAULT_DURATION,
                            video=dict(codec='mpeg2video', color_space='YUV', depth=8, data_type='uint'),
                            audio=dict(codec='mp2'))


@pytest.fixture(scope='session')
def ogg_video_asset(tmpdir_factory):
    ffmpeg_params = dict(
        width=DEFAULT_WIDTH,
        height=DEFAULT_HEIGHT,
        duration=DEFAULT_DURATION,
    )
    command = ('ffmpeg -loglevel error '
               '-f lavfi -i color=color=red:size=%(width)dx%(height)d:duration=%(duration).1f:rate=15 '
               '-f lavfi -i sine=frequency=440:duration=%(duration).1f '
               '-strict -2 -c:v theora -c:a vorbis -ac 2 -sn '
               '-f ogg' % ffmpeg_params).split()
    tmpfile = tmpdir_factory.mktemp('ogg_video_asset').join('theora-vorbis.ogg')
    command.append(str(tmpfile))
    subprocess.run(command, check=True, stderr=subprocess.PIPE)
    with tmpfile.open('rb') as file:
        essence = file.read()
    return madam.core.Asset(essence=io.BytesIO(essence), mime_type='video/ogg',
                            width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT, duration=DEFAULT_DURATION,
                            video=dict(codec='theora', color_space='YUV', depth=8, data_type='uint'),
                            audio=dict(codec='vorbis'))


@pytest.fixture(scope='session')
def nut_video_asset():
    ffmpeg_params = dict(
        width=DEFAULT_WIDTH,
        height=DEFAULT_HEIGHT,
        duration=DEFAULT_DURATION,
    )
    command = ('ffmpeg -loglevel error '
               '-f lavfi -i color=color=red:size=%(width)dx%(height)d:duration=%(duration).1f:rate=15 '
               '-f lavfi -i sine=frequency=440:duration=%(duration).1f '
               '-c:v ffv1 -level 3 -c:a pcm_s16le -sn '
               '-f nut pipe:' % ffmpeg_params).split()
    ffmpeg = subprocess.run(command, check=True, capture_output=True)
    return madam.core.Asset(essence=io.BytesIO(ffmpeg.stdout), mime_type='video/x-nut',
                            width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT, duration=DEFAULT_DURATION,
                            video=dict(codec='ffv1', color_space='YUV', depth=8, data_type='uint'),
                            audio=dict(codec='pcm_s16le'))


@pytest.fixture(scope='session', params=['mp2_video_asset', 'mp4_video_asset', 'mkv_video_asset', 'nut_video_asset'])
def video_asset(request, avi_video_asset, mp2_video_asset, mp4_video_asset, mkv_video_asset, nut_video_asset):
    if request.param == 'avi_video_asset':
        return avi_video_asset
    if request.param == 'mp2_video_asset':
        return mp2_video_asset
    if request.param == 'mp4_video_asset':
        return mp4_video_asset
    if request.param == 'mkv_video_asset':
        return mkv_video_asset
    if request.param == 'nut_video_asset':
        return nut_video_asset
    raise ValueError()


@pytest.fixture(scope='session', params=['mp4_video_asset', 'mkv_video_asset'])
def video_asset_with_subtitle(request, mp4_video_asset, mkv_video_asset):
    if request.param == 'mp4_video_asset':
        return mp4_video_asset
    if request.param == 'mkv_video_asset':
        return mkv_video_asset
    raise ValueError()


@pytest.fixture(scope='session', params=[
    'jpeg_image_asset', 'png_image_asset', 'gif_image_asset', 'svg_vector_asset',
    'mp3_audio_asset', 'opus_audio_asset', 'wav_audio_asset',
    'avi_video_asset', 'mp2_video_asset', 'mp4_video_asset', 'mkv_video_asset', 'ogg_video_asset'])
def asset(request,
          jpeg_image_asset, png_image_asset, gif_image_asset, svg_vector_asset,
          mp3_audio_asset, opus_audio_asset, wav_audio_asset,
          avi_video_asset, mp2_video_asset, mp4_video_asset, mkv_video_asset, ogg_video_asset):
    if request.param == 'jpeg_image_asset':
        return jpeg_image_asset
    if request.param == 'png_image_asset':
        return png_image_asset
    if request.param == 'gif_image_asset':
        return gif_image_asset
    if request.param == 'svg_vector_asset':
        return svg_vector_asset
    if request.param == 'mp3_audio_asset':
        return mp3_audio_asset
    if request.param == 'opus_audio_asset':
        return opus_audio_asset
    if request.param == 'wav_audio_asset':
        return wav_audio_asset
    if request.param == 'avi_video_asset':
        return avi_video_asset
    if request.param == 'mp2_video_asset':
        return mp2_video_asset
    if request.param == 'mp4_video_asset':
        return mp4_video_asset
    if request.param == 'mkv_video_asset':
        return mkv_video_asset
    if request.param == 'ogg_video_asset':
        return ogg_video_asset
    raise ValueError()


@pytest.fixture(scope='session')
def unknown_asset():
    random_data = b'\x07]>e\x10\n+Y\x07\xd8\xf4\x90%\r\xbbK\xb8+\xf3v%\x0f\x11'
    return madam.core.Asset(essence=io.BytesIO(random_data),
                            mime_type='application/octet-stream')
