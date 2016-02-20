#!/usr/bin/env python

from setuptools import setup

setup(
    name='ADAM',
    version='0.1',
    author='Michael Seifert',
    author_email='mseifert@error-reports.org',
    install_requires=['pytaglib'],
    setup_requires=['pytest-runner'],
    tests_require=['pytest'],
)
