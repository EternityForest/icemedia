# SPDX-FileCopyrightText: Copyright Daniel Dunn
# SPDX-License-Identifier: LGPL-2.1-or-later

import logging
from scullery import messagebus, workers

__doc__ = ""


import weakref
import threading
import time
import traceback


import jack


def portToInfo(p):
    return PortInfo(p.name, p.is_input, p.shortname, p.is_audio, list(p.aliases))


# Util is not used anywhere else

# This is an acceptable dependamcy, it will be part of libkaithem if such a thing exists


# These events have to happen in a consistent order, the same order that the actual JACK callbacks happen.
# We can't do them within the jack callback becauuse that could do a deadlock.

jackEventHandlingQueue = []
jackEventHandlingQueueLock = threading.Lock()

portInfoByID = weakref.WeakValueDictionary()


class PortInfo:
    def __init__(self, name, isInput, sname, isAudio, aliases=None):
        self.isOutput = self.is_output = not isInput
        self.isInput = self.is_input = isInput
        self.isAudio = self.is_audio = isAudio
        self.name = name
        self.shortname = sname
        self.clientName = name[: -len(":" + sname)]
        portInfoByID[id(self)] = self
        self.aliases = aliases or []

    def toDict(self):
        return {
            "name": self.name,
            "isInput": self.is_input,
            "sname": self.shortname,
            "isAudio": self.isAudio,
            "aliases": self.aliases,
        }


class JackClientManager:
    def get_all_connections(self, *a, **k):
        check_exclude()

        a = [i.name if isinstance(i, PortInfo) else i for i in a]
        x = self._client.get_all_connections(*a, **k)
        x = [portToInfo(i) for i in x]
        return x

    def get_ports(self, *a, **k):
        check_exclude()

        a = [i.name if isinstance(i, PortInfo) else i for i in a]
        x = self._client.get_ports(*a, **k)
        x = [portToInfo(i) for i in x]
        return x

    def on_port_registered(self, port, registered):
        name, is_input, shortname, is_audio, registered = (
            port.name,
            port.is_input,
            port.shortname,
            port.is_audio,
            registered,
        )

        def f():
            try:
                global realConnections
                "Same function for register and unregister"
                # if not port:
                #     return

                p = PortInfo(name, is_input, shortname, is_audio)

                if registered:
                    # log.debug("JACK port registered: "+port.name)
                    with portsListLock:
                        portsList[name] = p

                    def g():
                        # Seems to need tome to set up fully.
                        time.sleep(0.5)
                        messagebus.post_message("/system/jack/newport", p)

                    workers.do(g)
                else:
                    torm = []
                    with portsListLock:
                        for i in _realConnections:
                            if i[0] == name or i[1] == name:
                                torm.append(i)
                        for i in torm:
                            del _realConnections[i]

                        try:
                            del portsList[name]
                        except Exception:
                            pass
                        realConnections = _realConnections.copy()

                    messagebus.post_message("/system/jack/delport", p)
            except Exception:
                print(traceback.format_exc())

        jackEventHandlingQueue.append(f)
        workers.do(handle_jack_event)

    def on_port_connected(self, a, b, c):
        a_is_output, a_name, b_name, connected = (a.is_output, a.name, b.name, c)
        # Whem things are manually disconnected we don't
        # Want to always reconnect every time

        def f():
            global realConnections

            if connected:
                with portsListLock:
                    if a_is_output:
                        _realConnections[a_name, b_name] = True
                    else:
                        _realConnections[b_name, a_name] = True

                    realConnections = _realConnections.copy()

            if not connected:
                i = (a_name, b_name)
                with portsListLock:
                    if (a_name, b_name) in _realConnections:
                        try:
                            del _realConnections[a_name, b_name]
                        except KeyError:
                            pass

                    if (b_name, a_name) in _realConnections:
                        try:
                            del _realConnections[b_name, a_name]
                        except KeyError:
                            pass

                    realConnections = _realConnections.copy()

                # Try to stop whatever airwire or set therof
                # from remaking the connection
                if i in activeConnections:
                    try:
                        # Deactivate first, that must keep it from using the api
                        # From within the callback
                        activeConnections[i].active = False
                        del allConnections[i]
                        del activeConnections[i]
                    except Exception:
                        pass

                # def f():
                #     if not connected:
                #         log.debug("JACK port "+ a.name+" disconnected from "+b.name)
                #     else:
                #         log.debug("JACK port "+ a.name+" connected to "+b.name)

                # workers.do(f)

        jackEventHandlingQueue.append(f)
        workers.do(handle_jack_event)

    def connect(self, f, t):
        t = self._client.get_port_by_name(t)
        f = self._client.get_port_by_name(f)

        if not t.is_input:
            x = t
            t = f
            f = x
        try:
            self._client.connect(f, t)
        except jack.JackErrorCode as e:
            if e.code == 17:
                pass
            else:
                raise

    def disconnect(self, f, t):
        t = self._client.get_port_by_name(t)
        f = self._client.get_port_by_name(f)

        if not t.is_input:
            x = t
            t = f
            f = x

        self._client.disconnect(f, t)

    def close(self):
        pass

    def __init__(self, *a, **k):
        self._client = jack.Client(
            "Overseer" + str(time.monotonic()), no_start_server=True
        )

        self._client.set_port_connect_callback(self.on_port_connected)
        self._client.set_port_registration_callback(
            self.on_port_registered, only_available=False
        )
        self._client.activate()


