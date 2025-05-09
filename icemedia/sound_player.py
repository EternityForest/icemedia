# SPDX-FileCopyrightText: Copyright 2013 Daniel Dunn
# SPDX-License-Identifier: LGPL-2.1-or-later

import subprocess

import os
import time
import threading
import collections
import logging
import traceback
from typing import List, Any, Optional, Callable

from scullery import workers

from scullery import util

from .python_mpv_jsonipc import MPV

log = logging.getLogger("system.sound")


media_paths = [""]

media_resolvers: dict[str, Callable[[str], str | None]] = {}


def resolve_sound(fn: str, extrapaths: List[str] = []) -> str:
    "Get the full path of a sound file by searching"
    filename = util.search_paths(fn, extrapaths)
    if not filename:
        filename = util.search_paths(fn, media_paths)

    # Search all module media folders
    if not filename:
        for k, i in media_resolvers.items():
            filename = i(fn)
            if filename:
                break

    # Raise an error if the file doesn't exist
    if not filename or not os.path.isfile(filename):
        raise ValueError("Specified audio file '" + fn + "' was not found")
    assert isinstance(filename, str)
    return filename


# This class provides some infrastructure to play sounds but if you use it directly it is a dummy.
class SoundWrapper(object):
    backendname = "Dummy Sound Driver(No real sound player found)"

    def __init__(self):
        # Prefetch cache for preloadng sound effects
        self.cache = collections.OrderedDict()
        self.runningSounds = {}

    def readySound(self, *args, **kwargs):
        pass

    @staticmethod
    def testAvailable():
        # Default to command based test
        return False

    # little known fact: Kaithem is actually a large collection of
    # mini garbage collectors and bookkeeping code...
    def delete_stopped_sounds(self):
        x = list(self.runningSounds.keys())
        for i in x:
            try:
                if not self.runningSounds[i].is_playing():
                    self.runningSounds.pop(i)
            except KeyError:
                pass

    def stop_all_sounds(self):
        x = list(self.runningSounds.keys())
        for i in x:
            try:
                self.runningSounds.pop(i)
            except KeyError:
                pass

    def get_position(self, channel: str = "PRIMARY"):
        "Return true if a sound is playing on channel"
        try:
            return self.runningSounds[channel].position()
        except KeyError:
            return False

    def set_volume(self, vol: float, channel: str = "PRIMARY"):
        pass

    def set_speed(self, speed: float, channel: str = "PRIMARY", *a, **kw):
        pass

    def play_sound(
        self,
        filename: str,
        handle: str = "PRIMARY",
        extraPaths: List[str] = [],
        volume: float = 1,
        finalGain: Optional[float] = None,
        output: Optional[str] = "",
        loop: float = 1,
        start: float = 0,
        speed: float = 1,
    ):
        pass

    def stop_sound(self, handle: str = "PRIMARY"):
        pass

    def is_playing(self, handle: str = "blah", refresh: bool = False):
        return False

    def pause(self, handle: str = "PRIMARY"):
        pass

    def resume(self, handle: str = "PRIMARY"):
        pass

    def fade_to(
        self,
        file: str | None,
        length: float = 1.0,
        block: bool = False,
        handle: str = "PRIMARY",
        output: Optional[str] = "",
        volume: float = 1,
        windup: float = 0,
        winddown: float = 0,
        loop: int = 1,
        start: float = 0,
        speed: float = 1,
    ):
        if file:
            self.play_sound(file, handle)
        else:
            self.stop_sound(handle)

    def preload(self, filename: str):
        pass

    def seek(self, position: float, channel: str = "PRIMARY"):
        try:
            return self.runningSounds[channel].seek(position)
        except KeyError:
            pass


test_sound_logs = []
play_logs = []


class TestSoundWrapper(SoundWrapper):
    def play_sound(
        self,
        filename: str,
        handle: str = "PRIMARY",
        extraPaths: List[str] = [],
        volume: float = 1,
        finalGain: float | None = None,
        output: str | None = "",
        loop: float = 1,
        start: float = 0,
        speed: float = 1,
    ):
        test_sound_logs.append(["play", handle, filename])
        play_logs.append(["play", handle, filename])

    def fade_to(
        self,
        file: str | None,
        length: float = 1,
        block: bool = False,
        handle: str = "PRIMARY",
        output: str | None = "",
        volume: float = 1,
        windup: float = 0,
        winddown: float = 0,
        loop: int = 1,
        start: float = 0,
        speed: float = 1,
    ):
        test_sound_logs.append(["fade_to", handle, file])
        play_logs.append(["fade_to", handle, file])

    def stop_sound(self, handle: str = "PRIMARY"):
        test_sound_logs.append(["stop", handle])


