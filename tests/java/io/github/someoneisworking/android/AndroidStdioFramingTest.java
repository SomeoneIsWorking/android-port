package io.github.someoneisworking.android;

import java.util.List;

/** Checked without a device: the framing rule a native report's lines depend on. */
public final class AndroidStdioFramingTest {
    private static int failures;

    private static void check(boolean condition, String message) {
        if (!condition) {
            System.out.println("FAIL: " + message);
            failures++;
        }
    }

    public static void main(String[] args) {
        StringBuilder pending = new StringBuilder();

        // A chunk that ends mid-line must not be emitted until its newline arrives: a watchdog
        // report written in two writes would otherwise be logged as two truncated lines.
        List<String> lines = AndroidStdioFraming.take(pending, "error: signal: frame ne", 3000);
        check(lines.isEmpty(), "a partial line was emitted early: " + lines);
        check(pending.toString().equals("error: signal: frame ne"), "partial line was not kept");
        lines = AndroidStdioFraming.take(pending, "ver finished $000123\nnext line\n", 3000);
        check(lines.equals(List.of("error: signal: frame never finished $000123", "next line")),
              "line framing disagrees: " + lines);
        check(pending.length() == 0, "a complete line was left pending");

        // Carriage returns separate as well: a bare \r progress line must not leak into the report.
        lines = AndroidStdioFraming.take(pending, "one\r\ntwo\rthree", 3000);
        check(lines.equals(List.of("one", "two")),
              "carriage returns were not treated as separators: " + lines);
        check(pending.toString().equals("three"), "text after the last carriage return was lost");
        lines = AndroidStdioFraming.take(pending, " four\n", 3000);
        check(lines.equals(List.of("three four")), "a continued line was split: " + lines);

        // A line longer than the caller accepts is emitted in pieces rather than held forever.
        StringBuilder longPending = new StringBuilder();
        lines = AndroidStdioFraming.take(longPending, "x".repeat(25), 10);
        check(lines.equals(List.of("xxxxxxxxxx", "xxxxxxxxxx")),
              "an over-long line was not emitted in pieces: " + lines);
        check(longPending.toString().equals("xxxxx"), "the remainder of an over-long line was lost");
        lines = AndroidStdioFraming.take(longPending, "yyyyy", 10);
        check(lines.equals(List.of("xxxxxyyyyy")), "the remainder was not emitted: " + lines);

        // Nothing pending means nothing to log.
        check(AndroidStdioFraming.takePending(new StringBuilder()).isEmpty(),
              "an empty pending line produced text");

        System.out.println(failures == 0 ? "AndroidStdioFramingTest: ok" : "failures: " + failures);
        System.exit(failures == 0 ? 0 : 1);
    }
}
