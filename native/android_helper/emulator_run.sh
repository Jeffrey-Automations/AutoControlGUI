#!/bin/sh
# Stage 4 on a CI emulator: install the debug APK, start the helper instrumentation in the
# background and drive it through the host provider stack. Emulator evidence only.
set -eu
apk="$1"
adb wait-for-device
adb install -r "$apk"
nohup adb shell am instrument -w je.autocontrol.helper/.HelperInstrumentation > instrument.log 2>&1 &
status=0
python native/android_helper/emulator_check.py || status=$?
echo "--- instrumentation log"
cat instrument.log || true
exit "$status"