def handle_jack_event():
    with jackEventHandlingQueueLock:
        if jackEventHandlingQueue:
            f = jackEventHandlingQueue.pop(False)
            f()


dummy = False


log = logging.getLogger("system.jack")

_jackclient = None


lock = threading.RLock()


def on_jack_failure():
    pass


def on_jack_start():
    pass


# No other lock should ever be gotten under this, to ensure anti deadlock ordering.

# This also protects the list of connections.  There is a theoretical race condition currently,
# Siomeone else could disconnect a port right as we connect it, and we currently mark things connected by ourselves
# without waiting for jack to tell us, to avoid double connects if at all possible on the "Don't touch the scary server" principle.

# However, in basically all intended use cases there will never be any external things changing anything around, other than manual users who can quicky fix au
# misconnections.
portsListLock = threading.Lock()
portsList = {}


# Currently we only support using the default system card as the
# JACK backend. We prefer this because it's easy to get Pulse working right.
usingDefaultCard = True


def is_connected(f, t):
    if not isinstance(f, str):
        f = f.name
    if not isinstance(t, str):
        t = t.name

    if (t, f) in _realConnections:
        return True

    if (f, t) in _realConnections:
        return True


ensureConnectionsQueued = [0]


def _ensureConnections(*a, **k):
    "Auto restore connections in the connection list"

    # Someone else is already gonna run this
    # It is ok to have excess runs, but there must always be atleast 1 run after every change
    if ensureConnectionsQueued[0]:
        return
    ensureConnectionsQueued[0] = 1

    try:
        with lock:
            # Avoid race conditions, set flag BEFORE we check.
            # So we can't miss anything.  The other way would cause them to think we would check,
            # so they exit, but actually we already did.
            ensureConnectionsQueued[0] = 0
            x = list(allConnections.keys())
        for i in x:
            try:
                allConnections[i].reconnect()
            except KeyError:
                pass
            except Exception:
                print(traceback.format_exc())
    except Exception:
        ensureConnectionsQueued[0] = 0
        log.exception("Probably just a weakref that went away.")


messagebus.subscribe("/system/jack/newport", _ensureConnections)

allConnections = weakref.WeakValueDictionary()

activeConnections = weakref.WeakValueDictionary()

# Things as they actually are
realConnections = {}

_realConnections = {}


def find_real():
    global realConnections, _realConnections
    assert _jackclient
    with lock:
        p = _jackclient.get_ports(is_output=True)

        pl = {}
        for i in p:
            try:
                for j in _jackclient.get_all_connections(i):
                    pl[i.name, j.name] = True
            except Exception:
                log.exception("Err")
        with portsListLock:
            _realConnections = pl
            realConnections = _realConnections.copy()

            p = _jackclient.get_ports()
            # First time, get the initial list
            if not portsList:
                for i in p:
                    portsList[i.name] = i


errlog = []


latestAirWireForGivenPair = weakref.WeakValueDictionary()


