# SPDX-FileCopyrightText: Copyright Daniel Dunn
# SPDX-License-Identifier: LGPL-2.1-or-later

from __future__ import annotations
import time
import sys
import functools
import base64
import os
import threading
import weakref
import logging
from typing import Optional
from subprocess import PIPE, STDOUT
from subprocess import Popen
from scullery import workers
from .jsonrpyc import RPC


# Truly an awefullehaccken
# Break out of venv to get to gstreamer
# It's just that one package.  Literally everything else
# Is perfectly fine. GStreamer doesn't do pip so we do this.

try:
    if os.environ.get("VIRTUAL_ENV"):
        en = os.environ["VIRTUAL_ENV"]
        p = os.path.join(
            en,
            "lib",
            "python" + ".".join(sys.version.split(".")[:2]),
            "site-packages",
            "gi",
        )
        s = "/usr/lib/python3/dist-packages/gi"

        if os.path.exists(s) and (not os.path.exists(p)):
            os.symlink(s, p)
except Exception:
    logging.exception("Failed to do the gstreamer hack")


def close_fds(p: Popen):
    try:
        p.stdin.close()
    except Exception:
        pass
    try:
        p.stdout.close()
    except Exception:
        pass
    try:
        p.stderr.close()
    except Exception:
        pass


@functools.cache
def which(program):
    "Check if a program is installed like you would do with UNIX's which command."

    # Because in windows, the actual executable name has .exe while the command name does not.
    if sys.platform == "win32" and not program.endswith(".exe"):
        program += ".exe"

    # Find out if path represents a file that the current user can execute.
    def is_exe(fpath):
        return os.path.isfile(fpath) and os.access(fpath, os.X_OK)

    fpath, fname = os.path.split(program)
    # If the input was a direct path to an executable, return it
    if fpath:
        if is_exe(program):
            return program

    # Else search the path for the file.
    else:
        for path in os.environ["PATH"].split(os.pathsep):
            path = path.strip('"')
            exe_file = os.path.join(path, program)
            if is_exe(exe_file):
                return exe_file

    # If we got this far in execution, we assume the file is not there and return None
    return None


# Can't pass GST elements, have to pass IDs
class ElementProxy:
    "Local proxy to element in the server process"

    def __init__(self, parent: GstreamerPipeline, obj_id) -> None:
        # This was making a bad GC loop issue.
        self.parent = weakref.ref(parent)
        self.id = obj_id

    def get_property(self, p, max_wait=10) -> str | int | float | bool:
        x = self.parent()
        assert x
        return x.get_property(self.id, p, max_wait=max_wait)  # type: ignore

    def set_property(self, p, v, max_wait=10):
        x = self.parent()
        assert x
        x.set_property(self.id, p, v, max_wait=max_wait)

    def pull_buffer(self, timeout=0.1):
        x = self.parent()
        assert x
        return base64.b64decode(x.pull_buffer(self.id, timeout))

    def pull_to_file(self, f):
        x = self.parent()
        assert x
        return x.pull_to_file(self.id, f)


pipes = weakref.WeakValueDictionary()


