"""PyInstaller build hook: bundle CoolProp's delvewheel-vendored runtime DLLs.

The Windows CoolProp wheel ships its MSVC runtime (e.g. ``msvcp140-*.dll``) in a
sibling ``coolprop.libs`` directory rather than inside the package, using the
standard ``delvewheel`` layout. PyInstaller's ``--collect-all CoolProp`` gathers
the package itself but does not follow into that separate ``.libs`` folder, so
the compiled ``CoolProp.CoolProp`` extension fails at runtime with
``ImportError: DLL load failed``. This hook locates the ``.libs`` DLLs and adds
them to the bundle root (``.``) so the extension can load them.

On Linux/macOS the ``coolprop.libs`` directory typically does not exist (the
runtime is resolved differently), so this hook is a no-op there.
"""

import glob
import os
import sysconfig

binaries = []

_libs_dir = os.path.join(sysconfig.get_paths()["purelib"], "coolprop.libs")
if os.path.isdir(_libs_dir):
    for _dll in glob.glob(os.path.join(_libs_dir, "*")):
        # (source, dest_dir) — dest "." places the DLL at the bundle root, next
        # to the extracted CoolProp extension, where the loader will find it.
        binaries.append((_dll, "."))