class MonoAirwire:
    """Represents a connection that should always exist as long as there
    is a reference to this object. You can also enable and disable it with
    the connect() and disconnect() functions.

    They start out in the connected state
    """

    def __init__(self, orig, to):
        self.orig = orig
        self.to = to
        self.active = True

        if isinstance(orig, PortInfo):
            orig = orig.name
        if isinstance(to, PortInfo):
            to = to.name
        self.tupleid = (orig, to)
        latestAirWireForGivenPair[self.tupleid] = self

    def disconnect(self, force=True):
        global realConnections
        self.disconnected = True
        try:
            del allConnections[self.orig, self.to]
        except Exception:
            pass

        if not force:
            # As garbage collection happens at uppredicatble times,
            # Don't disconnect if this airwire has been taken over by a new connection between the ports
            x = None
            try:
                x = latestAirWireForGivenPair[self.tupleid]
            except KeyError:
                pass

            if x and x is not self:
                return

        try:
            if lock.acquire(timeout=10):
                try:
                    if is_connected(self.orig, self.to):
                        disconnect(self.orig, self.to)
                        del activeConnections[self.orig, self.to]
                    try:
                        with portsListLock:
                            del _realConnections[self.orig, self.to]
                            realConnections = _realConnections.copy()
                    except KeyError:
                        pass
                    try:
                        with portsListLock:
                            del _realConnections[self.to, self.orig]
                            realConnections = _realConnections.copy()
                    except KeyError:
                        pass
                finally:
                    lock.release()
            else:
                raise RuntimeError("getting lock")

        except Exception:
            pass

    def __del__(self):
        # TODO: Is there any possible deadlock risk at all here?
        if self.active:
            self.disconnect(False)

    def connect(self):
        allConnections[self.orig, self.to] = self
        activeConnections[self.orig, self.to] = self

        self.connected = True
        self.reconnect()

    def reconnect(self):
        if (self.orig, self.to) in activeConnections:
            if self.orig and self.to:
                try:
                    if not is_connected(self.orig, self.to):
                        if lock.acquire(timeout=10):
                            try:
                                connect(self.orig, self.to)
                                with portsListLock:
                                    _realConnections[self.orig, self.to] = True
                                    global realConnections
                                    realConnections = _realConnections.copy()
                            finally:
                                lock.release()
                        else:
                            raise RuntimeError("Could not get lock")
                except Exception:
                    print(traceback.format_exc())


class MultichannelAirwire(MonoAirwire):
    "Link all outputs of f to all inputs of t, in sorted order"

    def _getEndpoints(self):
        f = self.orig
        if not f:
            return None, None

        t = self.to
        if not t:
            return None, None
        return f, t

    def reconnect(self):
        """Connects the outputs of channel strip(Or other JACK thing)  f to the inputs of t, one to one, until
        you run out of ports.

        Note that channel strips only have the main inputs but can have sends,
        so we have to distinguish them in the regex.
        """
        global realConnections, _realConnections
        if not self.active:
            return
        f, t = self._getEndpoints()

        if not f:
            return
        if not t:
            return
        f = f.replace("*:", "")
        t = t.replace("*:", "")

        if portsListLock.acquire(timeout=10):
            try:
                outPorts = sorted(
                    [
                        portsList[i]
                        for i in portsList
                        if i.split(":")[0] == f
                        and portsList[i].is_audio
                        and portsList[i].is_output
                    ],
                    key=lambda x: x.name,
                )
                inPorts = sorted(
                    [
                        portsList[i]
                        for i in portsList
                        if i.split(":")[0] == t
                        and portsList[i].is_audio
                        and (not portsList[i].is_output)
                    ],
                    key=lambda x: x.name,
                )
            finally:
                portsListLock.release()
        else:
            raise RuntimeError("Getting lock")

        # outPorts = _jackclient.get_ports(f+":*",is_output=True,is_audio=True)
        # inPorts = _jackclient.get_ports(t+":*",is_input=True,is_audio=True)
        # Connect all the ports
        for i in zip(outPorts, inPorts):
            if not is_connected(i[0].name, i[1].name):
                if lock.acquire(timeout=10):
                    try:
                        connect(i[0], i[1])
                        with portsListLock:
                            _realConnections[i[0].name, i[1].name] = True
                            realConnections = _realConnections.copy()
                    finally:
                        lock.release()
                else:
                    raise RuntimeError("Getting lock")

    def disconnect(self, force=True):
        global _jackclient
        check_exclude()

        if hasattr(self, "noNeedToDisconnect"):
            return

        f, t = self._getEndpoints()
        if not f:
            return

        if not force:
            # As garbage collection happens at uppredicatble times,
            # Don't disconnect if this airwire has been taken over by a new connection between the ports
            x = None
            try:
                x = latestAirWireForGivenPair[self.tupleid]
            except KeyError:
                pass

            if x and x is not self:
                return

        inPorts = outPorts = None
        if portsListLock.acquire(timeout=10):
            try:
                outPorts = sorted(
                    [
                        portsList[i]
                        for i in portsList
                        if i.split(":")[0] == f
                        and portsList[i].is_audio
                        and portsList[i].is_output
                    ],
                    key=lambda x: x.name,
                )
                inPorts = sorted(
                    [
                        portsList[i]
                        for i in portsList
                        if i.split(":")[0] == t
                        and portsList[i].is_audio
                        and (not portsList[i].is_output)
                    ],
                    key=lambda x: x.name,
                )
            finally:
                portsListLock.release()

        if not inPorts or not outPorts:
            return

        if lock.acquire(timeout=10):
            try:
                # Connect all the ports
                for i in zip(outPorts, inPorts):
                    if is_connected(i[0], i[1]):
                        disconnect(i[0], i[1])
                        try:
                            del activeConnections[i[0].name, i[1].name]
                        except KeyError:
                            pass
            finally:
                lock.release()
        else:
            raise RuntimeError("getting lock")

    def __del__(self):
        workers.do(self.disconnect)


