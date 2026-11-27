#define _GNU_SOURCE
/* Journal recovery against an I/O double for the slot reads: an interrupted read is
 * retried, a read that fails outright refuses recovery and leaves the slot untouched, and
 * a genuinely short record is still passed over in favour of the older valid one. The
 * double replaces pread only inside guardian_journal.c, which is compiled into this file. */
#include <errno.h>
#include <stdint.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

typedef enum { IO_PASS, IO_EINTR_ONCE, IO_FAIL, IO_PARTIAL_ONCE } io_mode;
static io_mode mode = IO_PASS;
static ino_t target;  /* Only reads of this inode are disturbed. */
static unsigned disturbed;

static ssize_t double_pread(int number, void *buffer, size_t size, off_t offset) {
    struct stat status;
    if (mode != IO_PASS && fstat(number, &status) == 0 && status.st_ino == target) {
        if (mode == IO_EINTR_ONCE) { mode = IO_PASS; ++disturbed; errno = EINTR; return -1; }
        if (mode == IO_FAIL) { ++disturbed; errno = EIO; return -1; }
        if (mode == IO_PARTIAL_ONCE && size > 1) { mode = IO_PASS; ++disturbed; size /= 2; }
    }
    return pread(number, buffer, size, offset);
}

#define GJ_PREAD double_pread
#include "guardian_journal.c"

#include <stdio.h>
#include <stdlib.h>

static unsigned checks;
#define CHECK(expression) do { if (!(expression)) { \
    fprintf(stderr, "failed line %d: %s\n", __LINE__, #expression); abort(); } ++checks; } while (0)

static char root[64];
static const uint8_t install[GJ_INSTALLATION_BYTES] = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16};
static const char *newer_name;

static void path_of(char *out, size_t size, const char *name) { snprintf(out, size, "%s/%s", root, name); }

static gj_error reopen(gj_journal *journal) { return gj_open(journal, root, getuid(), install); }

/* An older CLEAN record (sequence 4, counter 1) and a newer PLANNED one (sequence 5,
 * counter 2); returns the newer slot's inode, the one the double disturbs. */
static ino_t two_slots(void) {
    char path[128];
    const char *names[] = {"journal.a", "journal.b", "lock"};
    for (size_t i = 0; i < 3; ++i) { path_of(path, sizeof(path), names[i]); unlink(path); }
    mode = IO_PASS;
    gj_journal journal;
    CHECK(reopen(&journal) == GJ_ERROR_NONE && gj_initialize(&journal, install, 1) == GJ_ERROR_NONE);
    CHECK(gj_plan(&journal) == GJ_ERROR_NONE && gj_mark(&journal, GJ_RECOVERING) == GJ_ERROR_NONE);
    CHECK(gj_mark(&journal, GJ_CLEAN) == GJ_ERROR_NONE && gj_plan(&journal) == GJ_ERROR_NONE);
    CHECK(journal.current.sequence == 5 && journal.current.counter == 2);
    newer_name = journal.slot ? "journal.b" : "journal.a";
    gj_close(&journal);
    struct stat status;
    path_of(path, sizeof(path), newer_name);
    CHECK(stat(path, &status) == 0 && status.st_size == (off_t)sizeof(gj_record));
    return status.st_ino;
}

/* An interrupted read is retried, so the newer record still wins. */
static void case_interrupted(void) {
    target = two_slots();
    disturbed = 0;
    mode = IO_EINTR_ONCE;
    gj_journal journal;
    CHECK(reopen(&journal) == GJ_ERROR_NONE && disturbed == 1);
    CHECK(journal.current.sequence == 5 && journal.current.counter == 2 && journal.current.phase == GJ_PLANNED);
    gj_close(&journal);
}

/* A partial transfer is continued rather than taken for a torn record. */
static void case_partial_transfer(void) {
    target = two_slots();
    disturbed = 0;
    mode = IO_PARTIAL_ONCE;
    gj_journal journal;
    CHECK(reopen(&journal) == GJ_ERROR_NONE && disturbed == 1);
    CHECK(journal.current.sequence == 5 && journal.current.counter == 2);
    gj_close(&journal);
}

/* A slot that cannot be read refuses recovery: the older record is not adopted, nothing
 * can commit, and the unread slot keeps its full record for the next attempt. */
static void case_permanent_error(void) {
    target = two_slots();
    disturbed = 0;
    mode = IO_FAIL;
    gj_journal journal;
    CHECK(reopen(&journal) == GJ_ERROR_IO && disturbed >= 1);
    CHECK(journal.directory < 0 && journal.lock < 0);
    CHECK(gj_plan(&journal) == GJ_ERROR_DIRECTORY && gj_mark(&journal, GJ_RECOVERING) == GJ_ERROR_DIRECTORY);
    mode = IO_PASS;
    char path[128];
    struct stat status;
    path_of(path, sizeof(path), newer_name);
    CHECK(stat(path, &status) == 0 && status.st_size == (off_t)sizeof(gj_record));
    CHECK(reopen(&journal) == GJ_ERROR_NONE && journal.current.sequence == 5 && journal.current.counter == 2);
    gj_close(&journal);
}

/* A genuinely short record is still a torn write: the older record is recovered. */
static void case_short_record(void) {
    two_slots();
    char path[128];
    path_of(path, sizeof(path), newer_name);
    CHECK(truncate(path, sizeof(gj_record) / 2) == 0);
    gj_journal journal;
    CHECK(reopen(&journal) == GJ_ERROR_NONE && journal.current.sequence == 4 && journal.current.counter == 1);
    gj_close(&journal);
}

int main(void) {
    snprintf(root, sizeof(root), "/tmp/guardian-journal-io-XXXXXX");
    CHECK(mkdtemp(root) != NULL);
    CHECK(chmod(root, 0700) == 0);
    case_interrupted();
    case_partial_transfer();
    case_permanent_error();
    case_short_record();
    char path[128];
    const char *names[] = {"journal.a", "journal.b", "lock"};
    for (size_t i = 0; i < 3; ++i) { path_of(path, sizeof(path), names[i]); unlink(path); }
    CHECK(rmdir(root) == 0);
    printf("{\"checks\": %u, \"evidence\": \"journal reads through an I/O double\"}\n", checks);
    return 0;
}
