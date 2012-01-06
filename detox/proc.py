import eventlet
import sys
import py
from eventlet.processes import Process, DeadProcess
from eventlet.timeout import Timeout
from eventlet.green.subprocess import Popen, PIPE, STDOUT
from eventlet import GreenPool
import eventlet
import tox._config
import tox._cmdline

def timelimited(secs, func):
    if secs is not None:
        with Timeout(secs):
            return func()
    return func()

class FileSpinner:
    chars = "- \ | / - \ | /".split()
    def __init__(self):
        self.path2last = {}

    def getchar(self, path):
        try:
            lastsize, charindex = self.path2last[path]
        except KeyError:
            lastsize, charindex = 0, 0
        newsize = path.size()
        if newsize != lastsize:
            charindex += 1
        self.path2last[path] = (lastsize, charindex)
        return self.chars[charindex % len(self.chars)]


class ToxReporter(tox._cmdline.Reporter):
    actionchar = "+"

    def _loopreport(self):
        filespinner = FileSpinner()
        while 1:
            eventlet.sleep(0.2)
            msg = []
            for action in self.session._actions:
                for popen in action._popenlist:
                    if popen.poll() is None:
                        spinnchar = filespinner.getchar(popen.outpath)
                        if action.venv:
                            id = action.venv.envconfig.envname
                        else:
                            id = ""
                        msg.append("%s %s %s" % (
                            id, action.activity, spinnchar))
            if msg:
                self.tw.reline("   ".join(msg))

    def __getattr__(self, name):
        if name[0] == "_":
            raise AttributeError(name)

        def generic_report(*args):
            self._calls.append((name,)+args)
            if self.config.opts.verbosity >= 2:
                print ("%s" %(self._calls[-1], ))
        return generic_report

    #def logpopen(self, popen):
    #    self._tw.line(msg)

    #def popen_error(self, msg, popen):
    #    self._tw.line(msg, red=True)
    #    self._tw.line("logfile: %s" % popen.stdout.name)

class Detox:
    def __init__(self, toxconfig):
        self._toxconfig = toxconfig
        self._resources = Resources(self)

    def startloopreport(self):
        if self.toxsession.report.tw.hasmarkup:
            eventlet.spawn_n(self.toxsession.report._loopreport)

    @property
    def toxsession(self):
        try:
            return self._toxsession
        except AttributeError:
            self._toxsession = tox._cmdline.Session(
                self._toxconfig, Report=ToxReporter, popen=Popen)
            return self._toxsession

    def provide_sdist(self):
        return self.toxsession.sdist()

    def provide_venv(self, venvname):
        venv = self.toxsession.getvenv(venvname)
        self.toxsession.setupenv(venv, None)
        return venv

    def runtests(self, venvname):
        venv, sdist = self.getresources("venv:%s" % venvname, "sdist")
        venv.install_sdist(sdist)
        self.toxsession.runtestenv(venv, sdist, redirect=True)

    def runtestsmulti(self, envlist):
        pool = GreenPool()
        for env in envlist:
            pool.spawn_n(self.runtests, env)
        pool.waitall()
        retcode = self._toxsession._summary()
        return retcode

    def getresources(self, *specs):
        return self._resources.getresources(*specs)

class Resources:
    def __init__(self, providerbase):
        self._providerbase = providerbase
        self._spec2thread = {}
        self._pool = GreenPool(1000)
        self._resources = {}

    def _dispatchprovider(self, spec):
        parts = spec.split(":", 1)
        name = parts.pop(0)
        provider = getattr(self._providerbase, "provide_" + name)
        self._resources[spec] = res = provider(*parts)
        return res

    def getresources(self, *specs):
        for spec in specs:
            if spec not in self._resources:
                if spec not in self._spec2thread:
                    t = self._pool.spawn(self._dispatchprovider, spec)
                    self._spec2thread[spec] = t
        l = []
        for spec in specs:
            if spec not in self._resources:
                self._spec2thread[spec].wait()
            l.append(self._resources[spec])
        return l
