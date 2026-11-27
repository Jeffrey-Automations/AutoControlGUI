package je.autocontrol.helper.core

import java.io.Closeable
import java.io.IOException
import java.io.Reader
import java.io.Writer

/** The longest request line, in characters; a longer one ends its connection. */
const val MAX_LINE = 64 * 1024

/**
 * Accept clients one at a time until [accept] throws, serving each with [serve] and closing it after.
 *
 * Each client is its own I/O boundary: a peer that hangs up while its reply is written, or a reset
 * socket, ends that client only. The failure goes to [onClientFailure] and the next client is
 * accepted, so the ledger and the injector outlive any one connection. A failure of [accept] itself,
 * or anything that is not an [IOException], still ends the loop.
 */
fun <C : Closeable> acceptClients(accept: () -> C, serve: (C) -> Unit, onClientFailure: (IOException) -> Unit) {
    while (true) {
        val client = accept()
        try {
            client.use(serve)
        } catch (failure: IOException) {
            onClientFailure(failure)
        }
    }
}

/** Answer each request line from [reader] with one line from [respond], until end of input or an over-long line. */
fun serveLines(reader: Reader, writer: Writer, respond: (String) -> String) {
    while (true) {
        val line = readBoundedLine(reader) ?: return
        writer.write(respond(line))
        writer.write("\n")
        writer.flush()
    }
}

/** One line without its newline; null at end of input, or once a line passes [MAX_LINE] characters. */
fun readBoundedLine(reader: Reader): String? {
    val line = StringBuilder()
    while (true) {
        val next = reader.read()
        if (next < 0) return if (line.isEmpty()) null else line.toString()
        if (next == '\n'.code) return line.toString()
        if (line.length >= MAX_LINE) return null
        line.append(next.toChar())
    }
}
