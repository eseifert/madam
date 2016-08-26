#!/usr/bin/env python

from setuptools import setup

import versioneer

setup(
    name='MADAM',
    version=versioneer.get_version(),
    cmdclass=versioneer.get_cmdclass(),
    author='Michael Seifert, Erich Seifert',
    author_email='mseifert@error-reports.org, dev@erichseifert.de',
    install_requires=['bidict', 'frozendict', 'mutagen', 'piexif', 'pillow'],
    setup_requires=['pytest-runner', 'versioneer'],
    tests_require=['piexif', 'pillow', 'pytest >=2.8'],
    extras_require={
        'doc': ['sphinx >=1.3', 'sphinx_rtd_theme']
    },
    packages=['madam'],
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Environment :: Console',
        'Intended Audience :: Developers',
        'Operating System :: POSIX',
        'Programming Language :: Python',
        'Topic :: Multimedia :: Graphics :: Graphics Conversion',
        'Topic :: Multimedia :: Sound/Audio :: Conversion',
        'Topic :: Multimedia :: Video :: Graphics Conversion',
        'License :: OSI Approved :: GNU Affero General Public License v3',
        'Programming Language :: Python :: 3 :: Only',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
    ],
    keywords='asset media processing'
)
