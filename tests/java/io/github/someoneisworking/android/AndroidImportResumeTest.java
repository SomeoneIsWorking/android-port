package io.github.someoneisworking.android;

import java.io.ByteArrayInputStream;
import java.io.File;
import java.io.IOException;
import java.nio.file.Files;

public final class AndroidImportResumeTest {
    private static void check(boolean value, String reason) {
        if (!value) throw new AssertionError(reason);
    }

    private static void changed(ByteArrayInputStream source, File staged) throws IOException {
        try {
            AndroidImportResume.verifyPrefix(source, staged, staged.length(), 4096);
        } catch (AndroidImportResume.SourceChanged expected) {
            return;
        }
        throw new AssertionError("changed or truncated source was accepted for resume");
    }

    public static void main(String[] args) throws IOException {
        if (args.length != 1) throw new IllegalArgumentException("one build-local test directory required");
        File root = new File(args[0]);
        check(AndroidImportPromotion.remove(root), "stale test output could not be removed");
        check(root.mkdirs(), "could not create test output");
        try {
            File staged = new File(root, "input.zip");
            byte[] prefix = new byte[8193];
            for (int index = 0; index < prefix.length; ++index) prefix[index] = (byte) index;
            Files.write(staged.toPath(), prefix);
            byte[] whole = java.util.Arrays.copyOf(prefix, prefix.length + 3);
            whole[prefix.length] = 42;
            ByteArrayInputStream same = new ByteArrayInputStream(whole);
            AndroidImportResume.verifyPrefix(same, staged, prefix.length, 4096);
            check(same.read() == 42, "verified source is not positioned for append");

            whole[4096] ^= 1;
            changed(new ByteArrayInputStream(whole), staged);
            changed(new ByteArrayInputStream(new byte[4096]), staged);
            check(Files.size(staged.toPath()) == prefix.length, "verification mutated staged bytes");
            System.out.println("Android import resume: exact prefix and changed/truncated refusal passed");
        } finally {
            check(AndroidImportPromotion.remove(root), "test output cleanup failed");
        }
    }
}
