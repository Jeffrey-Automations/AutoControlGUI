"""A contained launcher exiting is insufficient: all actual Job processes must retire first."""
import ctypes
import sys
from types import SimpleNamespace

import pytest

from je_auto_control.utils.agent_runtime.errors import AgentTaskError


class Kernel:
    def __init__(self):
        self.events, self.counts = [], [0]
        self.terminate_ok = self.query_ok = self.close_ok = True
        self.processes, self.handles, self.signals = [], {}, {}
        self.belongs = True

    def CreateJobObjectW(self, *_unused):
        return 0x100000001

    def SetInformationJobObject(self, handle, _kind, _data, _size):
        assert handle == 0x100000001
        return True

    def AssignProcessToJobObject(self, handle, process):
        assert (handle, process) == (0x100000001, 99)
        return True

    def TerminateJobObject(self, handle, _code):
        assert handle == 0x100000001
        self.events.append('terminate')
        return self.terminate_ok

    def QueryInformationJobObject(self, handle, kind, pointer, size, _length):
        assert handle == 0x100000001
        if kind == 3:
            from je_auto_control.utils.agent_runtime.native_job import _ProcessList
            value = ctypes.cast(pointer, ctypes.POINTER(_ProcessList)).contents
            value.assigned = value.listed = len(self.processes)
            for index, pid in enumerate(self.processes):
                value.pids[index] = pid
            return self.query_ok
        assert kind == 1
        from je_auto_control.utils.agent_runtime.native_job import _Accounting
        assert size == ctypes.sizeof(_Accounting) == 48
        value = ctypes.cast(pointer, ctypes.POINTER(_Accounting)).contents
        value.active = self.counts[0]
        if len(self.counts) > 1:
            self.counts.pop(0)
        self.events.append(('active', value.active))
        return self.query_ok

    def CloseHandle(self, handle):
        if handle in self.handles:
            self.events.append(('process-close', self.handles[handle]))
            if self.close_ok:
                del self.handles[handle]
            return self.close_ok
        assert handle == 0x100000001
        self.events.append('close')
        return self.close_ok

    def OpenProcess(self, access, inherit, pid):
        assert access == 0x101000
        assert not inherit
        assert pid in self.processes
        handle = 0x200000000 + pid
        self.handles[handle] = pid
        return handle

    def IsProcessInJob(self, process, job, pointer):
        assert process in self.handles
        assert job == 0x100000001
        ctypes.cast(pointer, ctypes.POINTER(ctypes.c_int)).contents.value = self.belongs
        return True

    def WaitForSingleObject(self, process, milliseconds):
        pid = self.handles[process]
        self.events.append(('process-wait', pid, milliseconds))
        return self.signals.get(pid, 0)


def owned(monkeypatch):
    from je_auto_control.utils.agent_runtime import native_job
    kernel = Kernel()
    monkeypatch.setattr(native_job, '_kernel', lambda: kernel)
    return native_job.NativeJob(SimpleNamespace(_handle=99)), kernel, native_job


def test_job_termination_is_confirmed_empty_before_the_owned_handle_is_closed(monkeypatch):
    job, kernel, _module = owned(monkeypatch)
    kernel.counts = [2, 1, 0]
    job.close()
    assert kernel.events == ['terminate', ('active', 2), ('active', 1), ('active', 0), 'close']
    job.close()
    assert kernel.events.count('close') == 1


@pytest.mark.parametrize('failure', ['terminate_ok', 'query_ok', 'close_ok'])
def test_failed_job_retirement_retains_ownership_and_never_claims_closed(monkeypatch, failure):
    job, kernel, _module = owned(monkeypatch)
    setattr(kernel, failure, False)
    with pytest.raises(AgentTaskError):
        job.close()
    assert job._handle == 0x100000001
    setattr(kernel, failure, True)
    job.close()
    assert job._handle is None


def test_nonempty_tree_exhausts_original_bound_and_remains_owned(monkeypatch):
    job, kernel, module = owned(monkeypatch)
    kernel.counts = [1]
    now = [0.0]
    sleeps = []

    def sleep(delay):
        sleeps.append(delay)
        now[0] += delay

    monkeypatch.setattr(module, 'time', SimpleNamespace(monotonic=lambda: now[0], sleep=sleep), raising=False)
    with pytest.raises(AgentTaskError):
        job.close(timeout=0.03)
    assert now[0] <= 0.03
    assert sleeps
    assert job._handle == 0x100000001
    assert 'close' not in kernel.events
    kernel.counts = [0]
    job.close()
    assert job._handle is None