objectPoolLock = threading.RLock()

objectPool = []


class PlayerHolder(object):
    def __init__(self, p: MPV) -> None:
        self.player = p
        self.usesCounter = 0
        self.conf = [0]
        self.is_configured = False
        self.lastvol = -99089798
        self.conf_speed = 1.0
        self.loop_conf = -1
        self.alreadyMadeReplacement = False
        self.lastjack = "hgfdxcghjkufdszcxghjkuyfgdx"


class MPVBackend(SoundWrapper):
    @staticmethod
    def testAvailable():
        if not util.which("mpv"):
            return False
        try:
            return True
        except Exception:
            pass

    backendname = "MPV"

    # What this does is it keeps a reference to the sound player process and
    # If the object is destroyed it destroys the process stopping the sound
    # It also abstracts checking if its playing or not.
    class MPVSoundContainer(object):
        def __init__(
            self,
            filename,
            vol,
            finalGain,
            output,
            loop,
            start=0.0,
            speed=1.0,
            just_preload=False,
        ):
            self.lock = threading.RLock()
            self.stopped = False
            self.is_playingCache = None

            self.player: Optional[PlayerHolder] = None

            if output == "__disable__":
                return

            self.alreadySetCorrection = False

            # I think this leaks memory when created and destroyed repeatedly
            with objectPoolLock:
                if len(objectPool):
                    self.player = objectPool.pop()
                else:
                    self.player = PlayerHolder(MPV())

            # Avoid somewhat slow RPC calls if we can
            if not self.player.is_configured:
                cname = "kplayer" + str(time.monotonic()) + "_out"
                self.player.player.vid = "no"
                self.player.player.keep_open = "yes"
                self.player.player.ao = "jack,pulse,alsa"
                self.player.player.jack_name = cname
                self.player.player.gapless_audio = "weak"
                self.player.player.is_configured = True

            if speed != self.player.conf_speed:
                self.player.conf_speed = speed
                self.player.player.audio_pitch_correction = False
                self.player.player.speed = speed

            self.speed: float = speed

            if not loop == self.player.loop_conf:
                self.player.loop_conf = loop
                # For legavy reasons some stuff used tens of millions instead of actual infinite loop.
                # But it seems mpv ignores everything past a certain number. So we replace effectively forever with
                # actually forever to get the same effect, assuming that was user intent.
                if not (loop == -1 or loop > 900000000):
                    self.player.player.loop_playlist = int(max(loop, 1))
                else:
                    self.player.player.loop_playlist = "inf"

            # Due to memory leaks, these have a limited lifespan
            self.player.usesCounter += 1

            if (not hasattr(self.player, "lastvol")) or not self.player.lastvol == vol:
                self.player.lastvol = vol
                self.player.player.volume = vol * 100

            self.volume = vol
            self.finalGain = finalGain if finalGain is not None else vol

            jp = "system:*"
            if output:
                if ":" not in output:
                    jp = output + ":*"
                else:
                    jp = output

            if not self.player.lastjack == jp:
                self.player.player.jack_port = jp
                self.player.player.lastjack = jp

            self.started = time.time()

            if filename:
                if self.player:
                    self.is_playingCache = None
                    self.player.player.loadfile(filename)

                    self.player.player.pause = False
                    if start:
                        for i in range(50):
                            try:
                                time.sleep(0.01)
                                self.player.player.seek(str(start), "absolute")
                                break
                            except Exception:
                                pass

                else:
                    raise RuntimeError("Player object is gone")

        def __del__(self):
            self.stop()

        def stop(self):
            if self.stopped:
                return
            self.stopped = True
            bad = True
            if self.player:
                # Only do the maybe recycle logic when stopping a still good SFX

                try:
                    with self.lock:
                        self.player.player.stop()
                    bad = False
                except Exception:
                    # Sometimes two threads try to stop this at the same time and we get a race condition
                    # I really hate this but stopping a crashed sound can't be allowed to take down anything else.
                    pass

                # When the player only has a few uses left, if we don't have many spare objects in
                # the pool, we are going to make the replacement ahead of time in a background thread.
                # But try tpo only make one replacement per object, we don't actually want to go up to the max
                # in the pool because they can use CPU in the background
                if bad or self.player.usesCounter > 8:
                    if not self.player.alreadyMadeReplacement:
                        if (len(objectPool) < 3) or self.player.usesCounter > 10:
                            self.player.alreadyMadeReplacement = True

                            def f():
                                # Can't make it under lock that is slow
                                from .python_mpv_jsonipc import MPV

                                o = PlayerHolder(MPV())
                                with objectPoolLock:
                                    if len(objectPool) < 4:
                                        objectPool.append(o)
                                        return
                                    else:
                                        o.player.terminate()
                                o.player.stop()

                            workers.do(f)

                if bad or self.player.usesCounter > 10:
                    p = self.player

                    def f():
                        if p:
                            p.player.terminate()

                    workers.do(f)

                else:
                    with objectPoolLock:
                        p = self.player
                        if p:
                            if len(objectPool) < 4:
                                objectPool.append(p)
                            else:
                                p.player.terminate()
                self.player = None

        def is_playing(self, refresh=False):
            with self.lock:
                if not self.player:
                    return False
                try:
                    if not refresh:
                        if self.is_playingCache is not None:
                            return self.is_playingCache
                    c = self.player.player.eof_reached == False

                    if c is False:
                        self.is_playingCache = c

                    return c
                except Exception:
                    logging.exception("Error getting playing status, assuming closed")
                    return False

        def position(self):
            return time.time() - self.started

        def wait(self):
            with self.lock:
                if self.player:
                    self.player.wait_for_playback()
                else:
                    raise RuntimeError("No player object")

        def seek(self, position):
            pass

        def setVol(self, volume, final=True):
            with self.lock:
                self.volume = volume
                if final:
                    self.finalGain = volume
                if self.player:
                    self.player.lastvol = volume
                    self.player.player.volume = volume * 100

        def set_speed(self, speed: float):
            with self.lock:
                if self.player:
                    if not self.alreadySetCorrection:
                        self.player.player.audio_pitch_correction = False
                        self.alreadySetCorrection = True
                    # Mark as needing to be updated
                    self.player.conf_speed = speed
                    self.player.player.speed = speed
                self.speed = speed

        def getVol(self):
            with self.lock:
                if self.player:
                    return self.player.player.volume
                else:
                    return 0

        def pause(self):
            with self.lock:
                if self.player:
                    self.player.player.pause = True

        def resume(self):
            with self.lock:
                if self.player:
                    self.player.player.pause = False

    def play_sound(
        self,
        filename: str,
        handle: str = "PRIMARY",
        extraPaths: List[str] = [],
        volume: float = 1,
        finalGain: Optional[float] = None,
        output: Optional[str] = "",
        loop: float = 1,
        start: float = 0,
        speed: float = 1,
    ):
        # Those old sound handles won't garbage collect themselves
        self.delete_stopped_sounds()
        # Raise an error if the file doesn't exist
        fn = resolve_sound(filename, extraPaths)
        # Play the sound with a background process and keep a reference to it
        self.runningSounds[handle] = self.MPVSoundContainer(
            fn, volume, finalGain, output, loop, start=start, speed=speed
        )

    def stop_sound(self, handle="PRIMARY"):
        # Delete the sound player reference object and its destructor will stop the sound
        if handle in self.runningSounds:
            # Instead of using a lock lets just catch the error is someone else got there first.
            try:
                x = self.runningSounds[handle]
                try:
                    x.stop()
                except Exception:
                    logging.exception("Error stopping")
                del self.runningSounds[handle]
                x.nocallback = True
                del x
            except KeyError:
                pass

    def is_playing(self, channel="PRIMARY", refresh=False):
        "Return true if a sound is playing on channel"
        try:
            return self.runningSounds[channel].is_playing(refresh)
        except KeyError:
            return False

    def wait(self, channel="PRIMARY"):
        "Block until any sound playing on a channel is playing"
        try:
            self.runningSounds[channel].wait()
        except KeyError:
            return False

    def set_volume(self, vol, channel="PRIMARY", final=True):
        "Return true if a sound is playing on channel"
        try:
            return self.runningSounds[channel].setVol(vol, final=final)
        except KeyError:
            pass

    def set_speed(self, speed, channel="PRIMARY", *a, **kw):
        "Return true if a sound is playing on channel"
        try:
            return self.runningSounds[channel].set_speed(speed)
        except KeyError:
            pass

    def seek(self, position, channel="PRIMARY"):
        "Return true if a sound is playing on channel"
        try:
            return self.runningSounds[channel].seek(position)
        except KeyError:
            pass

    def pause(self, channel="PRIMARY"):
        "Return true if a sound is playing on channel"
        try:
            return self.runningSounds[channel].pause()
        except KeyError:
            pass

    def resume(self, channel="PRIMARY"):
        "Return true if a sound is playing on channel"
        try:
            return self.runningSounds[channel].resume()
        except KeyError:
            pass

    def fade_to(
        self,
        file: str | None,
        length: float = 1.0,
        block: bool = False,
        handle: str = "PRIMARY",
        output: Optional[str] = "",
        volume: float = 1,
        windup: float = 0,
        winddown: float = 0,
        loop: int = 1,
        start: float = 0,
        speed: float = 1,
    ):
        old_sound = self.runningSounds.pop(handle, None)

        if old_sound and not (length or winddown):
            old_sound.stop()

        # Allow fading to silence
        if file:
            sspeed = speed
            if windup:
                sspeed = 0.1

            self.play_sound(
                file,
                handle=handle,
                volume=0,
                output=output,
                finalGain=volume,
                loop=loop,
                start=start,
                speed=sspeed,
            )

        # if not x:
        #    return
        if not (length or winddown or windup):
            return
        loop_id = time.time()
        self.loop_id = loop_id
        try:
            old_sound.loop_id = None
        except Exception:
            pass

        def f():
            fade_start_time = time.monotonic()
            try:
                old_volume = old_sound.volume
            except Exception:
                old_volume = 0

            try:
                old_speed = old_sound.speed
            except Exception:
                old_speed = 1

            targetVol = 1
            while time.monotonic() - fade_start_time < max(length, winddown, windup):
                if max(length, winddown):
                    foratio = max(
                        0,
                        min(
                            1,
                            (
                                (time.monotonic() - fade_start_time)
                                / max(length, winddown)
                            ),
                        ),
                    )
                else:
                    foratio = 1

                if length:
                    firatio = max(
                        0, min(1, ((time.monotonic() - fade_start_time) / length))
                    )
                else:
                    firatio = 1

                tr = time.monotonic()

                if old_sound and old_sound.player:
                    # Player might have gotten itself stopped by now
                    try:
                        old_sound.setVol(max(0, old_volume * (1 - foratio)))

                        if winddown:
                            wdratio = max(
                                0,
                                min(
                                    1, ((time.monotonic() - fade_start_time) / winddown)
                                ),
                            )
                            old_sound.set_speed(max(0.1, old_speed * (1 - wdratio)))
                    except AttributeError:
                        print(traceback.format_exc())

                if file and (handle in self.runningSounds):
                    # If another fade has taken over from this one,
                    # self will be it's old_sound, it will take over

                    if self.loop_id:
                        targetVol = self.runningSounds[handle].finalGain
                        self.set_volume(
                            min(1, targetVol * firatio), handle, final=False
                        )

                        if windup:
                            wuratio = max(
                                0,
                                min(1, ((time.monotonic() - fade_start_time) / windup)),
                            )
                            self.set_speed(
                                max(0.1, min(speed, wuratio * speed, 8)), handle
                            )

                # Don't overwhelm the backend with commands
                time.sleep(max(1 / 48.0, time.monotonic() - tr))

            try:
                targetVol = self.runningSounds[handle].finalGain
            except KeyError:
                targetVol = -1

            if not targetVol == -1:
                try:
                    self.set_volume(min(1, targetVol), handle)
                except Exception as e:
                    print(e)

            if old_sound:
                old_sound.stop()

        if block:
            f()
        else:
            workers.do(f)


