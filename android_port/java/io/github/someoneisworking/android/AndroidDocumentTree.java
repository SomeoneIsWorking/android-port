package io.github.someoneisworking.android;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.ContentResolver;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.UriPermission;
import android.database.Cursor;
import android.net.Uri;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.os.ParcelFileDescriptor;
import android.provider.DocumentsContract;
import android.system.OsConstants;
import android.util.Log;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileNotFoundException;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * A player-selected shared-storage folder, kept across launches and reinstalls.
 *
 * <p>Package storage is deleted on uninstall; a folder the player picks with
 * {@code ACTION_OPEN_DOCUMENT_TREE} is not. This class owns the picker, the persisted read/write
 * grant, the remembered tree URI, a cached path index over the tree, descriptor opening for native
 * code, and publication of a validated private directory into the tree. Files a previous install
 * created there are not readable by filesystem path after a reinstall, so every access goes through
 * the document provider. The grant itself dies with the package: after a reinstall the player picks
 * the same folder again and the title validates it in place.</p>
 */
public final class AndroidDocumentTree {
    public interface PublishListener {
        /** Main thread, at most every 500 ms. */
        void onProgress(long entries, long bytes, long totalBytes, String currentName);
    }

    public interface PublishCallback {
        void onPublished();
        void onFailed(String message);
    }

    private static final String TAG = "AndroidDocumentTree";
    private static final String PREFERENCES = "android-document-tree";
    private static final String STORAGE_AUTHORITY = "com.android.externalstorage.documents";
    private static final String PARTIAL_SUFFIX = ".partial";
    /** Names only a complete replacement waiting to take its base name; see {@link #replace}. */
    private static final String REPLACEMENT_SUFFIX = ".new";
    private static final String FILE_MIME = "application/octet-stream";
    private static final int GRANT = Intent.FLAG_GRANT_READ_URI_PERMISSION
            | Intent.FLAG_GRANT_WRITE_URI_PERMISSION;
    private static final long PROGRESS_INTERVAL_MILLIS = 500;
    private static final int BUFFER_BYTES = 256 * 1024;
    private static final String[] COLUMNS = {
            DocumentsContract.Document.COLUMN_DOCUMENT_ID,
            DocumentsContract.Document.COLUMN_DISPLAY_NAME,
            DocumentsContract.Document.COLUMN_MIME_TYPE,
            DocumentsContract.Document.COLUMN_SIZE,
            DocumentsContract.Document.COLUMN_LAST_MODIFIED,
    };
    private static final AtomicBoolean PUBLISHING = new AtomicBoolean();

    private final ContentResolver resolver;
    private final Uri tree;
    private final AndroidDocumentTreeIndex index;
    private final Handler main = new Handler(Looper.getMainLooper());
    private Thread publication;

    private AndroidDocumentTree(Context context, Uri tree) {
        this.resolver = context.getApplicationContext().getContentResolver();
        this.tree = tree;
        this.index = new AndroidDocumentTreeIndex(DocumentsContract.getTreeDocumentId(tree), this::query);
    }

