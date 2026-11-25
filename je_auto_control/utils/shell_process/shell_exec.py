import locale
import os
import queue
import shlex
import signal
import subprocess  # nosec B404  # reason: ShellManager intentionally invokes user-supplied subprocesses without shell
import sys
import time
from threading import Thread
from typing import IO, List, Optional

from je_auto_control.utils.exception.cancellation import (
    cancellation_checkpoint, current_cancellation_token,
)
from je_auto_control.utils.exception.exceptions import AutoControlActionException
from je_auto_control.utils.executor.run_control import checkpoint, current_stop_token
from je_auto_control.utils.logging.logging_instance import autocontrol_logger


def console_encoding() -> str:
    """The encoding a console program writes in: on Windows the ANSI code page.

    ``locale.getpreferredencoding(False)`` answers ``utf-8`` in UTF-8 mode,
    which Python 3.15 turns on by default (PEP 686), while ``cmd``, ``sc`` or
    ``ipconfig`` keep writing the code page (cp950 on Traditional Chinese
    Windows), so their output came back as replacement characters.
    ``locale.getencoding`` (3.11+) ignores UTF-8 mode. Elsewhere the preferred
    encoding stays: a UTF-8 locale gives the same answer either way.
    """
    getencoding = getattr(locale, "getencoding", None)
    if sys.platform == "win32" and getencoding is not None:
        return getencoding()
    return locale.getpreferredencoding(False)


def command_args(shell_command: str | List[str]) -> str | List[str]:
    """What to hand ``subprocess`` for ``shell_command``, never through a shell.

    A list is the argv. A string is split with POSIX rules, except on
    native Windows (not Cygwin or MSYS, whose ``subprocess`` is POSIX), where
    it goes to ``CreateProcess`` as the command line it is:
    ``shlex`` in non-POSIX mode keeps the quote characters in each token, and
    ``subprocess`` then quoted them again -- ``"C:\\Program Files\\x"`` arrived
    with its quotes and a quoted executable path was not found.
    """
    if isinstance(shell_command, list):
        return [str(part) for part in shell_command]
    if sys.platform == "win32":
        return str(shell_command)
    return shlex.split(shell_command)


_BATCH_SUFFIXES = (".bat", ".cmd")
_CMD_METACHARACTERS = frozenset('&|<>^%!"\r\n')


def refuse_batch_metacharacters(args: str | List[str]) -> None:
    """Refuse an argv list for a .bat / .cmd file whose arguments hold cmd syntax.

    Windows runs a batch file through cmd.exe, which parses the command line
    again: ``subprocess`` quotes each argument for CreateProcess but not for
    cmd, so ``["run.bat", "x&calc"]`` also started calc. A string command is
    the caller's own command line and is left alone.
    """
    if sys.platform != "win32" or not isinstance(args, list) or not args:
        return
    if not args[0].lower().endswith(_BATCH_SUFFIXES):
        return
    for arg in args[1:]:
        if _CMD_METACHARACTERS.intersection(arg):
            raise ValueError(f"batch file argument {arg!r} contains cmd metacharacters")


def program_of(shell_command: str | List[str] | None) -> str:
    """The program a command runs, which is all of it that may be logged.

    The arguments can hold a ``${secrets.*}`` value already filled in, and
    the whole command used to be logged, and written to the log file.
    """
    if isinstance(shell_command, list):
        return str(shell_command[0]) if shell_command else ""
    text = str(shell_command or "").strip()
    if text.startswith('"'):
        return text[1:].split('"', 1)[0]
    return text.split(" ", 1)[0]


def _taskkill_path() -> str:
    return os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "taskkill.exe")


def _kill_tree(process: subprocess.Popen[bytes]) -> None:
    """Kill ``process`` and everything it started."""
    if sys.platform == "win32":
        taskkill = [_taskkill_path(), "/T", "/F", "/PID", str(process.pid)]
        try:
            subprocess.run(taskkill, capture_output=True, timeout=10, check=False)  # nosec B603  # nosemgrep  # reason: fixed system tool, our child's pid
        # Its failure replaced the stop or timeout being raised, and the
        # program itself was then not killed below.
        except (OSError, subprocess.SubprocessError) as error:
            autocontrol_logger.error("taskkill failed: %r", error)
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    try:
        process.kill()
    except OSError:
        pass


