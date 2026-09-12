package io.github.someoneisworking.android;

import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;

/** Verifies a staged document before appending bytes from a reopened SAF stream. */
final class AndroidImportResume {
    static final class SourceChanged extends IOException {
        SourceChanged() {
            super("resumable source changed; the partial copy was discarded");
        }
    }

    private AndroidImportResume() {}

    /** Leaves {@code source} positioned immediately after the verified prefix. */
    static void verifyPrefix(InputStream source, File staged, long bytes, int bufferBytes)
            throws IOException {
        if (bytes < 0 || bufferBytes < 4096 || staged.length() != bytes) {
            throw new SourceChanged();
        }
        byte[] fromSource = new byte[bufferBytes];
        byte[] fromStage = new byte[bufferBytes];
        try (InputStream existing = new FileInputStream(staged)) {
            long checked = 0;
            while (checked < bytes) {
                if (Thread.currentThread().isInterrupted()) {
                    throw new IOException("import cancelled");
                }
                int length = (int) Math.min(bufferBytes, bytes - checked);
                if (!readExactly(source, fromSource, length)
                        || !readExactly(existing, fromStage, length)) {
                    throw new SourceChanged();
                }
                for (int index = 0; index < length; ++index) {
                    if (fromSource[index] != fromStage[index]) throw new SourceChanged();
                }
                checked += length;
            }
        }
    }

    private static boolean readExactly(InputStream input, byte[] buffer, int length) throws IOException {
        int read = 0;
        while (read < length) {
            int count = input.read(buffer, read, length - read);
            if (count < 0) return false;
            if (count == 0) {
                int next = input.read();
                if (next < 0) return false;
                buffer[read++] = (byte) next;
            } else {
                read += count;
            }
        }
        return true;
    }
}
