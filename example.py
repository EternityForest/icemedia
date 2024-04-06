import time
import iceflow.iceflow


class NoiseWindow(iceflow.iceflow.GstreamerPipeline):
    def __init__(self):
        iceflow.iceflow.GstreamerPipeline.__init__(self)
        self.add_element("videotestsrc", pattern="snow")
        self.add_element("autovideosink")


n = NoiseWindow()
n.start()
print("started")

time.sleep(2)
print("stopping")
n.stop()
print("stopped")
