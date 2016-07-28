#!/usr/bin/env python

from setuptools import setup

import versioneer

setup(
    name='MADAM',
    version=versioneer.get_version(),
    cmdclass=versioneer.get_cmdclass(),
    author='Michael Seifert',
    author_email='mseifert@error-reports.org',
    install_requires=['bidict', 'piexif', 'pillow'],
    setup_requires=['pytest-runner', 'versioneer'],
    tests_require=['piexif', 'pillow', 'pytest'],
    packages=['madam']
)
