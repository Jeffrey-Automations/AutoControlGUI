====================
Keywords & Executor
====================

The Keyword/Executor system is AutoControl's JSON-based scripting engine. You define automation
steps as JSON arrays (keywords), and the executor interprets and runs them.

Keyword Format
==============

Keywords are JSON arrays where each element is an action:

.. code-block:: json

   [
       ["function_name", {"param_name": "param_value"}],
       ["function_name", {"param_name": "param_value"}]
   ]

For example:

.. code-block:: json

   [
       ["AC_set_mouse_position", {"x": 500, "y": 300}],
       ["AC_click_mouse", {"mouse_keycode": "mouse_left"}],
       ["AC_write", {"write_string": "Hello"}]
   ]

An on / off parameter (``ignore_case``, ``present``, ``raise_on_fail``, ``paste`` …)
takes a JSON ``true`` / ``false``, or a string read by its spelling: ``"true"``,
``"yes"``, ``"on"`` and ``"1"`` are on, and any other string (``"false"``, ``"no"``,
``"off"``, ``"0"``) is off.

Available Action Commands
=========================

.. list-table::
   :header-rows: 1
   :widths: 20 80

   * - Category
     - Commands
   * - Mouse
     - ``AC_click_mouse``, ``AC_set_mouse_position``, ``AC_get_mouse_position``, ``AC_press_mouse``, ``AC_release_mouse``, ``AC_mouse_scroll``
   * - Keyboard
     - ``AC_type_keyboard``, ``AC_press_keyboard_key``, ``AC_release_keyboard_key``, ``AC_write``, ``AC_write_secret``, ``AC_hotkey``, ``AC_check_key_is_press``
   * - Image
     - ``AC_locate_all_image``, ``AC_locate_image_center``, ``AC_locate_and_click``
   * - Screen
     - ``AC_screen_size``, ``AC_screenshot``
   * - Record
     - ``AC_record``, ``AC_stop_record``
   * - Report
     - ``AC_generate_html``, ``AC_generate_json``, ``AC_generate_xml``, ``AC_generate_html_report``, ``AC_generate_json_report``, ``AC_generate_xml_report``
   * - Project
     - ``AC_create_project``
   * - Shell
     - ``AC_shell_command``
   * - Executor
     - ``AC_execute_action``, ``AC_execute_files``

Executing a JSON File
=====================

.. code-block:: python

   from je_auto_control import execute_action, read_action_json

   execute_action(read_action_json("actions.json"))

Errors and ``raise_on_error``
=============================

``execute_action`` records a failed action as its ``repr`` and runs the next
one; ``raise_on_error=True`` raises at the first failure instead. Contained
this way are the ``AutoControlException`` family and the builtin ``OSError``,
``RuntimeError``, ``ArithmeticError``, ``AttributeError``, ``TypeError``,
``ValueError``, ``LookupError`` and ``ImportError``.

A command that raises anything else -- ``cv2.error``, ``sqlite3.Error``, a
plugin's own exception class -- is wrapped at that action in
``AutoControlForeignException``, whose ``original`` attribute and
``__cause__`` hold the original error. It is then recorded like any other
failure, ``AC_try`` catches it, ``AC_retry`` retries it, ``AC_loop`` records it
per pass and ``AC_parallel`` records it in its branch. With
``raise_on_error=True`` the wrapper is what is raised, so code that caught
``cv2.error`` or ``sqlite3.Error`` around ``execute_action`` should catch
``AutoControlForeignException`` and read ``original``.

