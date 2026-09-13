package io.github.someoneisworking.android;

import android.system.ErrnoException;
import android.system.Os;
import android.util.Log;

import java.io.FileDescriptor;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.Reader;
import java.nio.charset.StandardCharsets;

/**
 * Routes the process's standard streams into logcat.
 *
 * <p>Android gives an application no console: a native write to stdout or stderr goes nowhere, so a
 * port's own diagnostics — including the fatal report a watchdog prints from a signal handler — are
 * lost exactly when they are needed most. Duplicating a pipe onto both descriptors and reading it on
 * a Java thread puts those lines where {@code adb logcat} can see them.</p>
 *
 * <p>Native {@code write} into a pipe stays async-signal-safe, so a report emitted from a signal
 * handler arrives intact instead of being dropped.</p>
 */
public final class AndroidStdioLog {
    private static final int PIPE_READ = 0;
    private static final int PIPE_WRITE = 1;
    private static final int MAX_LINE_CHARS = 3000;

    private static Thread reader;

    private AndroidStdioLog() {}

    /** Redirects stdout and stderr into logcat under the given tag. Idempotent. */
    public static synchronized void redirect(String tag) {
        if (reader != null) {
            return;
        }
        String resolvedTag = tag == null || tag.isEmpty() ? "native" : tag;
        try {
            FileDescriptor[] pipe = Os.pipe();
            Os.dup2(pipe[PIPE_WRITE], 1);
            Os.dup2(pipe[PIPE_WRITE], 2);
            Os.close(pipe[PIPE_WRITE]);
            FileDescriptor source = pipe[PIPE_READ];
            reader = new Thread(() -> pump(source, resolvedTag), "native-stdio-log");
            reader.setDaemon(true);
            reader.start();
        } catch (ErrnoException error) {
            // A port whose diagnostics cannot be captured still works; say so once instead of dying.
            Log.w(resolvedTag, "standard streams stay uncaptured: " + error.getMessage());
        }
    }

    private static void pump(FileDescriptor source, String tag) {
        /* FileInputStream on a descriptor reports a broken stream by failing to
         * read, which the reader loop below turns into its own warning. */
        pump(new InputStreamReader(new FileInputStream(source), StandardCharsets.UTF_8), tag);
    }

    /** Framing and logging for one stream; a reader is supplied so the rule can be exercised. */
    static void pump(Reader source, String tag) {
        StringBuilder pending = new StringBuilder();
        char[] buffer = new char[2048];
        try {
            int count;
            while ((count = source.read(buffer)) > 0) {
                for (String line : AndroidStdioFraming.take(pending, new String(buffer, 0, count),
                                                            MAX_LINE_CHARS)) {
                    logLine(line, tag);
                }
            }
            logLine(AndroidStdioFraming.takePending(pending), tag);
        } catch (IOException error) {
            Log.w(tag, "standard stream capture stopped: " + error.getMessage());
        }
    }

    private static void logLine(String line, String tag) {
        if (line.isEmpty()) {
            return;
        }
        Log.i(tag, line);
    }
}