_STOP_POLL_SECONDS = 0.1
#: Output lines a manager keeps until they are read; the oldest make room.
MAX_QUEUED_LINES = 10_000
_READER_JOIN_SECONDS = 1.0


def _communicate_stoppable(process: subprocess.Popen[bytes], argv: str | List[str], timeout_s: float,
                           input_bytes: Optional[bytes]) -> tuple[bytes, bytes]:
    """``communicate`` within ``timeout_s``, checking for a stop or a cancellation between short waits."""
    if current_stop_token() is None and current_cancellation_token() is None:
        return process.communicate(input_bytes, timeout=timeout_s)
    deadline = time.monotonic() + timeout_s
    pending = input_bytes
    while True:
        cancellation_checkpoint()
        checkpoint()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(argv, timeout_s)
        try:
            return process.communicate(pending, timeout=min(remaining, _STOP_POLL_SECONDS))
        except subprocess.TimeoutExpired:
            pending = None  # communicate keeps feeding what it was given; it refuses input a second time


def run_captured(argv: str | List[str], timeout_s: float,
                 input_bytes: Optional[bytes] = None) -> subprocess.CompletedProcess[bytes]:
    """Run ``argv`` (no shell), capturing stdout and stderr as bytes, for at most ``timeout_s``.

    ``subprocess.run(timeout=...)`` kills only the program itself and then
    waits, without a limit, for everything still holding its pipes: a
    program that started one of its own (``cmd /c ping -n 9 ...`` took 8 s
    with a 1 s timeout) held the caller until it ended. On timeout the
    whole process tree is killed, then ``TimeoutExpired`` is raised.

    Inside a stoppable run or a cancellation scope the wait wakes every
    ``_STOP_POLL_SECONDS``: a stop or a cancellation kills the tree the same
    way and propagates (``ExecutionStopped`` / the token's own error) instead
    of holding the caller until the program or the timeout ends.
    """
    # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit.dangerous-subprocess-use-audit
    process = subprocess.Popen(argv, stdin=subprocess.PIPE if input_bytes is not None else None,  # nosec B603  # reason: argv list or CreateProcess line, never a shell
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               # its own process group on POSIX, so the timeout can end all of it
                               start_new_session=sys.platform != "win32")
    try:
        stdout, stderr = _communicate_stoppable(process, argv, timeout_s, input_bytes)
    except BaseException:  # reason: end the tree on a timeout, a stop or any other escape, then re-raise
        _kill_tree(process)
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            autocontrol_logger.error("%s: output pipes still open after the kill", program_of(argv))
        raise
    return subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)  # nosemgrep  # reason: runs nothing


