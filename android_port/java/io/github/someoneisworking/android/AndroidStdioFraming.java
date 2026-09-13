package io.github.someoneisworking.android;

/**
 * Turns a byte stream's chunks into whole lines.
 *
 * <p>A native report can arrive in any number of reads, and a chunk can end in the middle of a line,
 * so nothing may be logged until its newline is seen. Platform-free on purpose: the framing rule is
 * what a reader depends on, and it is checked without a device.</p>
 */
public final class AndroidStdioFraming {
    private AndroidStdioFraming() {}

    /**
     * Appends one chunk to the pending line and returns every line the chunk completed, oldest
     * first. A trailing partial line stays in {@code pending} for the next chunk, an over-long line
     * is emitted in pieces rather than held forever, and a blank line is not returned at all — a
     * separator with nothing before it is noise, not a report.
     *
     * <p>Both newline characters separate, so a native line ending in CRLF breaks once and a
     * progress line rewritten with a bare carriage return does not accumulate.</p>
     *
     * @param pending holds the text after the last separator; cleared as lines are taken
     * @param maxChars longest piece a caller accepts before it must be emitted
     */
    public static java.util.List<String> take(StringBuilder pending, String chunk, int maxChars) {
        java.util.List<String> lines = new java.util.ArrayList<>();
        for (int index = 0; index < chunk.length(); index++) {
            char value = chunk.charAt(index);
            if (value == '\n' || value == '\r') {
                addLine(lines, pending);
            } else {
                pending.append(value);
                if (pending.length() >= maxChars) {
                    addLine(lines, pending);
                }
            }
        }
        return lines;
    }

    private static void addLine(java.util.List<String> lines, StringBuilder pending) {
        if (pending.length() == 0) {
            return;
        }
        lines.add(takePending(pending));
    }

    /** Returns the pending line and clears it; empty when nothing is pending. */
    public static String takePending(StringBuilder pending) {
        if (pending.length() == 0) {
            return "";
        }
        String line = pending.toString();
        pending.setLength(0);
        return line;
    }
}
