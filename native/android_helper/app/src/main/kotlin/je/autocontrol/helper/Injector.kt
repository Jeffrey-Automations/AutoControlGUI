package je.autocontrol.helper

import android.app.UiAutomation
import android.os.SystemClock
import android.util.Log
import android.view.InputDevice
import android.view.InputEvent
import android.view.KeyEvent
import android.view.MotionEvent
import je.autocontrol.helper.core.FenceLedger
import je.autocontrol.helper.core.InjectionOutcome
import je.autocontrol.helper.core.PointerAction
import je.autocontrol.helper.core.performPointer

private const val TAG = "JeAutoControlHelper"
private const val IDLE_WAIT_MS = 10L
private const val SWIPE_STEPS = 10

/**
 * The helper's only writer. It takes one command at a time from the ledger and, between events,
 * asks whether a fence has moved past it; when one has, it releases what it pressed and reports
 * the command as not completed.
 */
class Injector(private val automation: UiAutomation, private val ledger: FenceLedger) {
    @Volatile private var running = false
    private var thread: Thread? = null

    fun start() {
        running = true
        thread = Thread({ loop() }, "JeAutoControlInjector").also { it.isDaemon = true; it.start() }
    }

    fun stop() {
        running = false
        thread?.join(2_000)
    }

    private fun loop() {
        while (running) {
            val next = ledger.claimNext()
            if (next == null) {
                SystemClock.sleep(IDLE_WAIT_MS)
                continue
            }
            val (id, command) = next
            val outcome = try {
                perform(id, command)
            } catch (failure: RuntimeException) {
                Log.e(TAG, "injection failed", failure)
                InjectionOutcome(succeeded = false, released = false)
            }
            ledger.finish(id, outcome.succeeded, outcome.released)
        }
    }

    /** A throwing injection is a refused one, so the gesture still goes on to release what it pressed. */
    private fun inject(event: InputEvent): Boolean = try {
        automation.injectInputEvent(event, true)
    } catch (failure: RuntimeException) {
        Log.e(TAG, "input event refused", failure)
        false
    }

    private fun perform(id: String, command: Map<String, Any?>): InjectionOutcome = when (command["kind"]) {
        "tap" -> pointer(id, listOf(command.int("x") to command.int("y")), 0)
        "swipe" -> pointer(id, path(command), command.int("duration_ms").toLong() / SWIPE_STEPS)
        "key" -> key(id, command.int("keycode"))
        else -> InjectionOutcome(succeeded = false, released = true)
    }

    private fun path(command: Map<String, Any?>): List<Pair<Int, Int>> {
        val (x, y, toX, toY) = listOf(command.int("x"), command.int("y"), command.int("to_x"), command.int("to_y"))
        return (0..SWIPE_STEPS).map { step ->
            (x + (toX - x) * step / SWIPE_STEPS) to (y + (toY - y) * step / SWIPE_STEPS)
        }
    }

    /** The gesture's sequencing (first failure wins, input always released) lives in [performPointer]. */
    private fun pointer(id: String, points: List<Pair<Int, Int>>, stepMs: Long): InjectionOutcome {
        val down = SystemClock.uptimeMillis()
        return performPointer(points, { ledger.stillCurrent(id) }, { SystemClock.sleep(stepMs) }) { action, x, y ->
            val time = if (action == PointerAction.DOWN) down else SystemClock.uptimeMillis()
            inject(motion(down, time, motionAction(action), x, y))
        }
    }

    private fun motionAction(action: PointerAction): Int = when (action) {
        PointerAction.DOWN -> MotionEvent.ACTION_DOWN
        PointerAction.MOVE -> MotionEvent.ACTION_MOVE
        PointerAction.UP -> MotionEvent.ACTION_UP
        PointerAction.CANCEL -> MotionEvent.ACTION_CANCEL
    }

    private fun key(id: String, keycode: Int): InjectionOutcome {
        val now = SystemClock.uptimeMillis()
        if (!inject(KeyEvent(now, now, KeyEvent.ACTION_DOWN, keycode, 0))) {
            return InjectionOutcome(succeeded = false, released = true)
        }
        val current = ledger.stillCurrent(id)
        val released = inject(KeyEvent(now, SystemClock.uptimeMillis(), KeyEvent.ACTION_UP, keycode, 0))
        return InjectionOutcome(succeeded = current && released, released = released)
    }

    private fun motion(down: Long, time: Long, action: Int, x: Int, y: Int): MotionEvent =
        MotionEvent.obtain(down, time, action, x.toFloat(), y.toFloat(), 0).also {
            it.source = InputDevice.SOURCE_TOUCHSCREEN
        }
}

private fun Map<String, Any?>.int(key: String): Int = (this[key] as Number).toInt()