class ShellManager:
    """
    ShellManager
    Shell 指令管理器
    - 執行外部 shell 指令 (不使用 shell=True，避免注入)
    - 使用背景執行緒持續讀取 stdout / stderr
    - 將輸出放入 queue，供 pull_text() 取出
    """

    def __init__(self, shell_encoding: Optional[str] = None, program_buffer: int = 10240000) -> None:
        """
        :param shell_encoding: shell command read output encoding; by default
            the locale's, which is what a console program writes on Windows
            (UTF-8 turned ``磁碟區`` into replacement characters)
        :param program_buffer: buffer size
        """
        self.read_program_error_output_from_thread: Thread | None = None
        self.read_program_output_from_thread: Thread | None = None
        self.still_run_shell: bool = False
        self.process: subprocess.Popen[bytes] | None = None
        self.run_output_queue: queue.Queue[str] = queue.Queue()
        self.run_error_queue: queue.Queue[str] = queue.Queue()
        self.program_encoding: str = shell_encoding or console_encoding()
        self.program_buffer: int = program_buffer

    def exec_shell(self, shell_command: str | List[str] | None = None, *,
                   command: str | List[str] | None = None) -> None:
        """
        Execute shell command with shell=False.
        執行 shell 指令 (shell=False，呼叫端需自備 argv 或可被 shlex 切分的字串)

        ``command`` is accepted as another name for ``shell_command`` -- the
        name ``AC_shell_to_var`` and the documented examples use. The manager
        runs one program at a time: starting another ends the one before.
        A program that cannot start raises ``AutoControlActionException``;
        it used to be logged and reported as success.
        """
        shell_command = shell_command if shell_command is not None else command
        if shell_command is None:
            raise ValueError("exec_shell needs shell_command")
        autocontrol_logger.info("exec_shell: %s", program_of(shell_command))
        try:
            self.exit_program()
            args = command_args(shell_command)
            refuse_batch_metacharacters(args)
            # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit.dangerous-subprocess-use-audit
            self.process = subprocess.Popen(  # nosec B603  # reason: shell=False, argv list validated via _normalize_command
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
            )

            self.still_run_shell = True

            self.read_program_output_from_thread = Thread(
                target=self._read_stream,
                args=(self.process.stdout, self.run_output_queue),
                daemon=True,
            )
            self.read_program_output_from_thread.start()

            self.read_program_error_output_from_thread = Thread(
                target=self._read_stream,
                args=(self.process.stderr, self.run_error_queue),
                daemon=True,
            )
            self.read_program_error_output_from_thread.start()

        except (OSError, ValueError) as error:
            raise AutoControlActionException(
                f"exec_shell: {program_of(shell_command)} could not start: {error}") from error

    def pull_text(self) -> None:
        """
        Pull text from queues and log.
        從 queue 取出訊息並透過 logger 輸出
        """
        try:
            while not self.run_error_queue.empty():
                error_message = self.run_error_queue.get_nowait().strip()
                if error_message:
                    autocontrol_logger.error(error_message)

            while not self.run_output_queue.empty():
                output_message = self.run_output_queue.get_nowait().strip()
                if output_message:
                    autocontrol_logger.info(output_message)

        except queue.Empty:
            pass

        if self.process and self.process.poll() is not None:
            self._join_readers()
            self.exit_program()

    def _join_readers(self) -> None:
        """Let the readers finish what an ended program left in its pipes.

        Bounded: a program of its own that it left running can hold them open.
        """
        for reader in (self.read_program_output_from_thread, self.read_program_error_output_from_thread):
            if reader is not None:
                reader.join(timeout=_READER_JOIN_SECONDS)

    def exit_program(self) -> None:
        """
        Exit program and clean resources.
        結束程式並清理資源
        """
        self.still_run_shell = False

        if self.process is not None:
            self._terminate_and_reap(self.process)
            self.process = None

        self.log_and_clear_queue()

    def _terminate_and_reap(self, process: subprocess.Popen[bytes]) -> None:
        """Terminate ``process``, wait for the real exit code, and reap it."""
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                autocontrol_logger.error("Shell command did not exit after kill")
        autocontrol_logger.info(
            f"Shell command exit with code {process.returncode}"
        )

    def log_and_clear_queue(self) -> None:
        """
        Log and clear queues.
        透過 logger 輸出並清空 queue
        """
        while not self.run_output_queue.empty():
            autocontrol_logger.info(self.run_output_queue.get_nowait().strip())

        while not self.run_error_queue.empty():
            autocontrol_logger.error(self.run_error_queue.get_nowait().strip())

        self.run_output_queue = queue.Queue()
        self.run_error_queue = queue.Queue()

    def _read_stream(self, stream: Optional[IO[bytes]], target_queue: queue.Queue[str]) -> None:

        """
        Read stream line by line and put into queue, keeping the newest ``MAX_QUEUED_LINES``.
        讀取輸出流並放入 queue

        Nothing reads the queue of a program ``start_exe`` launched, so a
        chatty one grew it in memory for as long as it ran.
        """
        while self.still_run_shell and stream:
            line = stream.readline(self.program_buffer)
            if not line:
                break
            _make_room(target_queue)
            target_queue.put_nowait(line.decode(self.program_encoding, "replace"))


def _make_room(lines: queue.Queue[str]) -> None:
    """Drop the oldest lines until one more fits in ``MAX_QUEUED_LINES``."""
    while lines.qsize() >= MAX_QUEUED_LINES:
        try:
            lines.get_nowait()
        except queue.Empty:
            return


default_shell_manager = ShellManager()
