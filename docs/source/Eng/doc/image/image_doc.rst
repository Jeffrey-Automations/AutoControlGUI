=================
Image Recognition
=================

AutoControl uses OpenCV template matching to locate UI elements on the screen.
This is useful for finding buttons, icons, or other visual elements and interacting with them.

Locate All Matches
==================

Find all occurrences of a template image on the screen:

.. code-block:: python

   import time
   from je_auto_control import locate_all_image, screenshot

   time.sleep(2)

   # detect_threshold: 0.0 ~ 1.0 (1.0 = exact match)
   image_data = locate_all_image(
       screenshot(),
       detect_threshold=0.9,
       draw_image=False
   )
   print(image_data)  # [[x1, y1, x2, y2], ...]

Locate Image Center
===================

Find a template image and return its center coordinates:

.. code-block:: python

   import time
   from je_auto_control import locate_image_center, screenshot

   time.sleep(2)

   cx, cy = locate_image_center(
       screenshot(),
       detect_threshold=0.9,
       draw_image=False
   )
   print(f"Found at center: ({cx}, {cy})")

Locate and Click
================

Find a template image and automatically click on its center:

.. code-block:: python

   import time
   from je_auto_control import locate_and_click, screenshot

   time.sleep(2)

   image_data = locate_and_click(
       screenshot(),
       "mouse_left",
       detect_threshold=0.9,
       draw_image=False
   )
   print(image_data)

Parameters
==========

.. list-table::
   :header-rows: 1
   :widths: 25 15 60

   * - Parameter
     - Type
     - Description
   * - ``image``
     - str / PIL Image
     - The template image to search for (file path or PIL ``ImageGrab.grab()`` result)
   * - ``detect_threshold``
     - float
     - Detection precision from ``0.0`` to ``1.0``. ``1.0`` requires an exact match.
   * - ``draw_image``
     - bool
     - If ``True``, marks the detected area on the returned image.

Not Found versus Unusable Input
===============================

``ImageNotFoundException`` means the search ran and the template is not on
screen. An input the search cannot run on raises ``ImageSearchInputException``
instead:

* a template file that does not exist or cannot be decoded;
* a single-colour template, which would score a perfect match everywhere;
* a ``detect_threshold`` outside ``0``-``1``, NaN, or not a number;
* an image OpenCV cannot match (an unsupported colour layout or pixel type).

The two are siblings under ``AutoControlException``, not parent and child, so
a handler for "not found" never catches a typo in the template path:

.. code-block:: python

   from je_auto_control import (
       ImageNotFoundException, ImageSearchInputException, locate_image_center,
   )

   try:
       locate_image_center("save_button.png", detect_threshold=0.9)
   except ImageNotFoundException:
       print("not on screen")
   except ImageSearchInputException as error:
       print(f"fix the template or threshold: {error}")

Absence checks therefore fail on unusable input instead of passing:
``AC_assert_image`` with ``present: false`` fails ("the template could not be
used"), ``AC_wait_image_gone`` and ``ac_wait_for_image`` raise rather than
wait, and ``AC_if_image_found`` records a failure rather than running its
``else`` branch. An image trigger with such a template is disabled and logged;
observer rules, state-machine ``if_image_found`` guards and anchor locators
raise. Self-healing still falls back to its VLM step and reports why the
template failed. Device frames (``DeviceFrame.locate_image``) follow the same
split.
