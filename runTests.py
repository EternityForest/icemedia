from tests import testGstStability
import unittest
import scullery.workers

scullery.workers.start()


# WARNING: Plays audio, stops pulse, and generally takes over hte sound
# from tests import testJack
# unittest.main(testJack,exit=False)


unittest.main(testGstStability, exit=False)