class CombiningAirwire(MultichannelAirwire):
    def reconnect(self):
        """Connects the outputs of channel strip f to the port t. As in all outputs
        to one input. If the destination is a client, connect all channnels of src to all of dest.
        """
        if not self.active:
            return
        f, t = self._getEndpoints()
        if not f:
            return
        if not t:
            return
        if lock.acquire(timeout=10):
            try:
                if t.endswith("*"):
                    t = t[:-1]

                if f.endswith("*"):
                    f = f[:-1]

                if t.endswith(":"):
                    t = t[:-1]

                if f.endswith(":"):
                    f = f[:-1]

                outPorts = []
                inPorts = []
                with portsListLock:
                    for i in portsList:
                        if i.startswith(f + ":") or i == f:
                            if portsList[i].is_output and portsList[i].is_audio:
                                outPorts.append(i)
                        if i.split(":")[0] == t or i == t:
                            if portsList[i].is_input and portsList[i].is_audio:
                                inPorts.append(i)

                # Connect all the ports
                for i in outPorts:
                    for j in inPorts:
                        if not is_connected(i, j):
                            connect(i, j)

            finally:
                lock.release()

    def disconnect(self, force=False):
        f, t = self._getEndpoints()
        if not f:
            return
        if not t:
            return

        if not force:
            # As garbage collection happens at uppredicatble times,
            # Don't disconnect if this airwire has been taken over by a new connection between the ports
            x = None
            try:
                x = latestAirWireForGivenPair[self.tupleid]
            except KeyError:
                pass

            if x and x is not self:
                return

        if lock.acquire(timeout=10):
            try:
                if t.endswith("*"):
                    t = t[:-1]

                if f.endswith("*"):
                    f = f[:-1]

                outPorts = []
                inPorts = []
                with portsListLock:
                    for i in portsList:
                        if i.startswith(f + ":") or i == f:
                            if portsList[i].is_output and portsList[i].is_audio:
                                outPorts.append(i)
                        if i.split(":")[0] == t or i == t:
                            if portsList[i].is_input and portsList[i].is_audio:
                                inPorts.append(i)

                if not inPorts:
                    return
                # Disconnect all the ports
                for i in outPorts:
                    for j in inPorts:
                        if is_connected(i, j):
                            try:
                                disconnect(i, j)
                            except Exception:
                                print(traceback.format_exc())
                            try:
                                del activeConnections[i, j]
                            except KeyError:
                                pass
            finally:
                lock.release()


def Airwire(f, t, force_combining=False):
    # Can't connect to nothing, for now lets use a hack and make these nonsense
    # names so emoty strings don't connect to stuff
    if not f or not t:
        f = "jdgdsjfgkldsf"
        t = "dsfjgjdsfjgkl"
    if force_combining:
        return CombiningAirwire(f, t)
    elif f is None or t is None:
        return MonoAirwire(None, None)
    elif ":" in f:
        if ":" not in t:
            return CombiningAirwire(f, t)
        return MonoAirwire(f, t)
    else:
        return MultichannelAirwire(f, t)


