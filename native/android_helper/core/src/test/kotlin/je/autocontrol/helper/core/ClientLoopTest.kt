package je.autocontrol.helper.core

import java.io.Closeable
import java.io.IOException
import java.io.StringReader
import java.io.StringWriter
import java.io.Writer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class ClientLoopTest {
    private val boot = "6f1cfc87-e569-d6ae-2d37-d14af9cf3f04"
    private val epoch = "a".repeat(32)
    private val request = "1".padStart(32, '0')
    private val tap = mapOf<String, Any?>("kind" to "tap", "x" to 10, "y" to 20)

    /** A connection whose peer may already have hung up: then every write fails as a closed socket does. */
    private class FakeClient(input: String, hungUp: Boolean = false) : Closeable {
        val reader = StringReader(input)
        val output = StringWriter()
        val writer: Writer = if (!hungUp) output else object : Writer() {
            override fun write(buffer: CharArray, offset: Int, length: Int) {
                throw IOException("broken pipe")
            }
            override fun flush() = Unit
            override fun close() = Unit
        }
        var closed = false

        override fun close() {
            closed = true
        }
    }

    /** Serves [clients] in order, then ends the loop the way a closed server socket would. */
    private fun serveAll(clients: List<FakeClient>, respond: (String) -> String): List<IOException> {
        val pending = ArrayDeque(clients)
        val failures = mutableListOf<IOException>()
        val end = IllegalStateException("server socket closed")
        val thrown = assertThrows(IllegalStateException::class.java) {
            acceptClients<FakeClient>({ pending.removeFirstOrNull() ?: throw end }, { client ->
                serveLines(client.reader, client.writer, respond)
            }) { failures += it }
        }
        assertSame(end, thrown)
        return failures
    }

    @Test
    fun aClientThatHangsUpBeforeItsReplyDoesNotEndTheLoop() {
        val ledger = FenceLedger(boot, epoch)
        assertTrue(ledger.begin(request, epoch, tap).accepted)
        val protocol = ProtocolHandler(ledger, boot, epoch)
        val settle = { id: String ->
            protocol.handle(mapOf("op" to "settle", "id" to id)).getValue("status").toString()
        }
        val early = FakeClient("$request\n", hungUp = true)
        val next = FakeClient("$request\n")
        val failures = serveAll(listOf(early, next), settle)
        assertEquals(listOf("broken pipe"), failures.map { it.message })
        // The next client is served by the same ledger and sees the command the first one left.
        assertEquals("queued\n", next.output.toString())
        assertTrue(early.closed && next.closed)
    }

    @Test
    fun aFailureThatIsNotAClientIoErrorStillEndsTheLoop() {
        val broken = IllegalStateException("ledger invariant")
        val thrown = assertThrows(IllegalStateException::class.java) {
            acceptClients<FakeClient>({ FakeClient("x\n") }, { throw broken }) { }
        }
        assertSame(broken, thrown)
    }

    @Test
    fun eachLineGetsOneReplyAndAnOverLongLineEndsTheConnection() {
        val client = FakeClient("one\ntwo")
        serveLines(client.reader, client.writer) { it.uppercase() }
        assertEquals("ONE\nTWO\n", client.output.toString())
        val long = FakeClient("x".repeat(MAX_LINE + 1) + "\nlater\n")
        serveLines(long.reader, long.writer) { "reply" }
        assertEquals("", long.output.toString())
        assertNull(readBoundedLine(StringReader("")))
    }
}