class GStreamerPipeline:
    def __init__(self, *a, **k):
        self.error_info_handlers = []

        # If del can't find this it would to an infinite loop
        self.worker: Optional[Popen] = None

        pipes[id(self)] = self
        self.ended = False
        f = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "iceflow_server.py"
        )
        # Unusued, the lock is for compatibility wiith the old not-rpc based iceflow
        self.lock = threading.RLock()
        env = {}
        env.update(os.environ)
        env["GST_DEBUG"] = "*:1"

        self.rpc = None

        if which("kaithem._iceflow_server") and False:
            self.worker = Popen(
                ["kaithem._iceflow_server"],
                stdout=PIPE,
                stdin=PIPE,
                stderr=STDOUT,
                env=env,
            )
        else:
            # TODO nobody seems to know why this sometimes OSErrors
            for i in range(5):
                try:
                    self.worker = Popen(
                        [sys.executable or "python3", f],
                        stdout=PIPE,
                        stdin=PIPE,
                        stderr=STDOUT,
                        env=env,
                    )
                    self.worker.stdin.flush()
                    break
                except OSError:
                    if i == 4:
                        raise
                    else:
                        time.sleep(i / 10)

        self.rpc = RPC(
            target=weakref.proxy(self),
            stdin=self.worker.stdout,
            stdout=self.worker.stdin,
            daemon=True,
        )
        # We have no way of knowing when it's actually ready and listening for commands if gstreamer
        # needs to load
        time.sleep(1)

    def rpc_call(self, *a, **k):
        if self.rpc:
            return self.rpc.call(*a, **k)

        raise RuntimeError("No RPC object")

    def __getattr__(self, attr):
        if self.ended or self.worker.poll() is not None:
            raise RuntimeError("This process is already dead")

        def f(*a, **k):
            try:
                return self.rpc_call(attr, args=a, kwargs=k, block=0.001, timeout=15)
            except Exception:
                if self.worker:
                    for i in self.error_info_handlers:
                        try:
                            i()
                        except Exception as e:
                            print(f"Error {e} in error_info_handler")
                    self.cleanup_popen()
                    workers.do(self.worker.wait)
                raise

        return f

    def pull_to_file(self, *a, **k):
        if self.ended or self.worker.poll() is not None:
            raise RuntimeError("This process is already dead")

        try:
            return self.rpc_call(
                "pull_to_file", args=a, kwargs=k, block=0.001, timeout=0.5
            )
        except Exception:
            if self.worker:
                self.cleanup_popen()
                workers.do(self.worker.wait)
            raise

    def cleanup_popen(self):
        self.worker.terminate()
        self.worker.kill()
        close_fds(self.worker)
        try:
            self.rpc.stdin.close()
        except Exception:
            pass

    def __del__(self):
        self.cleanup_popen()
        workers.do(self.worker.wait)

    def add_element(self, element_name: str, *a, **k):
        "Returns an element proxy object"
        # This has to do with setup and I suppose we probably shouldn't just let the error pass by.
        if self.ended or self.worker.poll() is not None:
            raise RuntimeError("This process is already dead")

        # convert element proxies to their ids for transmission
        for key, item in k.items():
            if isinstance(item, ElementProxy):
                k[key] = item.id

        if "connectToOutput" in k:
            k["connect_to_output"] = k.pop("connectToOutput")

        if "connect_to_output" in k and isinstance(
            k["connect_to_output"], (list, tuple)
        ):
            k["connect_to_output"] = [
                (i.id if isinstance(i, ElementProxy) else i)
                for i in k["connect_to_output"]
            ]
        e = ElementProxy(
            self,
            self.rpc_call(
                "add_elementRemote",
                args=(element_name, *a),
                kwargs=k,
                block=0.0001,
                timeout=5,
            ),
        )

        name = k.get("name", f"{element_name}_{id(e)}")

        if element_name == "queue":

            def f():
                x = e.get_property("current-level-time")
                if isinstance(x, (int, float)):
                    x = x / 1000_000_000
                    print(f"Queue {name} level: {x}s")

            self.error_info_handlers.append(f)

        return e

    def set_property(self, *a, max_wait=10, **k):
        # Probably Just Not Important enough to raise an error for this.
        if self.ended or self.worker.poll() is not None:
            print("Prop set in dead process")
            self.ended = True
            return

        # convert element proxies to their ids for transmission
        for key, item in k.items():
            if isinstance(item, ElementProxy):
                k[key] = item.id

        a = [i.id if isinstance(i, ElementProxy) else i for i in a]
        return ElementProxy(
            self,
            self.rpc_call(
                "set_property", args=a, kwargs=k, block=0.0001, timeout=max_wait
            ),
        )

    def get_property(self, e, p, max_wait=10):
        # Probably Just Not Important enough to raise an error for this.
        if self.ended or self.worker.poll() is not None:
            print("Prop get in dead process")
            self.ended = True
            return

        # convert element proxies to their ids for transmission
        if isinstance(e, ElementProxy):
            e = e.id

        return self.rpc_call(
            "get_property", args=[e, p], block=0.0001, timeout=max_wait
        )

    def add_pil_capture(self, *a, **k):
        # Probably Just Not Important enough to raise an error for this.
        if self.ended or self.worker.poll() is not None:
            print("Prop set in dead process")
            self.ended = True
            return
        return ElementProxy(
            self,
            self.rpc_call(
                "addRemotePILCapture", args=a, kwargs=k, block=0.0001, timeout=10
            ),
        )

    def on_appsink_data(self, element_name, data, *a, **k):
        return

    def _on_appsink_data(self, element_name, data):
        self.on_appsink_data(element_name, base64.b64decode(data))

    def on_motion_begin(self, *a, **k):
        print("Motion start")

    def on_motion_end(self, *a, **k):
        print("Motion end")

    def on_multi_file_sink_file(self, fn, *a, **k):
        print("MultiFileSink", fn)

    def on_barcode(self, codetype, data):
        print("Barcode: ", codetype, data)

    def on_level_message(self, src, rms, level):
        pass

    def stop(self):
        if self.ended:
            return

        self.ended = True
        if self.worker.poll() is not None:
            self.ended = True
            return
        try:
            self.rpc_call("stop", block=0.01, timeout=10)
            self.worker.terminate()
            time.sleep(0.5)
            self.worker.kill()
            close_fds(self.worker)
            try:
                self.rpc.stdin.close()
            except Exception:
                pass

        except Exception:
            self.worker.terminate()
            time.sleep(0.5)
            self.worker.kill()
            close_fds(self.worker)
            try:
                self.rpc.stdin.close()
            except Exception:
                pass
            workers.do(self.worker.wait)

        self.rpc = None

    def print(self, s):
        print(s)

    def on_presence_value(self, v):
        print(v)

    def on_video_analyze(self, v):
        print(v)


GstreamerPipeline = GStreamerPipeline