############################################################################
# This section manages the actual sound IO and creates jack ports
# This code runs once when the event loads. It also runs when you save the event during the test compile
# and may run multiple times when kaithem boots due to dependancy resolution
__doc__ = ""


def work():
    global _reconnecterThreadObjectStopper

    # Wait 10s before actually doing anything to avoid nuisiance chattering errors.
    # This thread mostly only fixes crashed stuff.
    for i in range(100):
        if not _reconnecterThreadObjectStopper[0]:
            return
        time.sleep(0.1)

    failcounter = 0
    while _reconnecterThreadObjectStopper[0]:
        try:
            # The _checkJack stuf won't block, because we already have the lock
            if lock.acquire(timeout=2):
                failcounter = 0
                try:
                    _checkJackClient()
                finally:
                    lock.release()
                _ensureConnections()
            else:
                failcounter += 1
                if failcounter > 2:
                    if _reconnecterThreadObjectStopper[0]:
                        raise RuntimeError("Could not get lock,retrying in 5s")

                else:
                    # Already stopping anyway, ignore
                    pass
            time.sleep(5)
        except Exception:
            time.sleep(30)
            logging.exception("Error in jack manager")


_reconnecterThreadObject = None
_reconnecterThreadObjectStopper = [0]


def start_managing(p=None, n=None):
    "Start mananaging JACK in whatever way was configured."

    global _jackclient
    global _reconnecterThreadObject

    with lock:
        try:
            _jackclient = JackClientManager()
        except Exception:
            log.exception("Error creating JACK client, retry later")

        try:
            find_real()
        except Exception:
            log.exception("Error getting initial jack graph info")

        # Stop the old thread if needed
        _reconnecterThreadObjectStopper[0] = 0
        try:
            if _reconnecterThreadObject:
                _reconnecterThreadObject.join()
        except Exception:
            pass

        _reconnecterThreadObjectStopper[0] = 1
        _reconnecterThreadObject = threading.Thread(target=work)
        _reconnecterThreadObject.name = "JackReconnector"
        _reconnecterThreadObject.daemon = True
        _reconnecterThreadObject.start()


def stop_managing():
    global _reconnecterThreadObject

    with lock:
        try:
            if _jackclient:
                _jackclient._client.deactivate()
        except Exception:
            pass
        # Stop the old thread if needed
        _reconnecterThreadObjectStopper[0] = 0
        try:
            if _reconnecterThreadObject:
                _reconnecterThreadObject.join()
        except Exception:
            pass
        _reconnecterThreadObject = None


postedCheck = True

firstConnect = False


def _checkJackClient(err=True):
    global _jackclient, realConnections, postedCheck, firstConnect

    if lock.acquire(timeout=10):
        try:
            assert _jackclient
            t = _jackclient.get_ports()

            if not t:
                if firstConnect:
                    raise RuntimeError(
                        "JACK Server not started or client not connected, will try connect "
                    )
                firstConnect = True

            if not postedCheck:
                postedCheck = True

            return True
        except Exception:
            postedCheck = False

            if firstConnect:
                firstConnect = True
            else:
                print(traceback.format_exc())

            try:
                _jackclient = None
            except Exception:
                pass

            with portsListLock:
                portsList.clear()
                _realConnections = {}

            try:
                _jackclient = JackClientManager()
            except Exception:
                if err:
                    log.exception("Error creating JACK client")
                return

            _jackclient.get_ports()
            get_ports()
            time.sleep(0.5)
            find_real()
            return True
        finally:
            lock.release()

    if not _jackclient:
        return False


def get_portsListCache():
    "We really should not need to have this refreser, it is only there in case of erro, hence the 1 hour."
    global portsList, portsCacheTime
    if time.monotonic() - portsCacheTime < 3600:
        return portsList
    portsCacheTime = time.monotonic()
    get_ports()
    return portsList


portsCacheTime = 0


lastCheckedClientFromget_ports = 0


