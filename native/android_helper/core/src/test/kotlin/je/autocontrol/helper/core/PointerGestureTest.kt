package je.autocontrol.helper.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Test

class PointerGestureTest {
    private val swipe = (0..10).map { step -> (step * 10) to (step * 20) }

    /** Records every event and refuses the ones [refuse] names, by action and zero-based occurrence. */
    private class Recorder(private val refuse: Set<Pair<PointerAction, Int>> = emptySet()) {
        val events = mutableListOf<Triple<PointerAction, Int, Int>>()

        fun inject(action: PointerAction, x: Int, y: Int): Boolean {
            val occurrence = events.count { it.first == action }
            events += Triple(action, x, y)
            return (action to occurrence) !in refuse
        }

        val actions: List<PointerAction> get() = events.map { it.first }
    }

    private fun swipeWith(recorder: Recorder, current: () -> Boolean = { true }) =
        performPointer(swipe, current, {}, recorder::inject)

    @Test
    fun anAcceptedGesturePressesMovesAndLifts() {
        val recorder = Recorder()
        assertEquals(InjectionOutcome(succeeded = true, released = true), swipeWith(recorder))
        val moves = List(10) { PointerAction.MOVE }
        assertEquals(listOf(PointerAction.DOWN) + moves + PointerAction.UP, recorder.actions)
        assertEquals(Triple(PointerAction.UP, 100, 200), recorder.events.last())
    }

    @Test
    fun oneRefusedMoveFailsTheGestureAndStillReleasesThePointer() {
        val recorder = Recorder(refuse = setOf(PointerAction.MOVE to 4))
        val outcome = swipeWith(recorder)
        assertEquals(InjectionOutcome(succeeded = false, released = true), outcome)
        // No MOVE after the refused one and no UP: the pointer is cancelled where it last got to.
        val expected = listOf(PointerAction.DOWN) + List(5) { PointerAction.MOVE } + PointerAction.CANCEL
        assertEquals(expected, recorder.actions)
        assertEquals(Triple(PointerAction.CANCEL, 40, 80), recorder.events.last())
    }

    @Test
    fun aRefusedCancelAfterARefusedMoveReportsInputStillPressed() {
        val recorder = Recorder(refuse = setOf(PointerAction.MOVE to 0, PointerAction.CANCEL to 0))
        assertEquals(InjectionOutcome(succeeded = false, released = false), swipeWith(recorder))
        assertFalse(PointerAction.UP in recorder.actions)
    }

    @Test
    fun aRefusedDownSendsNothingElse() {
        val recorder = Recorder(refuse = setOf(PointerAction.DOWN to 0))
        assertEquals(InjectionOutcome(succeeded = false, released = true), swipeWith(recorder))
        assertEquals(listOf(PointerAction.DOWN), recorder.actions)
    }

    @Test
    fun aRefusedUpIsAFailureWithInputStillPressed() {
        val recorder = Recorder(refuse = setOf(PointerAction.UP to 0))
        assertEquals(InjectionOutcome(succeeded = false, released = false), swipeWith(recorder))
    }

    @Test
    fun aFenceMidGestureCancelsInsteadOfLifting() {
        val recorder = Recorder()
        var asked = 0
        val outcome = swipeWith(recorder) { ++asked <= 3 }
        assertEquals(InjectionOutcome(succeeded = false, released = true), outcome)
        assertEquals(Triple(PointerAction.CANCEL, 30, 60), recorder.events.last())
        assertFalse(PointerAction.UP in recorder.actions)
    }

    @Test
    fun aTapIsADownAndAnUp() {
        val recorder = Recorder()
        val outcome = performPointer(listOf(5 to 6), { true }, {}, recorder::inject)
        assertEquals(InjectionOutcome(succeeded = true, released = true), outcome)
        assertEquals(listOf(PointerAction.DOWN, PointerAction.UP), recorder.actions)
        assertThrows(IllegalArgumentException::class.java) {
            performPointer(emptyList(), { true }, {}, recorder::inject)
        }
    }
}