Never contained, whatever ``raise_on_error`` says: assertion failures
(``AutoControlAssertionException``, and a plugin's own ``AssertionError``),
``AC_break`` / ``AC_continue``, stop requests (``ExecutionStopped``),
cancellation, ``KeyboardInterrupt`` and ``SystemExit``.

Executing All JSON Files in a Directory
=======================================

.. code-block:: python

   from je_auto_control import execute_files, get_dir_files_as_list

   execute_files(get_dir_files_as_list("./action_files/"))

Extending the Executor
======================

You can dynamically load external Python packages into the executor:

The package gate decides which packages may load. ``AC_add_package_to_executor`` could import ``os`` or
``subprocess`` for any action list, so **no package loads unless it has been allowed**; a package that is
not on the allowlist is refused before it is imported, and its action fails with
``AutoControlExecuteActionException``. A listed package also allows its submodules. There are three ways
to allow one:

.. code-block:: python

   from je_auto_control import executor

   executor.allow_packages("time")                # these, and their submodules

.. code-block:: bash

   # every entry point: both CLIs, the socket / REST / MCP servers, the scheduler
   JE_AUTOCONTROL_ALLOWED_PACKAGES=time,my_plugins je_auto_control start-server

   # one run of the CLI; the flag may be repeated
   je_auto_control run script.json --allow-package time --allow-package my_plugins

``JE_AUTOCONTROL_ALLOWED_PACKAGES`` is a comma-separated list read once, when the process starts; an entry
that is not a dotted module name is ignored and logged. ``executor.set_allow_arbitrary_packages(True)``
opens the gate for every package, which is what releases before this one did by default (they loaded any
package and raised a ``DeprecationWarning``). None of these is an ``AC_*`` command, so an action list
cannot open its own gate.


.. code-block:: python

   from je_auto_control import package_manager

   # Load all functions from the 'time' module
   package_manager.add_package_to_executor("time")

After loading, functions are available with the ``package_function`` naming convention.
For example, ``time.sleep`` becomes ``time_sleep``:

.. code-block:: json

   [
       ["time_sleep", {"secs": 2}]
   ]

An action file may load a package and use it in the same list, provided the
gate allows that package:

.. code-block:: json

   [
       ["AC_add_package_to_executor", ["time"]],
       ["time_sleep", [2]]
   ]

Every command name is checked before the first action runs, and
``time_sleep`` does not exist until the load has run, so this list used to be
refused for an unknown command whatever the gate said. The check now leaves a
name to run time when all of these hold: it starts with ``<package>_``; an
``AC_add_package_to_executor`` earlier in the file names that package
literally (``["time"]`` or ``{"package": "time"}``, not a ``${variable}``);
and the gate would allow the package. Anything else -- a package that is not
allowed, a name used before its load, a typo in an ``AC_*`` name -- is still
rejected before anything runs. A deferred name that turns out not to exist
(``time_slep``) fails its own action with ``Unknown action`` when the run
reaches it. ``je_auto_control validate`` and the REST pre-check follow the
same rule.

To inspect the current executor command dictionary:

.. code-block:: python

   from je_auto_control import executor

   print(executor.event_dict)


Stored Action Lists, Named Registries and Generated Documents
=============================================================

**Voice commands and macros run with both authorities.** ``AC_voice_register``
and ``AC_define_macro`` record who registered the action list. When
``AC_voice_dispatch`` or ``AC_call_macro`` runs it, every step -- nested bodies
and ``AC_parallel`` branches included -- runs only if both that registrant and
the current caller have the capability the step needs; a refused step is
recorded as an ``AuthorizationError``. A stored list therefore neither borrows
an administrator's rights nor runs unchecked when the GUI or Python dispatches
it. A store-backed registrant is re-read at dispatch, so a deleted user's lists
stop running. The macro table is shared by every server: a principal may
redefine only its own macros, while trusted local code (no RBAC scope) may
redefine any and its macros cannot be replaced by a user. Anonymous MCP
sessions act as an ``mcp:<session>`` operator, so this applies to them even with
RBAC off; outside RBAC and MCP nothing changes.

**Named registries are capped.** The stores behind ``AC_cas_put`` /
``AC_cas_get``, ``AC_dedup_check``, ``AC_idempotency_begin`` / ``_complete`` /
``_release``, ``AC_bulkhead_run``, ``AC_sequence_observe`` and
``AC_outbox_enqueue`` / ``AC_outbox_pending`` hold at most
``MAX_REGISTRY_NAMES`` (1,024) names each. At the cap an existing name keeps
working and nothing is evicted; a new name, including a read of a name never
written, raises ``RegistryFullError`` naming the registry. None has a delete or
reset command, so names are released when the process ends.

**Generated documents keep references.** ``AC_generate_sop`` (``actions``,
``title``) and ``AC_generate_code`` (``source``) substitute known ``${var}``
placeholders -- a ``source`` path built from variables included -- but write
``${secrets.NAME}``, names not bound yet (a loop variable the documented steps
set), nested placeholders and variables holding a value the run resolved as a
secret exactly as written.

**Resolved env:// values are masked.** ``AC_resolve_ref`` and
``AC_resolve_refs`` still return ``env://`` values to the caller, but register
them with the run's secret mask, so the log, the journal and the MCP audit show
``***`` for the rest of the run. ``AC_resolve_ref``'s ``value`` and
``AC_resolve_refs``'s ``resolved`` are masked in the logged result and the
Script Builder result pane. ``file://`` values are not registered.

Stopping a run
--------------

A stop (or a cancellation) ends the wait of the command in progress with ``ExecutionStopped``:
waits and pauses, shell commands that capture output, the shared HTTP client, template matching,
OCR, VLM and LLM requests, read-only accessibility reads, adb commands, the USB and Wayland
capture tools, mobile device calls and find-element waits, ``AC_wait_for_port`` probes,
``AC_send_email`` (the message may or may not have been delivered), ``AC_feature_match``, each
model call of ``AC_agent_run`` / ``AC_computer_use``, ``AC_assert_audio`` / ``AC_assert_video``
and the admin console's poll and broadcast (hosts not reached yet are skipped). A mobile device
session caught mid-call is closed, as on a timeout. A native call that cannot be interrupted keeps
running in the background and its result is discarded.

Still not interruptible: accessibility writes (set value / invoke / toggle), the join of
``AC_parallel`` (held keys are released only once every branch has ended) and the finalisation of
a screen recording.
