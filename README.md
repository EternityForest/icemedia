# iceflow
More comfortable wrapper for gstreamer and JACK


### iceflow.jack module

This submodule requires pyjack, and of course Jack.

#### iceflow.jack.start_managing()

Call this to try to connect to the JACK server.  None of the other commands will work until you do this.


#### iceflow.jack.Airwire(from,to)
Return an Airwire object. This is a declaration that you want to connect two clients or ports and keep them connected.
If you try to connect a client to a single port, all outputs get mixed down. Likewise a port to a client duplicates to all inputs.

They start in the dis_connected state.


#### iceflow.jack.Airwire.connect()
Connect and stay connected. Even if a client dissapears and comes back. Deleting the Airwire will disconnect.
Note that manually disconnecting may not be undone, to prevent annoyance.

#### iceflow.jack.Airwire.disconnect()
Disconnect.


#### Message Bus activity

This submodule posts the following messages to the scullery
##### /system/jack/newport
 A PortInfo object with a .name, isInput, and isOutput property gets posted here whenever a new port is added to JACK.

##### /system/jack/delport
 A PortInfo object gets posted here whenever a port is unregistered.

##### system/jack/started
When jack is started or restarted

#### sullery.jack.start_managing()
Start the worker thread and enable management functions


### icemedia.iceflow module


This example shows a window full of noise

```python
import time
import icemedia.iceflow


class NoiseWindow(icemedia.iceflow.GstreamerPipeline):
    def __init__(self):
        icemedia.iceflow.GstreamerPipeline.__init__(self)
        self.add_element("videotestsrc", pattern="snow")
        self.add_element("autovideosink")


n = NoiseWindow()
n.start()
print("started")


time.sleep(5)
n.stop()
````

### icemedia.iceflow.GStreamerPipeline
This is the base class for making GStreamer apps

#### GStreamerPipeline.add_element(elementType, name=None, connectToOutput=None,**kwargs)

Adds an element to the pipe and returns a weakref proxy. Normally, this will connect to the last added
element, but you can explicitly pass a an object to connect to. If the last object is a decodebin, it will be connected when a suitable pad
on that is available.

The `**kwargs` are used to set properties of the element.

#### GStreamerPipeline.add_pil_capture(resolution, connectToOutput=None,buffer=1)
Adds a PILCapture object which acts like a video sink. It will buffer the most recent N frames, discarding as needed.

##### GStreamerPipeline.PILCapture.pull()
Return a video frame as a PIL/Pillow Image. May return None on empty buffers.

#### GStreamerPipeline.set_property(element, property, value)
Set a prop of an element, with some added nice features like converting strings to GstCaps where needed, and checking that filesrc locations are actually
valid files that exist.

#### GStreamerPipeline.on_message(source, name, structure)
Used for subclassing. Called when a message that has a structure is seen on the bus. Source is the GST elemeny, struct is dict-like, and name is a string.

#### GStreamerPipeline.play()
If paused, start. If never started, raise an error.

#### GStreamerPipeline.start()
Start running

#### GStreamerPipeline.stop()

Permanently stop and clean up.

#### GStreamerPipeline.pause()

What it sounds like

#### GStreamerPipeline.is_active()

Return True if playing or paused

#### GStreamerPipeline.seek(t=None, rate=None)
Seek to a time, set playback rate, or both.
