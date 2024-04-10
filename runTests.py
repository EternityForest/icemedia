# Hack because typeguard is currently broken on some systems.
import importlib.metadata

try:
    import typeguard  # noqa
except Exception:
    v = importlib.metadata.version

    def version(p):
        x = v(p)
        if not x:
            raise importlib.metadata.PackageNotFoundError()
        return p

    importlib.metadata.version = version


from tests import testJack
from tests import testGstStability
import unittest
import scullery.workers

scullery.workers.start()


# WARNING: Plays audio, stops pulse, and generally takes over hte sound
unittest.main(testJack, exit=False)


unittest.main(testGstStability, exit=False)
