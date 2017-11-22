#!/usr/bin/env python
# (c) Copyright IBM Corp. 2010, 2017. All Rights Reserved.

import pkg_resources
try:
    __version__ = pkg_resources.get_distribution(__name__).version
except pkg_resources.DistributionNotFound:
    pass

from .co3 import SimpleClient, \
    SimpleHTTPException, \
    PatchConflictException, \
    get_client, \
    get_config_file
from .co3base import ensure_unicode, \
    get_proxy_dict, \
    NoChange
from .co3argparse import parse_parameters, ArgumentParser
from .co3sslutil import match_hostname
from .patch import Patch
from .patch import PatchStatus

