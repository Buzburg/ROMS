"""Load the prebuilt Mojo kernels; never compile or download during a search."""
from functools import lru_cache
import importlib


@lru_cache(maxsize=1)
def _load():
    try:
        return importlib.import_module('app.roms_search_native')
    except ModuleNotFoundError as exc:
        if exc.name != 'app.roms_search_native':
            raise
        return None


def kernels():
    native = _load()
    if native is None or not all(hasattr(native, name) for name in ('expand', 'fuse', 'clean', 'passages')):
        raise RuntimeError('Build the required Mojo search module with scripts/build_search_native.py and restart ROMS')
    return native


def kernel_name():
    kernels()
    return 'mojo'
