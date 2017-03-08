from __future__ import print_function

import os.path
import sys
from setuptools import setup, find_packages
from setuptools.command.test import test as TestCommand

class PyTest(TestCommand):
    user_options = [('pytestargs=', 'a', "Resilient Environment Arguments")]

    def initialize_options(self):
        TestCommand.initialize_options(self)
        self.pytestargs = []
        self.test_suite = True

    def finalize_options(self):
        import shlex
        TestCommand.finalize_options(self)
        self.test_args = ["-s",] + shlex.split(self.pytestargs)

    def run_tests(self):
        #import here, cause outside the eggs aren't loaded
        import pytest
        errno = pytest.main(self.test_args)
        sys.exit(errno)

setup(
    name='rc-file-lookup',
    version="27.0.0",
    url='https://www.resilientsystems.com/',
    license='Resilient License',
    author='IBM Resilient',
    install_requires=[
        'setuptools>=34.3.0',
        'resilient_circuits>=27.1.0'
    ],
    tests_require=["pytest",
                   "pytest_resilient_circuits"],
    cmdclass = {"test" : PyTest},
    author_email='support@resilientsystems.com',
    description="Resilient Circuits Component for Automatic CSV File Lookup",
    long_description = "Resilient Circuits Component for Automatic CSV File Lookup",
    packages=find_packages(),
    include_package_data=True,
    data_files = [("file_lookup", ["file_lookup/LICENSE"]),
                  ("file_lookup/data", ["file_lookup/data/sample.csv"])],
    platforms='any',
    classifiers=[
        'Programming Language :: Python',
    ],
    entry_points={
        # Register the component with resilient_circuits
        "resilient.circuits.components": ["FileLookupComponent = file_lookup.components.file_lookup:FileLookupComponent"],
        "resilient.circuits.configsection": ["gen_config = file_lookup.components.file_lookup:config_section_data"]
    }
)
