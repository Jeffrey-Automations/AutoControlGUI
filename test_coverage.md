# 測試覆蓋度：AutoControlGUI

測量日期：2026-10-28。數字來自這台 Windows 機器上的一次實測，不是估計，也不是只數檔案。

| 項目 | 內容 |
|---|---|
| 直譯器 | 3.14.4 |
| 直譯器說明 | 專案 .venv |
| 工具 | coverage 7.15.0，`coverage run --branch` |
| 測量範圍 | `je_auto_control`、`je_auto_control_pytest` |
| 測試路徑 | `test/unit_test/headless test/unit_test/flow_control` |
| 命令 | `python -m coverage run --branch --source=je_auto_control,je_auto_control_pytest -m pytest test/unit_test/headless test/unit_test/flow_control` |
| 敘述覆蓋 | 89.79%（61641 / 68651） |
| 分支覆蓋 | 81.66%（14069 / 17228） |
| 測試結果 | 13361 passed, 70 skipped, 1 warning in 959.37s (0:15:59) |
| 耗時 | 969.1 秒 |

敘述覆蓋是執行到的敘述數除以全部敘述數。分支覆蓋是執行到的分支數除以全部分支數。兩者分開算，沒有把分支混進敘述百分比。

## 這次怎麼量

測試路徑沿用 pyproject 的 `test/unit_test/headless` 與 `test/unit_test/flow_control`。`test/unit_test` 裡的 `*_test.py` 會驅動真實滑鼠與鍵盤，沒有納入。測量用 `coverage run -m pytest`，避免 pytest 外掛在 coverage 啟動前先匯入整個套件。CI 的 `fail_under = 81` 把分支算進總分，而且設定排除 `gui` 與 `language_wrapper`；本檔的兩個百分比是全套件的敘述覆蓋與分支覆蓋，演算法不同。

## 覆蓋較低的檔案

只列這次測量裡敘述覆蓋最低的檔案，最多 12 個。

| 檔案 | 敘述覆蓋 | 已覆蓋 / 敘述 |
|---|---:|---:|
| `je_auto_control/linux_with_x11/core/utils/x11_linux_vk.py` | 0.0% | 0 / 190 |
| `je_auto_control/linux_with_x11/uinput/_device.py` | 0.0% | 0 / 123 |
| `je_auto_control/osx/listener/osx_listener.py` | 0.0% | 0 / 114 |
| `je_auto_control/linux_with_x11/listener/x11_linux_listener.py` | 0.0% | 0 / 82 |
| `je_auto_control/osx/screen/osx_screen.py` | 0.0% | 0 / 52 |
| `je_auto_control/linux_with_x11/uinput/mouse.py` | 0.0% | 0 / 48 |
| `je_auto_control/utils/xml/xml_file/xml_file.py` | 0.0% | 0 / 44 |
| `je_auto_control/utils/rest_api/__main__.py` | 0.0% | 0 / 37 |
| `je_auto_control/wrapper/_platform_linux.py` | 0.0% | 0 / 36 |
| `je_auto_control/linux_with_x11/keyboard/x11_linux_keyboard_control.py` | 0.0% | 0 / 34 |
| `je_auto_control/osx/keyboard/osx_keyboard.py` | 0.0% | 0 / 33 |
| `je_auto_control/linux_with_x11/record/x11_linux_record.py` | 0.0% | 0 / 29 |
