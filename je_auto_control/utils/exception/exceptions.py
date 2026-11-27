# general
class AutoControlException(Exception):
    """Base class for every AutoControl runtime error.

    All framework exceptions derive from this so that containment boundaries
    (executor, background poll loops, request handlers, GUI slots) can catch
    the whole family with a single ``except AutoControlException``. Do not add
    a sibling that inherits ``Exception`` directly, or only a builtin such as
    ``RuntimeError`` — that silently escapes every such boundary. List this
    class first and keep the builtin when existing callers catch it.
    """


# Keyboard
class AutoControlKeyboardException(AutoControlException):
    pass


class AutoControlCantFindKeyException(AutoControlException):
    pass


# Mouse
class AutoControlMouseException(AutoControlException):
    pass


# Screen


class AutoControlScreenException(AutoControlException):
    pass


# Image detect


class ImageNotFoundException(AutoControlException):
    """The template image was searched for and is not there."""


class ImageSearchInputException(AutoControlException):
    """An image search could not run on what it was given, so it says nothing about the screen.

    A missing or unreadable template, a single-colour one, a threshold outside
    0-1 (or NaN), or a frame OpenCV cannot match. A sibling of
    :class:`ImageNotFoundException`, not a subclass: an absence check
    (``AC_assert_image(present=False)``, ``AC_wait_image_gone``, the else
    branch of ``AC_if_image_found``) that catches "not found" must not pass
    on a misspelled template path. It stays in the family, so every
    containment boundary still records it as the action's failure.
    """


class AutoControlFlatTemplateException(AutoControlScreenException):
    """Template has (almost) no variation, so normalised correlation degenerates.

    A subclass rather than a sibling, so existing ``except
    AutoControlScreenException`` handlers keep catching it; callers that want to
    tell the user what to do about it (crop something with a pattern in it) can
    catch this one specifically.
    """


# Record


class AutoControlRecordException(AutoControlException):
    pass


# Execute action

class AutoControlExecuteActionException(AutoControlException):
    pass


class AutoControlJsonActionException(AutoControlException):
    pass


class AutoControlActionNullException(AutoControlException):
    pass


class AutoControlActionException(AutoControlException):
    pass


class AutoControlForeignException(AutoControlActionException):
    """A command raised an error from outside the framework family.

    ``cv2.error``, ``sqlite3.Error`` or a plugin's own exception class, which
    no containment boundary names. The executor wraps it at the per-action
    boundary so it is recorded as that action's failure instead of aborting
    the action list; the original is ``original`` and the ``__cause__``.
    """

    def __init__(self, command: str, error: BaseException) -> None:
        kind = type(error)
        super().__init__(f"{command} raised {kind.__module__}.{kind.__qualname__}: {error}")
        self.command = command
        self.original = error


class AutoControlAddCommandException(AutoControlException):
    pass


class AutoControlAssertionException(AutoControlException):
    """Raised when an ``AC_assert_*`` check fails."""


class AutoControlArgparseException(AutoControlException):
    pass


# html exception

class AutoControlHTMLException(AutoControlException):
    pass


# Json Exception

class AutoControlJsonException(AutoControlException):
    pass


class AutoControlGenerateJsonReportException(AutoControlException):
    pass


# XML

class XMLException(AutoControlException):
    pass


class XMLTypeException(AutoControlException):
    pass


# Execute callback
class CallbackExecutorException(AutoControlException):
    pass


# Platform capability
class AutoControlUnsupportedOperationException(
        AutoControlException, NotImplementedError):
    """An operation the current platform's backend cannot perform.

    Inherits both on purpose. ``NotImplementedError`` is what the GUI tabs and
    the REST handler already catch to say "not on this platform", and that
    behaviour is kept; ``AutoControlException`` is what the executor and the
    other containment boundaries catch, and a bare ``NotImplementedError``
    slipped straight past all of them — aborting a whole script where a single
    action should have been reported as failed.
    """


# Action-file signatures
class AutoControlSignatureException(AutoControlException):
    """An action file that had to be signed failed verification and was not run.

    Raised where a file is refused -- a missing sidecar, a mismatch, a key
    this endpoint does not trust -- so a server can answer "refused" rather
    than "crashed". Still an :class:`AutoControlException`, which is what
    this was before the type existed.
    """


# Optional dependency
class CryptographyUnavailableError(AutoControlException, RuntimeError):
    """A feature needs ``cryptography`` and the package is not installed.

    ``cryptography`` publishes no Windows arm64 wheel, so it is absent there by
    design and the message carries the install hint. Inherits ``RuntimeError``
    because that is what these accessors raised before the type existed.
    """
