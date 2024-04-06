from tests import testJack
from tests import testGstStability
import unittest
import scullery.workers

scullery.workers.start()


# WARNING: Plays audio, stops pulse, and generally takes over hte sound
unittest.main(testJack, exit=False)


unittest.main(testGstStability, exit=False)
