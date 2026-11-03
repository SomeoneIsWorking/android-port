package io.github.someoneisworking.android;

import java.io.IOException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Cached relative-path index over one document tree.
 *
 * <p>A document tree names files by provider document IDs, and the only way from a path to an ID
 * is one child query per directory. This keeps each directory's listing once it has been queried,
 * so resolving a path costs memory lookups after the first visit. Every mutation made through the
 * owning tree forgets the directory it changed; nothing else may change the tree while it is
 * mounted. Names are exact: case folding belongs to the consumer that needs it.</p>
 */
final class AndroidDocumentTreeIndex {
    /* Linux errno values: this class has no android.system.OsConstants. */
    static final int ENOENT = 2;
    static final int EIO = 5;
    static final int ENOTDIR = 20;
    static final int EINVAL = 22;

    static final class Entry {
        final String documentId;
        final String name;
        final boolean directory;
        final long size;
        final long lastModifiedMillis;

        Entry(String documentId, String name, boolean directory, long size, long lastModifiedMillis) {
            this.documentId = documentId;
            this.name = name;
            this.directory = directory;
            this.size = size;
            this.lastModifiedMillis = lastModifiedMillis;
        }
    }

    interface Lister {
        List<Entry> children(String documentId) throws IOException;
    }

    /** A provider refusal carried with the errno the native caller receives. */
    static final class Failure extends IOException {
        final int errno;

        Failure(int errno, String message) {
            super(message);
            this.errno = errno;
        }
    }

    private final Lister lister;
    private final Entry root;
    private final Map<String, Map<String, Entry>> listings = new HashMap<>();

    AndroidDocumentTreeIndex(String rootDocumentId, Lister lister) {
        if (rootDocumentId == null || lister == null) {
            throw new IllegalArgumentException("root document and lister are required");
        }
        this.lister = lister;
        this.root = new Entry(rootDocumentId, "", true, 0, 0);
    }

    /** Splits a tree-relative path; the empty path is the tree root. */
    static List<String> components(String relativePath) throws Failure {
        if (relativePath == null) throw new Failure(EINVAL, "path is required");
        List<String> parts = new ArrayList<>();
        if (relativePath.isEmpty()) return parts;
        for (String part : relativePath.split("/", -1)) {
            checkLeaf(part);
            parts.add(part);
        }
        return parts;
    }

    static void checkLeaf(String name) throws Failure {
        if (name == null || name.isEmpty() || name.equals(".") || name.equals("..")
                || name.indexOf('/') >= 0 || name.indexOf('\\') >= 0) {
            throw new Failure(EINVAL, "unsafe tree name: " + name);
        }
    }

    static String parent(String relativePath) throws Failure {
        List<String> parts = components(relativePath);
        if (parts.isEmpty()) throw new Failure(EINVAL, "the tree root has no parent");
        return String.join("/", parts.subList(0, parts.size() - 1));
    }

    static String leaf(String relativePath) throws Failure {
        List<String> parts = components(relativePath);
        if (parts.isEmpty()) throw new Failure(EINVAL, "the tree root has no name");
        return parts.get(parts.size() - 1);
    }

    /** The entry at a path, or null when any component is absent. */
    synchronized Entry find(String relativePath) throws IOException {
        Entry current = root;
        for (String part : components(relativePath)) {
            if (!current.directory) return null;
            current = listing(current).get(part);
            if (current == null) return null;
        }
        return current;
    }

    /** The directory at a path, refusing a missing or non-directory entry. */
    synchronized Entry directory(String relativePath) throws IOException {
        Entry entry = find(relativePath);
        if (entry == null) throw new Failure(ENOENT, "no such directory: " + relativePath);
        if (!entry.directory) throw new Failure(ENOTDIR, "not a directory: " + relativePath);
        return entry;
    }

    synchronized List<Entry> list(String relativePath) throws IOException {
        return Collections.unmodifiableList(new ArrayList<>(listing(directory(relativePath)).values()));
    }

    /** Drops the cached listing of a directory after a name in it changed. */
    synchronized void forget(String relativeDirectory) throws IOException {
        Entry entry = find(relativeDirectory);
        if (entry != null) listings.remove(entry.documentId);
    }

    synchronized void clear() {
        listings.clear();
    }

    private Map<String, Entry> listing(Entry directory) throws IOException {
        Map<String, Entry> names = listings.get(directory.documentId);
        if (names != null) return names;
        names = new HashMap<>();
        for (Entry child : lister.children(directory.documentId)) {
            checkLeaf(child.name);
            if (names.put(child.name, child) != null) {
                throw new Failure(EIO, "provider listed one name twice: " + child.name);
            }
        }
        listings.put(directory.documentId, names);
        return names;
    }
}
