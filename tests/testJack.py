import gc
import unittest
import time
import iceflow.jack_tools
import iceflow.iceflow


iceflow.jack_tools.start_managing()


class Player(iceflow.iceflow.GstreamerPipeline):
    def __init__(self):
        iceflow.iceflow.GstreamerPipeline.__init__(self, realtime=False)
        self.sink = self.add_element("audiotestsrc")
        self.sink = self.add_element("jackaudiosink", client_name="JackTest")


class TestJackAudio(unittest.TestCase):
    "Note: Requires JACK or pipewire equivalent to be running"

    def test_airwire(self):
        p = Player()
        p.start()

        print("You should hear noise")
        aw = iceflow.jack_tools.Airwire("JackTest", "system")
        aw.connect()
        time.sleep(1)
        print("No more noise")
        aw.disconnect()

        del aw
        gc.collect()
        time.sleep(1)
