package io.github.someoneisworking.android;

import java.io.IOException;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;

/**
 * The rules a multi-document selection has to satisfy before any bytes are copied.
 *
 * <p>Android delivers a selection as one entry per picked document, and the same document can
 * appear twice (a re-returned {@code ClipData} item, or a picker that reports the tapped item in
 * both the data and the clip). A duplicate would otherwise be copied twice and counted twice
 * against the byte budget, and two documents with the same display name would collide in the
 * single staging directory the consumer sees.</p>
 */
final class AndroidImportSelection {
    private AndroidImportSelection() {}

    /** The selection with repeated sources dropped, in the order Android reported them. */
    static <T> List<T> uniqueSources(List<T> sources) {
        return new ArrayList<>(new LinkedHashSet<>(sources));
    }

    /**
     * Rejects a document whose display name the selection already staged.
     *
     * @throws IOException naming the repeated file, because two documents would collide at one
     *     staging path and the consumer must not silently receive only one of them.
     */
    static void requireUnusedName(List<String> documentNames, String documentName)
            throws IOException {
        if (documentNames.contains(documentName)) {
            throw new IOException("the selection contains two files named " + documentName);
        }
    }
}
