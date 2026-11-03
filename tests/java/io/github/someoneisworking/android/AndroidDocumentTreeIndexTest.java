package io.github.someoneisworking.android;

import java.io.IOException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

public final class AndroidDocumentTreeIndexTest {
    private static void check(boolean value, String reason) {
        if (!value) throw new AssertionError(reason);
    }

    private static void refused(String path, int errno) {
        try {
            AndroidDocumentTreeIndex.components(path);
        } catch (AndroidDocumentTreeIndex.Failure expected) {
            check(expected.errno == errno, "wrong errno for " + path);
            return;
        }
        throw new AssertionError("unsafe path was accepted: " + path);
    }

    /** A provider whose listings are counted, so caching is observable. */
    private static final class Provider implements AndroidDocumentTreeIndex.Lister {
        final Map<String, List<AndroidDocumentTreeIndex.Entry>> children = new HashMap<>();
        final Map<String, Integer> queries = new HashMap<>();

        void add(String parent, String id, String name, boolean directory, long size) {
            children.computeIfAbsent(parent, key -> new ArrayList<>())
                    .add(new AndroidDocumentTreeIndex.Entry(id, name, directory, size, 7));
        }

        @Override
        public List<AndroidDocumentTreeIndex.Entry> children(String documentId) {
            queries.merge(documentId, 1, Integer::sum);
            return new ArrayList<>(children.getOrDefault(documentId, List.of()));
        }
    }

    public static void main(String[] args) throws IOException {
        check(AndroidDocumentTreeIndex.components("").isEmpty(), "empty path is not the root");
        check(AndroidDocumentTreeIndex.components("game/Data/a.igb")
                .equals(Arrays.asList("game", "Data", "a.igb")), "components split wrongly");
        check(AndroidDocumentTreeIndex.parent("game/Data/a.igb").equals("game/Data"), "parent");
        check(AndroidDocumentTreeIndex.parent("game").isEmpty(), "top-level parent is the root");
        check(AndroidDocumentTreeIndex.leaf("game/Data/a.igb").equals("a.igb"), "leaf");
        refused("game/../user", AndroidDocumentTreeIndex.EINVAL);
        refused("/game", AndroidDocumentTreeIndex.EINVAL);
        refused("game//Data", AndroidDocumentTreeIndex.EINVAL);
        refused("game\\Data", AndroidDocumentTreeIndex.EINVAL);
        refused(".", AndroidDocumentTreeIndex.EINVAL);

        Provider provider = new Provider();
        provider.add("root", "g", "game", true, 0);
        provider.add("root", "u", "user", true, 0);
        provider.add("g", "exe", "XMen2.exe", false, 4096);
        provider.add("g", "d", "Data", true, 0);
        provider.add("d", "a", "a.igb", false, 10);
        AndroidDocumentTreeIndex index = new AndroidDocumentTreeIndex("root", provider);

        AndroidDocumentTreeIndex.Entry exe = index.find("game/XMen2.exe");
        check(exe != null && exe.documentId.equals("exe") && exe.size == 4096 && !exe.directory,
                "file entry was not resolved");
        check(index.find("game/xmen2.exe") == null, "the index folded case");
        check(index.find("game/XMen2.exe/inside") == null, "a file was treated as a directory");
        check(index.find("game/Missing/a.igb") == null, "a missing directory resolved");
        check(index.find("").directory, "the root is not a directory");
        index.find("game/Data/a.igb");
        index.find("game/Data/a.igb");
        check(provider.queries.get("g") == 1 && provider.queries.get("d") == 1,
                "a cached directory was queried again");
        check(index.list("game").size() == 2, "directory listing is incomplete");

        try {
            index.directory("game/XMen2.exe");
            throw new AssertionError("a file was listed as a directory");
        } catch (AndroidDocumentTreeIndex.Failure expected) {
            check(expected.errno == AndroidDocumentTreeIndex.ENOTDIR, "wrong errno for a file listing");
        }
        try {
            index.list("game/Nothing");
            throw new AssertionError("a missing directory was listed");
        } catch (AndroidDocumentTreeIndex.Failure expected) {
            check(expected.errno == AndroidDocumentTreeIndex.ENOENT, "wrong errno for a missing listing");
        }

        check(index.find("user/x2native.conf") == null, "an absent file resolved");
        provider.add("u", "s", "x2native.conf", false, 3);
        check(index.find("user/x2native.conf") == null, "a cached listing saw a later change");
        index.forget("user");
        check(index.find("user/x2native.conf") != null, "forget did not re-query the directory");
        check(provider.queries.get("u") == 2, "forget re-queried the wrong number of times");
        index.clear();
        index.find("game/Data/a.igb");
        check(provider.queries.get("g") == 2 && provider.queries.get("d") == 2, "clear kept listings");

        Provider duplicate = new Provider();
        duplicate.add("root", "one", "Save", true, 0);
        duplicate.add("root", "two", "Save", true, 0);
        try {
            new AndroidDocumentTreeIndex("root", duplicate).find("Save");
            throw new AssertionError("a duplicated name was indexed");
        } catch (AndroidDocumentTreeIndex.Failure expected) {
            check(expected.errno == AndroidDocumentTreeIndex.EIO, "wrong errno for a duplicate");
        }
        Provider unsafe = new Provider();
        unsafe.add("root", "bad", "../escape", false, 0);
        try {
            new AndroidDocumentTreeIndex("root", unsafe).find("anything");
            throw new AssertionError("an unsafe provider name was indexed");
        } catch (AndroidDocumentTreeIndex.Failure expected) {
            check(expected.errno == AndroidDocumentTreeIndex.EINVAL, "wrong errno for an unsafe name");
        }
        System.out.println("AndroidDocumentTreeIndex: path, cache, invalidation and refusal contracts hold");
    }
}
