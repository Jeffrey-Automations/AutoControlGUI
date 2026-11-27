package je.autocontrol.helper

import android.net.LocalServerSocket
import android.net.LocalSocket
import android.util.Log
import java.io.BufferedReader
import java.io.InputStreamReader
import java.io.OutputStreamWriter
import je.autocontrol.helper.core.ProtocolHandler
import je.autocontrol.helper.core.acceptClients
import je.autocontrol.helper.core.serveLines
import org.json.JSONObject

private const val TAG = "JeAutoControlHelper"
const val SOCKET_NAME = "je_auto_control_helper"
private const val SHELL_UID = 2000
private const val ROOT_UID = 0

/**
 * Serve protocol version 1 on the abstract socket [SOCKET_NAME], one client at a time.
 *
 * An abstract socket has no file permissions, so any app could connect: only a peer running as
 * shell (what `adb forward` connections arrive as) or root is served; anything else is closed
 * before a line is read. A line over 64 KiB ends that connection. A client's own I/O failure, such
 * as hanging up before its reply is written, ends that connection only: the next client is served
 * by the same ledger, and the injector keeps running.
 */
class HelperServer(private val protocol: ProtocolHandler) {

    fun serve() {
        // Closed explicitly: LocalServerSocket only implements Closeable on newer API levels.
        val server = LocalServerSocket(SOCKET_NAME)
        try {
            acceptClients(server::accept, this::serveClient) { failure ->
                Log.w(TAG, "a client connection ended with an I/O error", failure)
            }
        } finally {
            server.close()
        }
    }

    private fun serveClient(client: LocalSocket) {
        val uid = client.peerCredentials.uid
        if (uid != SHELL_UID && uid != ROOT_UID) {
            Log.w(TAG, "refused a peer running as uid $uid")
            return
        }
        val reader = BufferedReader(InputStreamReader(client.inputStream, Charsets.UTF_8))
        val writer = OutputStreamWriter(client.outputStream, Charsets.UTF_8)
        serveLines(reader, writer, this::respond)
    }

    private fun respond(line: String): String {
        val reply = try {
            protocol.handle(decodeObject(JSONObject(line)))
        } catch (failure: org.json.JSONException) {
            mapOf("error" to "invalid_json")
        }
        return encodeObject(reply).toString()
    }
}
