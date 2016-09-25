#!/usr/bin/env python

from setuptools import setup

import versioneer

with open('README.rst') as file:
    long_description = file.read()

setup(
    name='MADAM',
    description='Digital asset management library',
    long_description=long_description,
    url='https://github.com/eseifert/madam',
    version=versioneer.get_version(),
    cmdclass=versioneer.get_cmdclass(),
    author='Michael Seifert, Erich Seifert',
    author_email='mseifert@error-reports.org, dev@erichseifert.de',
    install_requires=['bidict', 'frozendict', 'pillow'],
    setup_requires=['pytest-runner', 'versioneer'],
    tests_require=['mutagen', 'pillow', 'py3exiv2', 'pytest >=3.0'],
    extras_require={
        'doc': ['sphinx >=1.3', 'sphinx_rtd_theme'],
        'exiv2': ['py3exiv2'],
    },
    packages=['madam'],
    platforms=['POSIX'],
    license='AGPLv3',
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Environment :: Console',
        'Intended Audience :: Developers',
        'Operating System :: POSIX',
        'Programming Language :: Python',
        'Topic :: Multimedia :: Graphics :: Graphics Conversion',
        'Topic :: Multimedia :: Sound/Audio :: Conversion',
        'Topic :: Multimedia :: Video :: Conversion',
        'License :: OSI Approved :: GNU Affero General Public License v3',
        'Programming Language :: Python :: 3 :: Only',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
    ],
    keywords='asset media processing'
)