    /**
     * Opens the system folder picker. On Android 8+ it starts in {@code initialFolder} of primary
     * shared storage (for example {@code "Documents"}); the player can create a subfolder there.
     */
    public static boolean pick(Activity activity, int requestCode, String initialFolder) {
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT_TREE);
        intent.addFlags(GRANT | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION
                | Intent.FLAG_GRANT_PREFIX_URI_PERMISSION);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && initialFolder != null) {
            intent.putExtra(DocumentsContract.EXTRA_INITIAL_URI,
                    DocumentsContract.buildDocumentUri(STORAGE_AUTHORITY, "primary:" + initialFolder));
        }
        try {
            activity.startActivityForResult(intent, requestCode);
            return true;
        } catch (ActivityNotFoundException error) {
            return false;
        }
    }

    /**
     * Keeps the picked folder: takes the persistable read/write grant and remembers its URI under
     * {@code key}. Returns null when the picker was cancelled.
     */
    public static AndroidDocumentTree accept(Context context, int resultCode, Intent data, String key)
            throws IOException {
        if (resultCode != Activity.RESULT_OK || data == null || data.getData() == null) return null;
        Uri picked = data.getData();
        if ((data.getFlags() & GRANT) != GRANT) {
            throw new IOException("the folder picker did not grant read and write access");
        }
        try {
            context.getContentResolver().takePersistableUriPermission(picked, GRANT);
        } catch (SecurityException error) {
            throw new IOException("Android could not retain access to the folder", error);
        }
        preferences(context).edit().putString(key, picked.toString()).apply();
        return new AndroidDocumentTree(context, picked);
    }

    /** The folder remembered under {@code key}, or null when its grant no longer exists. */
    public static AndroidDocumentTree remembered(Context context, String key) {
        String saved = preferences(context).getString(key, null);
        if (saved == null) return null;
        Uri uri = Uri.parse(saved);
        for (UriPermission permission : context.getContentResolver().getPersistedUriPermissions()) {
            if (permission.getUri().equals(uri) && permission.isReadPermission()
                    && permission.isWritePermission()) {
                return new AndroidDocumentTree(context, uri);
            }
        }
        preferences(context).edit().remove(key).apply();
        return null;
    }

    public static boolean publishing() {
        return PUBLISHING.get();
    }

    public Uri uri() {
        return tree;
    }

    // --- Native file access: any thread; failures are negative errno values. ---

    /** A detached descriptor the caller owns, opened in {@link ParcelFileDescriptor} mode. */
    public int openDescriptor(String path, String mode, boolean create, boolean exclusive) {
        try {
            settle(path);
            AndroidDocumentTreeIndex.Entry entry = index.find(path);
            if (entry != null && create && exclusive) return -OsConstants.EEXIST;
            if (entry != null && entry.directory) return -OsConstants.EISDIR;
            Uri document;
            if (entry != null) {
                document = documentUri(entry.documentId);
            } else if (create) {
                document = createDocument(path, FILE_MIME);
            } else {
                return -OsConstants.ENOENT;
            }
            ParcelFileDescriptor descriptor = resolver.openFileDescriptor(document, mode);
            if (descriptor == null) return -OsConstants.EIO;
            return descriptor.detachFd();
        } catch (IOException | RuntimeException error) {
            return failure("open " + path, error);
        }
    }

    /** {directory ? 1 : 0, size, last modified ms}, or null when absent. */
    public long[] status(String path) {
        try {
            settle(path);
            AndroidDocumentTreeIndex.Entry entry = index.find(path);
            if (entry == null) return null;
            return new long[] {entry.directory ? 1 : 0, entry.size, entry.lastModifiedMillis};
        } catch (IOException | RuntimeException error) {
            failure("stat " + path, error);
            return null;
        }
    }

    /** The names in a directory, or null when it is absent or not a directory. */
    public String[] children(String path) {
        try {
            for (AndroidDocumentTreeIndex.Entry entry : index.list(path)) {
                if (entry.name.endsWith(REPLACEMENT_SUFFIX)) {
                    String base = entry.name.substring(0, entry.name.length() - REPLACEMENT_SUFFIX.length());
                    settle(path.isEmpty() ? base : path + "/" + base);
                }
            }
            List<AndroidDocumentTreeIndex.Entry> entries = index.list(path);
            String[] names = new String[entries.size()];
            for (int item = 0; item < names.length; ++item) names[item] = entries.get(item).name;
            return names;
        } catch (IOException | RuntimeException error) {
            failure("list " + path, error);
            return null;
        }
    }

    public int makeDirectory(String path) {
        try {
            if (index.find(path) != null) return -OsConstants.EEXIST;
            createDocument(path, DocumentsContract.Document.MIME_TYPE_DIR);
            return 0;
        } catch (IOException | RuntimeException error) {
            return failure("mkdir " + path, error);
        }
    }

    /** Removes a file, or an empty directory when {@code directory} is set. */
    public int delete(String path, boolean directory) {
        try {
            AndroidDocumentTreeIndex.Entry entry = index.find(path);
            if (entry == null) return -OsConstants.ENOENT;
            if (entry.directory != directory) {
                return directory ? -OsConstants.ENOTDIR : -OsConstants.EISDIR;
            }
            if (directory && !index.list(path).isEmpty()) return -OsConstants.ENOTEMPTY;
            deleteDocument(entry, path);
            return 0;
        } catch (IOException | RuntimeException error) {
            return failure("delete " + path, error);
        }
    }

    /**
     * Replaces {@code to} with the complete file {@code from} in the same directory.
     *
     * <p>A provider cannot rename over an existing document, so {@code from} first takes the name
     * {@code <to>.new}, which therefore only ever names a complete file; then {@code to} is deleted
     * and {@code <to>.new} takes its name. A crash between the steps leaves either the old file or
     * the new one, and {@link #settle} finishes the swap on the next access.</p>
     */
    public int replace(String from, String to) {
        try {
            String parent = AndroidDocumentTreeIndex.parent(from);
            if (!parent.equals(AndroidDocumentTreeIndex.parent(to))) return -OsConstants.EXDEV;
            if (to.endsWith(REPLACEMENT_SUFFIX)) return -OsConstants.EINVAL;
            String pending = to + REPLACEMENT_SUFFIX;
            AndroidDocumentTreeIndex.Entry source = index.find(from);
            if (source == null) return -OsConstants.ENOENT;
            AndroidDocumentTreeIndex.Entry stale = index.find(pending);
            if (stale != null) deleteDocument(stale, pending);
            rename(source, from, pending);
            settle(to);
            return 0;
        } catch (IOException | RuntimeException error) {
            return failure("replace " + from, error);
        }
    }

    /** Finishes an interrupted {@link #replace}: a {@code <path>.new} is newer than {@code path}. */
    private void settle(String path) throws IOException {
        if (path.isEmpty() || path.endsWith(REPLACEMENT_SUFFIX)) return;
        String pending = path + REPLACEMENT_SUFFIX;
        AndroidDocumentTreeIndex.Entry replacement = index.find(pending);
        if (replacement == null || replacement.directory) return;
        AndroidDocumentTreeIndex.Entry target = index.find(path);
        if (target != null) {
            if (target.directory) {
                throw new AndroidDocumentTreeIndex.Failure(OsConstants.EISDIR, path + " is a directory");
            }
            deleteDocument(target, path);
        }
        rename(replacement, pending, path);
    }

    private void deleteDocument(AndroidDocumentTreeIndex.Entry entry, String path) throws IOException {
        if (!DocumentsContract.deleteDocument(resolver, documentUri(entry.documentId))) {
            throw new AndroidDocumentTreeIndex.Failure(OsConstants.EIO, "provider did not delete " + path);
        }
        index.forget(AndroidDocumentTreeIndex.parent(path));
    }

    /** Renames {@code from} to the absent name {@code to} in the same directory. */
    private void rename(AndroidDocumentTreeIndex.Entry entry, String from, String to) throws IOException {
        String leaf = AndroidDocumentTreeIndex.leaf(to);
        Uri renamed = DocumentsContract.renameDocument(resolver, documentUri(entry.documentId), leaf);
        index.forget(AndroidDocumentTreeIndex.parent(to));
        if (renamed == null || index.find(to) == null) {
            throw new AndroidDocumentTreeIndex.Failure(OsConstants.EIO,
                    "provider did not rename " + from + " to " + leaf);
        }
    }

    // --- Publication of a validated private directory. ---

    /**
     * Copies {@code source} into this folder as {@code destinationName}, off the main thread.
     *
     * <p>The copy is written under a {@code .partial} name and replaces an existing destination
     * only once it is complete. The callback runs on the main thread.</p>
     */
    public synchronized void publish(File source, String destinationName, PublishListener listener,
                                     PublishCallback callback) {
        if (callback == null) throw new IllegalArgumentException("callback is required");
        if (!PUBLISHING.compareAndSet(false, true)) {
            callback.onFailed("A folder copy is already active.");
            return;
        }
        publication = new Thread(() -> {
            String failure = null;
            try {
                copyPublication(source, destinationName, listener);
            } catch (IOException | RuntimeException error) {
                failure = error.getMessage() == null ? error.toString() : error.getMessage();
                Log.w(TAG, "publication failed", error);
            } finally {
                index.clear();
                PUBLISHING.set(false);
            }
            String message = failure;
            main.post(() -> {
                if (message == null) callback.onPublished();
                else callback.onFailed(message);
            });
        }, "android-document-tree-publish");
        publication.start();
    }

    public synchronized void cancelPublication() {
        if (publication != null) publication.interrupt();
    }

    private void copyPublication(File source, String destinationName, PublishListener listener)
            throws IOException {
        AndroidDocumentTreeIndex.checkLeaf(destinationName);
        if (!source.isDirectory()) throw new IOException("publication source is not a directory");
        Progress progress = new Progress(listener, measure(source));
        String partialName = destinationName + PARTIAL_SUFFIX;
        removeChild(partialName);
        Uri partial = DocumentsContract.createDocument(resolver, documentUri(rootId()),
                DocumentsContract.Document.MIME_TYPE_DIR, partialName);
        if (partial == null) throw new IOException("cannot create " + partialName + " in the folder");
        copyDirectory(source, partial, progress);
        removeChild(destinationName);
        if (DocumentsContract.renameDocument(resolver, partial, destinationName) == null) {
            throw new IOException("cannot rename " + partialName + " to " + destinationName);
        }
        index.clear();
        if (index.find(destinationName) == null) {
            throw new IOException("the folder did not keep the name " + destinationName);
        }
    }

    private void copyDirectory(File source, Uri destination, Progress progress) throws IOException {
        File[] children = source.listFiles();
        if (children == null) throw new IOException("cannot list " + source.getName());
        for (File child : children) {
            checkInterrupted();
            AndroidDocumentTreeIndex.checkLeaf(child.getName());
            boolean directory = child.isDirectory();
            Uri created = DocumentsContract.createDocument(resolver, destination,
                    directory ? DocumentsContract.Document.MIME_TYPE_DIR : FILE_MIME, child.getName());
            if (created == null) throw new IOException("cannot create " + child.getName());
            progress.entry(child.getName());
            if (directory) {
                copyDirectory(child, created, progress);
            } else {
                copyFile(child, created, progress);
            }
        }
    }

    private void copyFile(File source, Uri destination, Progress progress) throws IOException {
        byte[] buffer = new byte[BUFFER_BYTES];
        try (InputStream input = new FileInputStream(source);
             OutputStream output = resolver.openOutputStream(destination, "w")) {
            if (output == null) throw new IOException("cannot write " + source.getName());
            for (int count; (count = input.read(buffer)) >= 0; ) {
                checkInterrupted();
                output.write(buffer, 0, count);
                progress.bytes(count, source.getName());
            }
        }
    }

    private void removeChild(String name) throws IOException {
        index.clear();
        AndroidDocumentTreeIndex.Entry existing = index.find(name);
        if (existing != null && !DocumentsContract.deleteDocument(resolver, documentUri(existing.documentId))) {
            throw new IOException("cannot remove " + name + " from the folder");
        }
        index.clear();
    }

    private static long measure(File file) {
        if (!file.isDirectory()) return file.length();
        long total = 0;
        File[] children = file.listFiles();
        if (children != null) {
            for (File child : children) total += measure(child);
        }
        return total;
    }

    private static void checkInterrupted() throws IOException {
        if (Thread.currentThread().isInterrupted()) throw new IOException("folder copy cancelled");
    }

    private final class Progress {
        private final PublishListener listener;
        private final long totalBytes;
        private long entries;
        private long bytes;
        private long lastMillis;

        Progress(PublishListener listener, long totalBytes) {
            this.listener = listener;
            this.totalBytes = totalBytes;
        }

        void entry(String name) {
            entries++;
            report(name);
        }

        void bytes(long count, String name) {
            bytes += count;
            report(name);
        }

        private void report(String name) {
            if (listener == null) return;
            long now = android.os.SystemClock.uptimeMillis();
            if (now - lastMillis < PROGRESS_INTERVAL_MILLIS) return;
            lastMillis = now;
            long reportedEntries = entries;
            long reportedBytes = bytes;
            main.post(() -> listener.onProgress(reportedEntries, reportedBytes, totalBytes, name));
        }
    }

    // --- Provider access. ---

    private String rootId() {
        return DocumentsContract.getTreeDocumentId(tree);
    }

    private Uri documentUri(String documentId) {
        return DocumentsContract.buildDocumentUriUsingTree(tree, documentId);
    }

    private Uri createDocument(String path, String mime) throws IOException {
        String parentPath = AndroidDocumentTreeIndex.parent(path);
        AndroidDocumentTreeIndex.Entry parent = index.directory(parentPath);
        String leaf = AndroidDocumentTreeIndex.leaf(path);
        Uri created = DocumentsContract.createDocument(resolver, documentUri(parent.documentId), mime, leaf);
        if (created == null) {
            throw new AndroidDocumentTreeIndex.Failure(OsConstants.EIO, "provider refused to create " + path);
        }
        index.forget(parentPath);
        if (index.find(path) == null) {
            DocumentsContract.deleteDocument(resolver, created);
            index.forget(parentPath);
            throw new AndroidDocumentTreeIndex.Failure(OsConstants.EIO,
                    "provider stored " + path + " under another name");
        }
        return created;
    }

    private List<AndroidDocumentTreeIndex.Entry> query(String documentId) throws IOException {
        Uri children = DocumentsContract.buildChildDocumentsUriUsingTree(tree, documentId);
        List<AndroidDocumentTreeIndex.Entry> entries = new ArrayList<>();
        try (Cursor cursor = resolver.query(children, COLUMNS, null, null, null)) {
            if (cursor == null) {
                throw new AndroidDocumentTreeIndex.Failure(OsConstants.EIO, "provider returned no listing");
            }
            while (cursor.moveToNext()) {
                entries.add(new AndroidDocumentTreeIndex.Entry(
                        cursor.getString(0), cursor.getString(1),
                        DocumentsContract.Document.MIME_TYPE_DIR.equals(cursor.getString(2)),
                        cursor.isNull(3) ? 0 : cursor.getLong(3),
                        cursor.isNull(4) ? 0 : cursor.getLong(4)));
            }
        } catch (SecurityException error) {
            throw new AndroidDocumentTreeIndex.Failure(OsConstants.EACCES, "folder access was revoked");
        }
        return entries;
    }

    private static int failure(String operation, Throwable error) {
        int errno = OsConstants.EIO;
        if (error instanceof AndroidDocumentTreeIndex.Failure) {
            errno = ((AndroidDocumentTreeIndex.Failure) error).errno;
        } else if (error instanceof FileNotFoundException) {
            errno = OsConstants.ENOENT;
        } else if (error instanceof SecurityException) {
            errno = OsConstants.EACCES;
        }
        if (errno != OsConstants.ENOENT) Log.w(TAG, operation + " failed: " + error);
        return -errno;
    }

    private static SharedPreferences preferences(Context context) {
        return context.getApplicationContext().getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE);
    }
}