def test_job_and_launcher_reaping_share_one_original_three_second_deadline(monkeypatch):
    from je_auto_control.utils.agent_runtime import native_channel
    now, observed = [0.0], []

    def close(*, timeout):
        observed.append(('job', timeout))
        now[0] += 2

    instance = object.__new__(native_channel.OwnedChannel)
    instance._job = SimpleNamespace(close=close)
    instance._process = SimpleNamespace(wait=lambda *, timeout: observed.append(('process', timeout)))
    monkeypatch.setattr(native_channel, 'sys', SimpleNamespace(platform='win32'))
    monkeypatch.setattr(native_channel, 'time', SimpleNamespace(monotonic=lambda: now[0]))
    instance._stop_process()
    assert observed == [('job', 3), ('process', 1)]


def test_a_rounded_remaining_time_never_exceeds_the_jobs_three_second_bound(monkeypatch):
    from je_auto_control.utils.agent_runtime import native_channel
    reading = 32765.838  # (reading + 3) - reading == 3.000000000003638
    assert (reading + 3) - reading > 3
    observed = []
    instance = object.__new__(native_channel.OwnedChannel)
    instance._job = SimpleNamespace(close=lambda *, timeout: observed.append(timeout))
    instance._process = SimpleNamespace(wait=lambda *, timeout: None)
    monkeypatch.setattr(native_channel, 'sys', SimpleNamespace(platform='win32'))
    monkeypatch.setattr(native_channel, 'time', SimpleNamespace(monotonic=lambda: reading))
    instance._stop_process()
    assert observed == [3]


def test_process_objects_must_signal_even_after_the_job_reports_no_active_processes(monkeypatch):
    job, kernel, _module = owned(monkeypatch)
    kernel.processes = [201, 202]
    kernel.signals[202] = 258
    with pytest.raises(AgentTaskError):
        job.close(timeout=0.03)
    assert job._handle == 0x100000001
    assert 'close' not in kernel.events
    assert any(event[:2] == ('process-wait', 202) for event in kernel.events if isinstance(event, tuple))
    assert kernel.handles
    kernel.processes = []
    kernel.signals[202] = 0
    job.close()
    assert job._handle is None
    assert not kernel.handles


def test_process_object_queries_may_never_select_a_process_outside_the_actual_owned_job(monkeypatch):
    job, kernel, _module = owned(monkeypatch)
    kernel.processes, kernel.belongs = [201], False
    with pytest.raises(AgentTaskError):
        job.close()
    assert 'terminate' in kernel.events
    assert 'close' not in kernel.events
    assert not kernel.handles


def test_member_capture_cannot_spend_past_the_original_retirement_deadline(monkeypatch):
    job, kernel, module = owned(monkeypatch)
    kernel.processes = list(range(201, 301))
    now = [0.0]
    original = kernel.OpenProcess

    def delayed(*args):
        now[0] += 0.01
        return original(*args)

    monkeypatch.setattr(kernel, 'OpenProcess', delayed)
    monkeypatch.setattr(module, 'time', SimpleNamespace(monotonic=lambda: now[0]))
    with pytest.raises(AgentTaskError):
        job.close(timeout=0.03)
    assert now[0] <= 0.03
    assert 'terminate' in kernel.events
    assert job._handle is not None
    assert 'close' not in kernel.events


def test_already_exhausted_deadline_still_terminates_only_the_owned_job(monkeypatch):
    job, kernel, _module = owned(monkeypatch)
    kernel.counts = [1]
    with pytest.raises(AgentTaskError):
        job.close(timeout=0)
    assert 'terminate' in kernel.events
    assert 'close' not in kernel.events
    assert job._handle == 0x100000001


class ThreadKernel(Kernel):
    """Adds the Toolhelp thread snapshot and suspend-count calls used by ``resume``."""

    def __init__(self):
        super().__init__()
        self.threads = [(7, 50), (8, 99), (9, 51)]
        self.previous = 1
        self.opened = []

    def CreateToolhelp32Snapshot(self, kind, pid):
        assert (kind, pid) == (0x4, 0)
        self.handles[0x300000000] = 'snapshot'
        self._cursor = 0
        return 0x300000000

    def _fill(self, pointer):
        from je_auto_control.utils.agent_runtime.native_job import _ThreadEntry
        entry = ctypes.cast(pointer, ctypes.POINTER(_ThreadEntry)).contents
        assert entry.length == ctypes.sizeof(_ThreadEntry) == 28
        if self._cursor >= len(self.threads):
            return False
        entry.thread, entry.owner = self.threads[self._cursor]
        self._cursor += 1
        return True

    def Thread32First(self, snapshot, pointer):
        assert snapshot == 0x300000000
        return self._fill(pointer)

    def Thread32Next(self, snapshot, pointer):
        assert snapshot == 0x300000000
        return self._fill(pointer)

    def OpenThread(self, access, inherit, thread):
        assert (access, inherit) == (0x2, False)
        self.opened.append(thread)
        self.handles[0x400000000 + thread] = 'thread'
        return 0x400000000 + thread

    def ResumeThread(self, thread):
        self.events.append(('resume', thread - 0x400000000))
        return self.previous


