#!/usr/bin/env python
# coding: utf-8

from setuptools import setup

setup(
    name="eventsocket",
    version="0.1.5",
    description="Twisted protocol for the FreeSWITCH's Event Socket",
    author="Alexandre Fiori",
    url="http://github.com/fiorix/eventsocket",
    py_modules=["eventsocket"],
    install_requires=["twisted>=15.2"],
)
