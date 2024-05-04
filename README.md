# iceflow
More comfortable wrapper for gstreamer and JACK


## Install

```
pip install icemedia
```


## icemedia.sound_player

### Example
```python
import icemedia.sound_player

testmedia = "YourAudioFileHere.mp3"

icemedia.sound_player.play_sound(testmedia)
time.sleep(3)
```

The icemedia.sound_player.sound uses MPV to play sounds, so it supports almost any file.


#### icemedia.sound_player.preload(filename,output="@auto")
Spins up a paused player for that filename and player. Garbage collecting old cache entries is handled for you.
Will be used when sound.play is called for the same filename and output.


#### icemedia.sound_player.fade_to(self,file,length=1.0, block=False, detach=True, handle="PRIMARY",**kwargs):

Fades the current sound on a given channel to the file. **kwargs aare equivalent to those on playSound.

Passing none for the file allows you to fade to silence, and if no sound is playing. it will fade FROM silence.

Block will block till the fade ends. Detach lets you keep the faded copy attached to the handle(Which makes it end when a new sound plays,
so it only makes sense if fading to silence).

Fading is perceptually linear.


#### icemedia.sound_player.play(filename,handle="PRIMARY",volume=1,start=0,end=-0.0001, output=None,fs=False,extraPaths=\[\])

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


#### icemedia.sound_player.stop(handle="PRIMARY")

Stop a sound by handle.

#### icemedia.sound_player.stop_all()

Stop all currently playing sounds.

#### icemedia.sound_player.is_playing(handle="PRIMARY")

Return true if a sound with handle handle is playing. Note that the
sound might finish before you actually get around to doing anything with
the value. If using the dummy backend because a backend is not
installed, result is undefined, but will not be an error, and will be a
boolean value. If a sound is paused, will return True anyway.

#### icemedia.sound_player.setvol(vol,handle="PRIMARY")

Set the volume of a sound. Volume goes from 0 to 1.

#### icemedia.sound_player.pause(handle="PRIMARY")

Pause a sound. Does nothing if already paused.

#### icemedia.sound_player.resume(handle="PRIMARY")

Resume a paused a sound. Does nothing if not paused.


## icemedia.jack module

This submodule requires pyjack, and of course Jack.


### Example
This uses both JACK and GStreamer

```python
import time
import icemedia.jack_tools
import icemedia.iceflow

"Only works if your device names match, may need to change Built-in Audio Analog Stereo to something else"

icemedia.jack_tools.start_managing()


class Player(icemedia.iceflow.GstreamerPipeline):
    def __init__(self):
        icemedia.iceflow.GstreamerPipeline.__init__(self, realtime=False)
        self.src = self.add_element("audiotestsrc")
        self.sink = self.add_element("jackaudiosink", client_name="JackTest", connect=0)

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
```

### icemedia.jack.start_managing()

Call this to try to connect to the JACK server.  None of the other commands will work until you do this.


### icemedia.jack.Airwire(from,to)
Return an Airwire object. This is a declaration that you want to connect two clients or ports and keep them connected.
If you try to connect a client to a single port, all outputs get mixed down. Likewise a port to a client duplicates to all inputs.

They start in the dis_connected state.


### icemedia.jack.Airwire.connect()
Connect and stay connected. Even if a client dissapears and comes back. Deleting the Airwire will disconnect.
Note that manually disconnecting may not be undone, to prevent annoyance.

### icemedia.jack.Airwire.disconnect()
Disconnect.


### Message Bus activity

This submodule posts the following messages to the [Scullery](https://github.com/EternityForest/scullery) message bus.

#### /system/jack/newport
 A PortInfo object with a .name, isInput, and isOutput property gets posted here whenever a new port is added to JACK.

#### /system/jack/delport
 A PortInfo object gets posted here whenever a port is unregistered.

#### system/jack/started
When jack is started or restarted

#### sullery.jack.start_managing()
Start the worker thread and enable management functions


## icemedia.iceflow module

This is a wrapper around GStreamer that handles a lot of the more obnoxious parts for you.
You'll need to install Gstreamer and it's bindings yourself, they are not in Pip.

To do this on debian-based systems, try these packages on apt, you only
need the plugins you actually want to use. GStreamer also will use any LADSPA plugins it finds.

 - python3-gi
 - python3-gst-1.0
 - gstreamer1.0-plugins-good
 - gstreamer1.0-plugins-bad
 - gstreamer1.0-plugins-ugly


### Noise Window

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

#### GStreamerPipeline.add_element(elementType, name=None connect_to_output=None, connect_when_available=None, auto_insert_audio_convert=False, \*\*kwargs)

Adds an element to the pipe and returns a weakref proxy. Normally, this will connect to the last added
element, but you can explicitly pass a an object to connect to.

If auto_insert_audio_convert is set, then if connecting the elements fails,
will retry with an audioconvert element in between.

if connect_when_available is True, then the elements will be connected later,
at runtime, when the pad exists.  This is needed for some Gst elements that have dynamic pads.

The `**kwargs` are used to set properties of the element.

This function returns an ElementProxy.  It acts like a GStreamer element but it is actually
a proxy object, because the actual pipeline is in a separate background process.

#### ElementProxy.set_property(key, value)

Set a key on the element.

#### GStreamerPipeline.add_pil_capture(resolution, connect_to_output=None,buffer=1)
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


#### GStreamerPipeline.on_level_message(self, src, rms, level):

Subclass this if you want to add a level element and recieve info about the volume.

#### GStreamerPipeline.on_multi_file_sink_file(self, fn, *a, **k):
    A MultiFileSink made a new file

#### GStreamerPipeline.def on_barcode(self, codetype, data):
    A barcode reader element has detected a barcode