def threaded(monkeypatch):
    from je_auto_control.utils.agent_runtime import native_job
    kernel = ThreadKernel()
    monkeypatch.setattr(native_job, '_kernel', lambda: kernel)
    return native_job.NativeJob(SimpleNamespace(_handle=99)), kernel


def test_resume_releases_only_the_sole_suspended_thread_of_the_owned_pid(monkeypatch):
    job, kernel = threaded(monkeypatch)
    job.resume(99)
    assert kernel.opened == [8]
    assert ('resume', 8) in kernel.events
    assert kernel.handles == {}


@pytest.mark.parametrize('threads', [[(7, 50)], [(8, 99), (9, 99)]])
def test_resume_refuses_a_process_without_exactly_one_thread(monkeypatch, threads):
    job, kernel = threaded(monkeypatch)
    kernel.threads = threads
    with pytest.raises(AgentTaskError, match='exactly one thread'):
        job.resume(99)
    assert kernel.opened == []
    assert kernel.handles == {}


@pytest.mark.parametrize('previous', [0, 2, 0xFFFFFFFF])
def test_resume_refuses_a_thread_that_was_not_suspended_exactly_once(monkeypatch, previous):
    job, kernel = threaded(monkeypatch)
    kernel.previous = previous
    with pytest.raises(AgentTaskError, match='suspended exactly once'):
        job.resume(99)
    assert kernel.handles == {}


def test_resume_refuses_once_the_job_is_closed(monkeypatch):
    job, kernel = threaded(monkeypatch)
    job.close()
    with pytest.raises(AgentTaskError, match='not open'):
        job.resume(99)
    assert kernel.opened == []


SPAWNER = '''
import os, subprocess, sys
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
with open(sys.argv[1] + ".tmp", "w") as report:
    report.write(str(child.pid))
os.replace(sys.argv[1] + ".tmp", sys.argv[1])
sys.stdin.buffer.readline()
'''


def _reported_pid(path, deadline=10.0):
    import time
    end = time.monotonic() + deadline
    while time.monotonic() < end:
        if path.exists():
            return int(path.read_text())
        time.sleep(0.02)
    raise AssertionError('helper never reported its child')


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows Job Objects only')
def test_a_child_spawned_at_helper_startup_is_already_inside_the_owned_job(tmp_path):
    from je_auto_control.utils.agent_runtime.native_channel import OwnedChannel
    from je_auto_control.utils.agent_runtime.native_job import _kernel
    report = tmp_path / 'child.pid'
    channel = OwnedChannel([sys.executable, '-u', '-c', SPAWNER, str(report)])
    kernel = _kernel()
    grandchild = None
    try:
        grandchild = kernel.OpenProcess(0x101000, False, _reported_pid(report))
        assert grandchild
        belongs = ctypes.c_int()
        assert kernel.IsProcessInJob(grandchild, channel._job._handle, ctypes.byref(belongs))
        assert belongs.value
    finally:
        channel.close()
    assert channel.retired
    if grandchild:
        assert kernel.WaitForSingleObject(grandchild, 3000) == 0
        kernel.CloseHandle(grandchild)


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows Job Objects only')
def test_the_helper_starts_suspended_and_resumes_only_after_the_job_owns_it(monkeypatch):
    from je_auto_control.utils.agent_runtime import native_channel, native_job
    order = []

    class Process:
        pid, stdin, stdout = 4242, None, None

        def __init__(self, argv, **options):
            order.append(('popen', options['creationflags'] & 0x4))

    class Job:
        def __init__(self, process):
            order.append('job')

        def resume(self, pid):
            order.append(('resume', pid))

        def close(self, *, timeout):
            order.append('close')

    monkeypatch.setattr(native_channel.subprocess, 'Popen', Process)
    monkeypatch.setattr(native_job, 'NativeJob', Job)
    monkeypatch.setattr(native_channel.threading, 'Thread', lambda **_kw: SimpleNamespace(start=lambda: None))
    native_channel.OwnedChannel(['helper'])
    assert order == [('popen', 0x4), 'job', ('resume', 4242)]


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows Job Objects only')
def test_a_failed_resume_retires_the_still_suspended_helper_through_its_job(monkeypatch):
    from je_auto_control.utils.agent_runtime import native_channel, native_job
    closed = []

    class Process:
        pid, stdin, stdout = 4242, None, None

        def __init__(self, argv, **options):
            pass

        def wait(self, *, timeout):
            closed.append('reaped')

    class Job:
        def __init__(self, process):
            pass

        def resume(self, pid):
            raise AgentTaskError('suspended native helper does not have exactly one thread')

        def close(self, *, timeout):
            closed.append('job')

    monkeypatch.setattr(native_channel.subprocess, 'Popen', Process)
    monkeypatch.setattr(native_job, 'NativeJob', Job)
    with pytest.raises(AgentTaskError, match='exactly one thread'):
        native_channel.OwnedChannel(['helper'])
    assert closed == ['job', 'reaped']
