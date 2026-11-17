/* Owned schema-one memory fixture. No desktop APIs or external process access. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <bcrypt.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <io.h>
#include <fcntl.h>

#define FRAME_BYTES 1024
#define OPERATIONS 128
#define COMMAND 1u
#define OPERATION 2u
#define NONCE 4u
#define REVISION 8u
#define DOCUMENT 16u
#define STATUS 32u
#define CHANGE_FIELDS 63u

typedef struct {
    uint32_t document;
    char status[12];
} Payload;

typedef struct {
    char magic[8];
    unsigned char challenge[16];
    uint64_t payload;
    uint64_t sequence;
} Header;

typedef struct {
    char id[33], operation[16], command[16];
    char operation_id[129], nonce[33], status[12];
    uint64_t revision, document;
    unsigned fields;
} Request;

typedef struct {
    Request request;
    uint64_t sequence;
    const char *error;
} Receipt;

static Payload payload = {17, "ready"};
static __declspec(align(8)) volatile LONG64 generation = 0;
static Header header;
static char launch_nonce[33];
static Receipt receipts[OPERATIONS];
static size_t receipt_count;

typedef char payload_size_check[sizeof(Payload) == 16 ? 1 : -1];
typedef char header_size_check[sizeof(Header) == 40 ? 1 : -1];

static void space(const char **p) {
    while (**p == ' ' || **p == '\t' || **p == '\r' || **p == '\n') ++*p;
}

static int take(const char **p, char value) {
    space(p);
    if (**p != value) return 0;
    ++*p;
    return 1;
}

static int text(const char **p, char *out, size_t capacity) {
    size_t used = 0;
    if (!take(p, '"')) return 0;
    while (**p && **p != '"') {
        unsigned char c = (unsigned char)**p;
        if (c < 32 || c >= 127 || c == '\\' || used + 1 >= capacity) return 0;
        out[used++] = (char)c;
        ++*p;
    }
    out[used] = 0;
    return take(p, '"');
}

static int number(const char **p, uint64_t *out) {
    uint64_t value = 0;
    space(p);
    if (**p < '0' || **p > '9') return 0;
    if (**p == '0' && (*p)[1] >= '0' && (*p)[1] <= '9') return 0;
    while (**p >= '0' && **p <= '9') {
        unsigned digit = (unsigned)(**p - '0');
        if (value > (UINT64_MAX - digit) / 10) return 0;
        value = value * 10 + digit;
        ++*p;
    }
    *out = value;
    return 1;
}

static int mark(unsigned *fields, unsigned bit) {
    if (*fields & bit) return 0;
    *fields |= bit;
    return 1;
}

static int control_field(const char **p, Request *r, const char *key) {
    static const struct { const char *name; unsigned bit; size_t offset, capacity; } fields[] = {
        {"command", COMMAND, offsetof(Request, command), sizeof(r->command)},
        {"operation_id", OPERATION, offsetof(Request, operation_id), sizeof(r->operation_id)},
        {"launch_nonce", NONCE, offsetof(Request, nonce), sizeof(r->nonce)},
        {"expected_sequence", REVISION, offsetof(Request, revision), 0},
        {"document_id", DOCUMENT, offsetof(Request, document), 0},
        {"job_status", STATUS, offsetof(Request, status), sizeof(r->status)}
    };
    size_t i;
    for (i = 0; i < sizeof(fields) / sizeof(fields[0]); ++i) {
        char *destination;
        if (strcmp(key, fields[i].name)) continue;
        if (!mark(&r->fields, fields[i].bit)) return 0;
        destination = (char *)r + fields[i].offset;
        if (fields[i].capacity) return text(p, destination, fields[i].capacity);
        return number(p, (uint64_t *)destination);
    }
    return 0;
}

static int control_object(const char **p, Request *r) {
    char key[32];
    if (!take(p, '{')) return 0;
    space(p);
    if (**p == '}') { ++*p; return 1; }
    for (;;) {
        if (!text(p, key, sizeof(key)) || !take(p, ':') || !control_field(p, r, key)) return 0;
        space(p);
        if (**p == '}') { ++*p; return 1; }
        if (!take(p, ',')) return 0;
    }
}

static int hex_digit(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    return -1;
}

static int hex32(const char *value) {
    size_t i;
    if (strlen(value) != 32) return 0;
    for (i = 0; i < 32; ++i) if (hex_digit(value[i]) < 0) return 0;
    return 1;
}

static int root_field(const char **p, Request *r, unsigned *fields, const char *key) {
    if (!strcmp(key, "id"))
        return mark(fields, 1) && text(p, r->id, sizeof(r->id));
    if (!strcmp(key, "operation"))
        return mark(fields, 2) && text(p, r->operation, sizeof(r->operation));
    if (!strcmp(key, "payload")) return mark(fields, 4) && control_object(p, r);
    return 0;
}

static int parse(const char *p, Request *r) {
    char key[32];
    unsigned fields = 0;
    memset(r, 0, sizeof(*r));
    if (!take(&p, '{')) return 0;
    for (;;) {
        if (!text(&p, key, sizeof(key)) || !take(&p, ':') || !root_field(&p, r, &fields, key)) return 0;
        space(&p);
        if (*p == '}') { ++p; break; }
        if (!take(&p, ',')) return 0;
    }
    space(&p);
    return fields == 7 && !*p && hex32(r->id);
}

static int identifier_character(unsigned char c) {
    if (c >= 'a' && c <= 'z') return 1;
    if (c >= 'A' && c <= 'Z') return 1;
    if (c >= '0' && c <= '9') return 1;
    return strchr("_.:-", c) != NULL;
}

static int operation_id(const char *value) {
    const unsigned char *p = (const unsigned char *)value;
    if (!*p) return 0;
    for (; *p; ++p) if (!identifier_character(*p)) return 0;
    return 1;
}

static void error(const char *code) {
    printf("{\"kind\":\"error\",\"code\":\"%s\"}", code);
}

static void snapshot(void) {
    printf("{\"kind\":\"snapshot\",\"document_id\":%lu,\"job_status\":\"%s\",\"sequence\":%llu}",
           (unsigned long)payload.document, payload.status, (unsigned long long)generation);
}

static void confirmation(const Receipt *receipt) {
    const Request *r = &receipt->request;
    if (receipt->error) { error(receipt->error); return; }
    printf("{\"kind\":\"receipt\",\"operation_id\":\"%s\",\"launch_nonce\":\"%s\","
           "\"comparison\":\"atomic\",\"document_id\":%llu,\"job_status\":\"%s\",\"sequence\":%llu}",
           r->operation_id, launch_nonce, (unsigned long long)r->document, r->status,
           (unsigned long long)receipt->sequence);
}

static int same_change(const Request *a, const Request *b) {
    return a->revision == b->revision && a->document == b->document && !strcmp(a->status, b->status);
}

static const char *change_error(const Request *r) {
    if (r->fields != CHANGE_FIELDS || !operation_id(r->operation_id) || (r->revision & 1)) {
        return "invalid_request";
    }
    if (strcmp(r->nonce, launch_nonce)) return "target_changed";
    if (r->document > UINT32_MAX ||
        (strcmp(r->status, "ready") && strcmp(r->status, "busy") && strcmp(r->status, "done"))) {
        return "invalid_state";
    }
    return NULL;
}

static void compare_set(const Request *r) {
    size_t i;
    Receipt *receipt;
    uint64_t before = (uint64_t)generation;
    const char *invalid = change_error(r);
    if (invalid) { error(invalid); return; }
    for (i = 0; i < receipt_count; ++i) {
        if (!strcmp(receipts[i].request.operation_id, r->operation_id)) {
            if (same_change(&receipts[i].request, r)) confirmation(&receipts[i]);
            else error("operation_conflict");
            return;
        }
    }
    if (receipt_count == OPERATIONS) { error("operation_limit"); return; }
    receipt = &receipts[receipt_count++];
    receipt->request = *r;
    if (r->revision != before) receipt->error = "state_changed";
    else if (before >= UINT64_MAX - 1) receipt->error = "sequence_exhausted";
    else {
        InterlockedExchange64(&generation, (LONG64)(before + 1));
        payload.document = (uint32_t)r->document;
        memset(payload.status, 0, sizeof(payload.status));
        memcpy(payload.status, r->status, strlen(r->status));
        InterlockedExchange64(&generation, (LONG64)(before + 2));
        receipt->sequence = before + 2;
    }
    confirmation(receipt);
}

static void bootstrap(void) {
    printf("{\"kind\":\"bootstrap\",\"protocol_version\":1,\"schema_version\":1,"
           "\"identity\":\"self_reported\",\"pid\":%lu,\"pointer_bits\":64,"
           "\"header_address\":%llu,\"header_size\":40,\"payload_address\":%llu,"
           "\"payload_size\":16,\"sequence_address\":%llu,\"sequence_size\":8,\"launch_nonce\":\"%s\"}",
           GetCurrentProcessId(), (unsigned long long)(uintptr_t)&header,
           (unsigned long long)(uintptr_t)&payload, (unsigned long long)(uintptr_t)&generation, launch_nonce);
}

static int initialize(int argc, char **argv) {
    unsigned char nonce[16];
    static const char hex[] = "0123456789abcdef";
    size_t i;
    unsigned nonzero = 0;
    if (argc != 4 || strcmp(argv[1], "--rpc") || strcmp(argv[2], "--challenge") || !hex32(argv[3])) return 0;
    memcpy(header.magic, "JEPMFIX1", 8);
    for (i = 0; i < 16; ++i) {
        header.challenge[i] = (unsigned char)(hex_digit(argv[3][i * 2]) * 16 + hex_digit(argv[3][i * 2 + 1]));
        nonzero |= header.challenge[i];
    }
    if (!nonzero || BCryptGenRandom(NULL, nonce, sizeof(nonce), BCRYPT_USE_SYSTEM_PREFERRED_RNG) != 0) return 0;
    for (i = 0; i < 16; ++i) {
        launch_nonce[i * 2] = hex[nonce[i] >> 4];
        launch_nonce[i * 2 + 1] = hex[nonce[i] & 15];
    }
    header.payload = (uint64_t)(uintptr_t)&payload;
    header.sequence = (uint64_t)(uintptr_t)&generation;
    return 1;
}

static void dispatch(const Request *request) {
    if (!strcmp(request->operation, "bootstrap") && request->fields == 0) { bootstrap(); return; }
    if (strcmp(request->operation, "control")) { error("invalid_request"); return; }
    if (!strcmp(request->command, "snapshot") && request->fields == COMMAND) snapshot();
    else if (!strcmp(request->command, "compare_set")) compare_set(request);
    else error("invalid_request");
}

static int serve(void) {
    char frame[FRAME_BYTES + 2];
    Request request;
    while (fgets(frame, sizeof(frame), stdin)) {
        size_t length = strlen(frame);
        if (!length || length > FRAME_BYTES || frame[length - 1] != '\n' || !parse(frame, &request)) return 2;
        printf("{\"id\":\"%s\",\"result\":", request.id);
        dispatch(&request);
        puts("}");
        if (ferror(stdout)) return 2;
    }
    return ferror(stdin) ? 2 : 0;
}

int main(int argc, char **argv) {
    if (sizeof(void *) != 8 || !initialize(argc, argv)) return 2;
    if (_setmode(_fileno(stdin), _O_BINARY) == -1 || _setmode(_fileno(stdout), _O_BINARY) == -1) return 2;
    setvbuf(stdout, NULL, _IONBF, 0);
    return serve();
}
