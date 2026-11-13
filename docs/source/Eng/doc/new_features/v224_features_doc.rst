Adaptive GUI: Page Headers, Cards and Controls That Shrink
==========================================================

The GUI is being redesigned around one set of adaptive building blocks, so
every page looks the same and fits a small window. This page describes what
is in place: the building blocks, the window's own breakpoints, and every
page rebuilt on them.

Every page is rebuilt
---------------------

All 51 pages now group their controls on cards, put their main table or result
on a card that takes the remaining height, wrap rows of fields and buttons
instead of widening, and set side-by-side panes (list and details, input and
output) one above the other in a narrow window. Status lines and notes are
muted hints. Nothing a page does changed: its widgets, menu actions and
translations are the same.

A page scrolls only when the window is smaller than the page can shrink: each
page is given the visible area, or its minimum size where that is larger. (Qt's
default sized a page holding a wrapped label from every control's preferred
height, so pages with a table scrolled in windows they fitted.)

The window adapts to its width
------------------------------

============  ==================  =========================================
Window width  Navigation          Execution details
============  ==================  =========================================
1,200 px +    docked on the left  a column on the right
800-1,199 px  docked on the left  a drawer over the tabs, from the right
below 800 px  a rail of icons     a drawer over the tabs, from the right
============  ==================  =========================================

In the narrowest layout the rail's menu button, **Ctrl+B** or **Ctrl+K** opens
the feature list as a drawer over the tabs; choosing a feature, **Escape** or a
click on the dimmed area closes it. The rail's last button toggles the
execution details. A width must move 24 px past a boundary before the layout
changes back, so dragging the window edge near one does not make it flicker.

**View → Navigation Panel** (**Ctrl+B**) still records whether you want the
docked list. That preference is kept apart from the width: a window narrowed
below 800 px hides the dock without changing it, and widening the window brings
the dock back only if you had it shown. It is saved on close as before.

What every page gets
--------------------

* **A page header.** Each tab opens with its title and a one-line description
  of what it is for, in the active language. The description comes from the
  ``<title_key>_subtitle`` string (``tab_mobile_subtitle`` for Mobile); a page
  whose language has no such string shows only the title.
* **Cards.** Group boxes are drawn as raised cards with their title above
  them, and new pages are built from ``Card`` directly.
* **Visible check boxes and radio buttons.** Fusion outlines them with a shade
  of the window colour, which all but disappears in the dark theme; they are
  now drawn in code from the palette (accent fill, check mark, ring and dot),
  so they follow the theme without any image file.
* **Controls that shrink.** When a page is first shown it goes through a fit
  pass: drop-down lists stop sizing themselves to their longest entry (Mobile
  needed 1,464 px for one command label), form labels move above their field
  when both do not fit, and long notes wrap.

Building blocks
---------------

They live in ``je_auto_control.gui.adaptive``:

``breakpoints``
    ``classify(width, previous)`` returns ``WidthClass.COMPACT`` (below 800
    px), ``MEDIUM`` or ``EXPANDED`` (from 1,200 px). A width must move 24 px
    past a boundary before the class changes back, so resizing near one does
    not flicker. Qt-free.
``flow_layout.FlowLayout``
    A row that wraps onto the next line instead of widening its page; its
    minimum width is its widest single item.
``responsive.ResponsiveBox``
    Two or more parts side by side when there is room, stacked below a width
    you choose.
``responsive.fit_to_width``
    The fit pass described above. The workspace runs it on every page it
    shows; a control already fitted is left alone.
``surfaces``
    ``Card``, ``PageHeader``, ``EmptyState`` and ``retranslate_surfaces``. They
    carry a ``role`` property (``card``, ``pageTitle``, ``hint`` ...) that the
    theme's style sheet targets, so the look stays in ``gui/theme.py``.
``style.AdaptiveStyle``
    The Fusion proxy that paints the two indicators.
    ``prepare_application`` installs it.

Titles, section titles and hints are sized from the body text size
(``type_scale_rules``), so **View → Text Size** scales them too.

The width check
---------------

``test/unit_test/headless/test_gui_page_widths.py`` opens every registered tab
the way the window does and reads its minimum width, in average characters of
the window's label font so the same limit holds on Windows and Linux fonts. A
page may need at most 72 characters (about 460 px in 10 pt Segoe UI). Every
page fits; before the rework Script Builder alone needed 818 px.
