import gc
import unittest
import time
import icemedia.jack_tools
import icemedia.iceflow

"Only works if your device names match, may need to change it"

icemedia.jack_tools.start_managing()


class Player(icemedia.iceflow.GstreamerPipeline):
    def __init__(self):
        icemedia.iceflow.GstreamerPipeline.__init__(self, realtime=False)
        self.sink = self.add_element("audiotestsrc")
        self.sink = self.add_element("jackaudiosink", client_name="JackTest", connect=0)


class TestJackAudio(unittest.TestCase):
    "Note: Requires JACK or pipewire equivalent to be running"

    def test_airwire(self):
        p = Player()
        p.start()

        print("You should hear noise")
        aw = icemedia.jack_tools.Airwire("JackTest", "Built-in Audio Analog Stereo")
        aw.connect()
        time.sleep(1)
        print("No more noise")
        aw.disconnect()

        del aw
        gc.collect()
        time.sleep(1)
