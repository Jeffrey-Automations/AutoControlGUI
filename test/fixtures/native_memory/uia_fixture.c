/* Owned hidden window fixture. Build-only until native acceptance is resumed. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <io.h>
#include <fcntl.h>

typedef struct {
    HANDLE ready;
    HANDLE stop;
    HWND window;
} WindowOwner;

typedef struct {
    int id;
    const wchar_t *text;
    DWORD style;
} Field;

static const Field fields[] = {
    {1001, L"17", 0},
    {1002, L"ready", 0},
    {1003, L"", 0},
    {1004, L"disabled", WS_DISABLED},
    {1005, L"fixture-only-secret", ES_PASSWORD},
    {1006, L"duplicate-a", 0},
    {1006, L"duplicate-b", 0}
};

static LRESULT CALLBACK window_proc(HWND window, UINT message, WPARAM word, LPARAM value) {
    if (message == WM_DESTROY) PostQuitMessage(0);
    return DefWindowProcW(window, message, word, value);
}

static int challenge_valid(int argc, char **argv) {
    size_t i;
    if (argc != 3 || strcmp(argv[1], "--challenge") || strlen(argv[2]) != 32) return 0;
    for (i = 0; i < 32; ++i) {
        char value = argv[2][i];
        if (!((value >= '0' && value <= '9') || (value >= 'a' && value <= 'f'))) return 0;
    }
    return 1;
}

static HWND create_window(void) {
    HINSTANCE instance = GetModuleHandleW(NULL);
    WNDCLASSW definition = {0};
    HWND window;
    size_t i;
    definition.lpfnWndProc = window_proc;
    definition.hInstance = instance;
    definition.lpszClassName = L"AutoControlOwnedUiaFixture";
    if (!RegisterClassW(&definition)) return NULL;
    window = CreateWindowExW(WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW,
        definition.lpszClassName, L"Owned UI observation fixture", WS_OVERLAPPED,
        -32000, -32000, 320, 320, NULL, NULL, instance, NULL);
    if (!window) return NULL;
    for (i = 0; i < sizeof(fields) / sizeof(fields[0]); ++i) {
        HWND child = CreateWindowExW(0, L"EDIT", fields[i].text,
            WS_CHILD | WS_VISIBLE | ES_READONLY | fields[i].style,
            8, 8 + (int)i * 32, 240, 24, window,
            (HMENU)(INT_PTR)fields[i].id, instance, NULL);
        if (!child) {
            DestroyWindow(window);
            return NULL;
        }
    }
    return window;
}

static DWORD pump(WindowOwner *owner) {
    for (;;) {
        DWORD wait = MsgWaitForMultipleObjects(1, &owner->stop, FALSE, INFINITE, QS_ALLINPUT);
        MSG message;
        if (wait == WAIT_OBJECT_0) return 0;
        if (wait != WAIT_OBJECT_0 + 1) return 3;
        while (PeekMessageW(&message, NULL, 0, 0, PM_REMOVE)) {
            if (message.message == WM_QUIT) return 3;
            TranslateMessage(&message);
            DispatchMessageW(&message);
            if (WaitForSingleObject(owner->stop, 0) == WAIT_OBJECT_0) return 0;
        }
    }
}

static DWORD WINAPI window_thread(void *argument) {
    WindowOwner *owner = (WindowOwner *)argument;
    DWORD result = 3;
    owner->window = create_window();
    if (SetEvent(owner->ready) && owner->window) result = pump(owner);
    if (owner->window && IsWindow(owner->window) && !DestroyWindow(owner->window)) result = 3;
    return result;
}

static DWORD WINAPI input_thread(void *argument) {
    DWORD count = 0;
    unsigned char byte;
    (void)argument;
    if (!ReadFile(GetStdHandle(STD_INPUT_HANDLE), &byte, 1, &count, NULL)) {
        return GetLastError() == ERROR_BROKEN_PIPE ? 0 : 2;
    }
    return count == 0 ? 0 : 2;
}

static int serve(WindowOwner *owner, HANDLE thread, const char *challenge) {
    HANDLE waits[2] = {owner->ready, thread};
    HANDLE input;
    DWORD code = 3, outcome;
    int result = 3;
    if (WaitForMultipleObjects(2, waits, FALSE, 5000) != WAIT_OBJECT_0 || !owner->window) return 3;
    printf("{\"fixture\":\"uia\",\"version\":1,\"pid\":%lu,\"hwnd\":%llu,\"challenge\":\"%s\"}\n",
        GetCurrentProcessId(), (unsigned long long)(uintptr_t)owner->window, challenge);
    if (ferror(stdout)) return 2;
    input = CreateThread(NULL, 0, input_thread, NULL, 0, NULL);
    if (!input) return 3;
    waits[0] = thread;
    waits[1] = input;
    outcome = WaitForMultipleObjects(2, waits, FALSE, INFINITE);
    if (outcome == WAIT_OBJECT_0 + 1 && GetExitCodeThread(input, &code)) result = (int)code;
    if (WaitForSingleObject(input, 0) != WAIT_OBJECT_0) CancelSynchronousIo(input);
    if (WaitForSingleObject(input, 5000) != WAIT_OBJECT_0) ExitProcess(3);
    if (!CloseHandle(input)) result = 3;
    return result;
}

static int retire(WindowOwner *owner, HANDLE thread, int result) {
    HANDLE handles[3] = {thread, owner->stop, owner->ready};
    DWORD code = 3;
    size_t i;
    if (thread) {
        if (!SetEvent(owner->stop) || WaitForSingleObject(thread, 5000) != WAIT_OBJECT_0) {
            ExitProcess(3);
        }
        if (!GetExitCodeThread(thread, &code) || code != 0) result = 3;
    }
    for (i = 0; i < sizeof(handles) / sizeof(handles[0]); ++i) {
        if (handles[i] && !CloseHandle(handles[i])) result = 3;
    }
    return result;
}

int main(int argc, char **argv) {
    WindowOwner owner = {0};
    HANDLE thread = NULL;
    int result = 3;
    if (sizeof(void *) != 8 || !challenge_valid(argc, argv)) return 2;
    if (GetFileType(GetStdHandle(STD_INPUT_HANDLE)) != FILE_TYPE_PIPE ||
        GetFileType(GetStdHandle(STD_OUTPUT_HANDLE)) != FILE_TYPE_PIPE) return 2;
    if (_setmode(_fileno(stdout), _O_BINARY) == -1) return 2;
    setvbuf(stdout, NULL, _IONBF, 0);
    owner.ready = CreateEventW(NULL, TRUE, FALSE, NULL);
    owner.stop = CreateEventW(NULL, TRUE, FALSE, NULL);
    if (owner.ready && owner.stop) thread = CreateThread(NULL, 0, window_thread, &owner, 0, NULL);
    if (thread) result = serve(&owner, thread, argv[2]);
    return retire(&owner, thread, result);
}
