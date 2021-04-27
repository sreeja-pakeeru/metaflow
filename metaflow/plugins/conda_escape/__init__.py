# Portions of this plugin are inspired by RPyC
# https://rpyc.readthedocs.io/
#
# The license for that software is reproduced below
#
# Copyright (c) 2005-2013
#  Tomer Filiba (tomerfiliba@gmail.com)
#  Copyrights of patches are held by their respective submitters
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.

import os
import subprocess
# conda_escape subpackage

from .exception_transferer import RemoteInterpreterException
from .client_modules import create_modules

# path to default python3 interpreter. This is the Python3 path that is, hopefully
# system-wide. We either look for something that the user provides or we look
# at the last priority python (ie: the base one -- not the one that is
# running in the conda environment)
def get_python3_base():
    try:
        out = subprocess.check_output(['type', '-a', 'python3'])
    except subprocess.CalledProcessError:
        return None
    lines = out.splitlines()
    if len(lines) < 2:
        # Need at least conda one and non conda one
        return None
    return lines[-1].split(b' ')[-1].decode(encoding='utf-8')

ESCAPE_HATCH_PY = os.environ.get('METAFLOW_PYTHON3_PATH', get_python3_base())

def generate_trampolines(python_interpreter_path, python_path):
    # This function will look in the configurations directory and create
    # files named <module>.py that will properly setup the escape hatch when
    # called

    # in some cases we may want to disable escape hatch
    # functionality, in that case, set MF_ESCAPE_HATCH_DISABLED
    if os.environ.get('MF_ESCAPE_HATCH_DISABLED', False) in (True, 'True'):
        return

    config_dir = os.path.dirname(os.path.abspath(__file__)) + "/configurations"

    for path in os.listdir(config_dir):
        path = os.path.join(config_dir, path)
        if os.path.isdir(path):
            dir_name = os.path.basename(path)
            if dir_name.startswith('emulate_'):
                module_names = dir_name[8:].split("__")
                for module_name in module_names:
                    with open(os.path.join(python_path, module_name + ".py"), mode='w') as f:
                        f.write("""
import importlib
import os
import sys
from metaflow.plugins.conda_escape.client_modules import ModuleImporter

# This is a trampoline file to ensure that the ModuleImporter to handle the emulated
# modules gets properly loaded. If multiple modules are emulated by a single configuration
# the first import will cause this trampoline file to be loaded. All other calls will use
# the module importer since we insert the importer at the head of the meta_path

def load():
    # We check if we are not overriding a module that already exists; to do so, we remove
    # the path we live at from sys.path and check
    old_paths = sys.path
    cur_path = os.path.dirname(__file__)
    sys.path = [p for p in old_paths if p != cur_path]
    # Handle special case where we launch a shell (including with a command)
    # and we are in the CWD (searched if '' is the first element of sys.path)
    if cur_path == os.getcwd() and sys.path[0] == '':
        sys.path = sys.path[1:]

    # Remove the module (this file) to reload it properly. Do *NOT* update sys.modules but
    # modify directly since it may be referenced elsewhere
    del sys.modules["{module_name}"]

    for prefix in {prefixes}:
        try:
            importlib.import_module(prefix)
        except ImportError:
            # Here we actually have two cases: we are being imported from the client (Conda env)
            # in which case we are happy (since no module exists) OR we are being imported by the
            # server in which case we could not find the underlying module so we re-raise
            # this error.
            # We distinguish these cases by checking if the executable is the python_path the
            # server should be using
            if sys.executable == "{python_path}":
                raise
        else:
            # Inverse logic as above here.
            if sys.executable == "{python_path}":
                return
            raise RuntimeError("Trying to override '%s' when module exists in system" % prefix)
    sys.path = old_paths
    m = ModuleImporter("{python_path}", "{path}", {prefixes})
    sys.meta_path.insert(0, m)
    # Reload this module using the ModuleImporter
    importlib.import_module("{module_name}")

load()
""" .format(
    python_path=python_interpreter_path,
    path=path,
    prefixes=module_names,
    module_name=module_name
))


def init(python_interpreter_path):
    # This function will look in the configurations directory and setup
    # the proper overrides
    config_dir = os.path.dirname(os.path.abspath(__file__)) + "/configurations"

    for path in os.listdir(config_dir):
        path = os.path.join(config_dir, path)
        if os.path.isdir(path):
            dir_name = os.path.basename(path)
            if dir_name.startswith('emulate_'):
                module_names = dir_name[8:].split("__")
                create_modules(python_interpreter_path, path, module_names)