def get_ports(*a, max_wait=10, **k):
    global portsList, _jackclient, lastCheckedClientFromget_ports

    if lock.acquire(timeout=max_wait):
        try:
            if not _jackclient:
                # MOstly here so we can use this standalone from a unit test
                if lastCheckedClientFromget_ports < time.monotonic() - 120:
                    lastCheckedClientFromget_ports = time.monotonic()
                    workers.do(_checkJackClient)
                return []
            x = _jackclient.get_ports(*a, **k)

            with portsListLock:
                # No filters means this must be the full list
                if not a and not k:
                    portsList.clear()
                for port in x:
                    portsList[port.name] = port

            return x
        finally:
            lock.release()
    return []


def get_port_names_with_aliases(*a, **k):
    if lock.acquire(timeout=10):
        try:
            if not _jackclient:
                return []
            ports = []
            x = _jackclient.get_ports(*a, **k)
            for i in x:
                for j in i.aliases:
                    if j not in ports:
                        ports.append(j)
                if i.name not in ports:
                    ports.append(i.name)
            return ports
        finally:
            lock.release()
    else:
        pass


def get_connections(name, *a, **k):
    if lock.acquire(timeout=10):
        try:
            if not _jackclient:
                return []
            try:
                return _jackclient.get_all_connections(name)
            except Exception:
                log.exception("Error getting connections")
                return []
        finally:
            lock.release()
    else:
        pass


exclude_until = [0]


def check_exclude():
    if time.monotonic() < exclude_until[0]:
        raise RuntimeError("That is not allowed, trying to auto-fix")


def disconnect(f, t):
    global realConnections
    assert _jackclient
    if lock.acquire(timeout=30):
        try:
            if not is_connected(f, t):
                return

            try:
                if isinstance(f, PortInfo):
                    f = f.name
                if isinstance(t, PortInfo):
                    t = t.name

                # Horrid hack to keep dummy connections around to not make gst stop
                if "SILENCE" in f:
                    return

                # This feels race conditionful but i think it is important so that we don't try to double-disconnect.
                # Be defensive with jack, the whole thing seems britttle
                # Let other side handle figuring out which is which
                for i in range(24):
                    # For unknown reasons it is possible to completely clog up the jack client.
                    # We must make a new one and retry should this ever happen
                    try:
                        _jackclient.disconnect(f, t)
                        # subprocess.check_call(['pw-jack', 'jack_disconnect', f, t])
                        break
                    except Exception:
                        _checkJackClient()

                with portsListLock:
                    try:
                        del _realConnections[f, t]
                        realConnections = _realConnections.copy()
                    except KeyError:
                        pass

                    try:
                        del _realConnections[t, f]
                        realConnections = _realConnections.copy()
                    except KeyError:
                        pass

            except Exception:
                print(traceback.format_exc())
        finally:
            lock.release()
    else:
        pass


def disconnect_all_from(p: str):
    "Disconnect everything to do wth given port"
    find_real()
    for i in list(realConnections.keys()):
        if i[0] == p or i[0].startswith(p + ":"):
            disconnect(*i)
        elif i[1] == p or i[1].startswith(p + ":"):
            disconnect(*i)


# This is an easy place to get a bazillion sounds queued up all waiting on the lock. This stops that.
awaiting = [0]
awaitingLock = threading.Lock()


def connect(f, t, ts=None):
    ts = ts or time.monotonic()

    global realConnections, _jackclient
    check_exclude()
    with awaitingLock:
        if awaiting[0] > 8:
            time.sleep(1)

        if awaiting[0] > 12:
            raise RuntimeError("Too many threads are waiting to make JACK connections")

        awaiting[0] += 1

    try:
        if lock.acquire(timeout=10):
            try:
                if is_connected(f, t):
                    return

                try:
                    if isinstance(f, PortInfo):
                        f = f.name
                    if isinstance(t, PortInfo):
                        t = t.name
                except Exception:
                    return

                try:
                    # Let other side handle figuring out which is which
                    for i in range(3):
                        # For unknown reasons it is possible to completely clog up the jack client.
                        # We must make a new one and retry should this ever happen
                        try:
                            assert _jackclient
                            _jackclient.connect(t, f)
                            break
                        except jack.JackErrorCode as e:
                            print(e)
                        except Exception:
                            _checkJackClient()
                    with portsListLock:
                        try:
                            _realConnections[f, t] = True
                            realConnections = _realConnections.copy()
                        except KeyError:
                            pass
                except Exception:
                    print(traceback.format_exc())
            finally:
                lock.release()
        else:
            pass
    finally:
        with awaitingLock:
            awaiting[0] -= 1
