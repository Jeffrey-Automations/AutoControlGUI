======
安裝
======

從 PyPI 安裝
============

.. code-block:: bash

   pip install je_auto_control

系統需求
========

* Python 3.11 以上
* pip 19.3 以上

安裝 GUI 支援
=============

.. code-block:: bash

   pip install je_auto_control[gui]

GUI（``start_autocontrol_gui()``）開著時，自動回收會關閉，改由 GUI 執行緒上的計時器回收循環垃圾，
程式結束時再打開。這樣 worker 執行緒不會碰到 PySide6 6.12 會延後刪除的 Qt 物件（那條路徑在 Windows 上曾讓程序 abort）。
只 import ``je_auto_control`` 不會改變任何事。

Linux 前置套件
==============

.. code-block:: bash

   sudo apt-get install cmake libssl-dev

樹莓派
======

.. code-block:: bash

   sudo apt-get install python3
   pip3 install je_auto_control
   sudo apt-get install libcblas-dev libhdf5-dev libhdf5-serial-dev
   sudo apt-get install libatlas-base-dev libjasper-dev
   sudo apt-get install libqtgui4 libqt4-test
   pip3 install -U pillow numpy

開發環境
========

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - 平台
     - 測試版本
   * - Windows
     - Windows 11
   * - macOS
     - macOS Big Sur (11)
   * - Linux
     - Ubuntu 20.04
   * - Raspberry Pi
     - 3B / 4B
