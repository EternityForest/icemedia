# iceflow
More comfortable wrapper for gstreamer and JACK



## iceflow.sound_player


### iceflow.sound_player.sound

The iceflow.sound_player.sound uses MPV to play sounds


#### iceflow.sound_player.sound.preload(filename,output="@auto")
Spins up a paused player for that filename and player. Garbage collecting old cache entries is handled for you.
Will be used when sound.play is called for the same filename and output.


#### iceflow.sound_player.sound.fade_to(self,file,length=1.0, block=False, detach=True, handle="PRIMARY",**kwargs):

Fades the current sound on a given channel to the file. **kwargs aare equivalent to those on playSound.

Passing none for the file allows you to fade to silence, and if no sound is playing. it will fade FROM silence.

Block will block till the fade ends. Detach lets you keep the faded copy attached to the handle(Which makes it end when a new sound plays,
so it only makes sense if fading to silence).

Fading is perceptually linear.


#### iceflow.sound_player.sound.play(filename,handle="PRIMARY",volume=1,start=0,end=-0.0001, output=None,fs=False,extraPaths=\[\])

The handle parameter lets you name the new sound instance to
stop it later or set volume.

If you try to play a sound under the same handle as a
stil-playing sound, the old one will be stopped. Defaults to PRIMARY.


Volume is a dimensionless multiplier. Start and end times are in seconds,
negative means relative to sound end. Start and end times are also
SOX/mplayer specific and are ignored(full sound will always play) with
other players.


Output is a jack client or port if JACK is running.  Currently only the default
outout works on non-jack systems.


#### iceflow.sound_player.sound.stop(handle="PRIMARY")

Stop a sound by handle.

#### iceflow.sound_player.sound.stop_all()

Stop all currently playing sounds.

#### iceflow.sound_player.sound.is_playing(handle="PRIMARY")

Return true if a sound with handle handle is playing. Note that the
sound might finish before you actually get around to doing anything with
the value. If using the dummy backend because a backend is not
installed, result is undefined, but will not be an error, and will be a
boolean value. If a sound is paused, will return True anyway.

#### iceflow.sound_player.sound.setvol(vol,handle="PRIMARY")

Set the volume of a sound. Volume goes from 0 to 1.

#### iceflow.sound_player.sound.pause(handle="PRIMARY")

Pause a sound. Does nothing if already paused.

#### iceflow.sound_player.sound.resume(handle="PRIMARY")

Resume a paused a sound. Does nothing if not paused.


## iceflow.jack module

This submodule requires pyjack, and of course Jack.

### iceflow.jack.start_managing()

Call this to try to connect to the JACK server.  None of the other commands will work until you do this.


### iceflow.jack.Airwire(from,to)
Return an Airwire object. This is a declaration that you want to connect two clients or ports and keep them connected.
If you try to connect a client to a single port, all outputs get mixed down. Likewise a port to a client duplicates to all inputs.

They start in the dis_connected state.


### iceflow.jack.Airwire.connect()
Connect and stay connected. Even if a client dissapears and comes back. Deleting the Airwire will disconnect.
Note that manually disconnecting may not be undone, to prevent annoyance.

### iceflow.jack.Airwire.disconnect()
Disconnect.


### Message Bus activity

This submodule posts the following messages to the scullery
#### /system/jack/newport
 A PortInfo object with a .name, isInput, and isOutput property gets posted here whenever a new port is added to JACK.

#### /system/jack/delport
 A PortInfo object gets posted here whenever a port is unregistered.

#### system/jack/started
When jack is started or restarted

#### sullery.jack.start_managing()
Start the worker thread and enable management functions


## icemedia.iceflow module


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
```

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
