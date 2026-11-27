package je.autocontrol.helper.core

/** The pointer events one gesture is made of. */
enum class PointerAction { DOWN, MOVE, UP, CANCEL }

/** How one injection ended; [released] is false when a pressed pointer or key may still be down. */
data class InjectionOutcome(val succeeded: Boolean, val released: Boolean)

/** Injects one pointer event at (x, y) and answers whether the platform accepted it. */
typealias PointerInjector = (action: PointerAction, x: Int, y: Int) -> Boolean

/**
 * Press at the first point, move through the rest and lift at the last, all through [inject].
 *
 * [stillCurrent] is asked before every event after DOWN, and [pause] runs before every MOVE. The
 * first failure decides the outcome: once a fence overtakes the command or any MOVE is refused, no
 * further MOVE or UP is sent, the pointer is cancelled at the last point it reached, and the gesture
 * is reported as failed, so a refused MOVE can never be followed by an UP that makes it look complete.
 * Only an UP the platform accepted makes the gesture succeed.
 */
fun performPointer(
    points: List<Pair<Int, Int>>,
    stillCurrent: () -> Boolean,
    pause: () -> Unit,
    inject: PointerInjector,
): InjectionOutcome {
    require(points.isNotEmpty()) { "a pointer gesture needs at least one point" }
    val (startX, startY) = points.first()
    // A refused DOWN pressed nothing, so there is nothing to release.
    if (!inject(PointerAction.DOWN, startX, startY)) return InjectionOutcome(succeeded = false, released = true)
    var last = points.first()
    for (point in points.drop(1)) {
        if (!stillCurrent()) return cancel(inject, last)
        pause()
        if (!inject(PointerAction.MOVE, point.first, point.second)) return cancel(inject, last)
        last = point
    }
    if (!stillCurrent()) return cancel(inject, last)
    val released = inject(PointerAction.UP, last.first, last.second)
    return InjectionOutcome(succeeded = released, released = released)
}

private fun cancel(inject: PointerInjector, at: Pair<Int, Int>): InjectionOutcome =
    InjectionOutcome(succeeded = false, released = inject(PointerAction.CANCEL, at.first, at.second))