backends = {"mpv": MPVBackend, "test": TestSoundWrapper}

backend = SoundWrapper()


def select_backend(name: str):
    global backend
    global play_sound, stop_sound, is_playing, resolve_sound, pause, resume
    global fade_to, position, setvol, readySound, preload

    if name not in backends:
        raise RuntimeError("Could not set up backend")
    try:
        if util.which(name) or backends[name].testAvailable():
            backend = backends[name]()
    except Exception:
        logging.exception("Failed to set up backend")

    play_sound = backend.play_sound
    stop_sound = backend.stop_sound
    is_playing = backend.is_playing
    resolve_sound = resolve_sound
    pause = backend.pause
    resume = backend.resume
    setvol = backend.set_volume
    position = backend.get_position
    fade_to = backend.fade_to
    readySound = backend.readySound
    preload = backend.preload


def stop_all_sounds():
    backend.stop_all_sounds()


def test(output=None):
    t = "test_" + str(time.time())
    play_sound("alert.ogg", output=output, handle=t)
    for i in range(100):
        if is_playing(t, refresh=True):
            return
        time.sleep(0.01)
    raise RuntimeError("Sound did not report as playing within 1000ms")


# Make fake module functions mapping to the bound methods.
# have to hardcode them here or else the linter might not be happy

play_sound = backend.play_sound
stop_sound = backend.stop_sound
is_playing = backend.is_playing
resolve_sound = resolve_sound
pause = backend.pause
resume = backend.resume
setvol = backend.set_volume
position = backend.get_position
fade_to = backend.fade_to
readySound = backend.readySound
preload = backend.preload

isStartDone = []

try:
    select_backend("mpv")
except Exception:
    logging.exception("Failed to select MPV backend.")
