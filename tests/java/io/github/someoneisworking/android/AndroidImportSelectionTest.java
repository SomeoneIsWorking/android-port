package io.github.someoneisworking.android;

import java.io.IOException;
import java.util.ArrayList;
import java.util.List;

/** Multi-document selection rules: duplicates in, one staged copy out. */
public final class AndroidImportSelectionTest {
    private static void repeatedSourcesCollapseInReportedOrder() {
        final List<String> reported = new ArrayList<>(
                List.of("content://a/Disk.1", "content://a/Disk.2", "content://a/Disk.1"));
        if (!AndroidImportSelection.uniqueSources(reported).equals(
                List.of("content://a/Disk.1", "content://a/Disk.2"))) {
            throw new AssertionError("repeated sources were not collapsed in order");
        }
        if (!AndroidImportSelection.uniqueSources(List.of()).isEmpty()) {
            throw new AssertionError("an empty report produced entries");
        }
        // The caller's list is untouched: Android's own result is not mutated.
        if (reported.size() != 3) {
            throw new AssertionError("the reported selection was modified");
        }
    }

    private static void aRepeatedDisplayNameIsRefused() {
        final List<String> staged = new ArrayList<>(List.of("Disk.1", "Disk.2"));
        try {
            AndroidImportSelection.requireUnusedName(staged, "Disk.2");
            throw new AssertionError("a repeated display name was accepted");
        } catch (IOException expected) {
            if (!expected.getMessage().contains("Disk.2")) {
                throw new AssertionError("the refusal did not name the file: " + expected.getMessage());
            }
        }
        try {
            AndroidImportSelection.requireUnusedName(staged, "Disk.3");
        } catch (IOException unexpected) {
            throw new AssertionError("a new display name was refused: " + unexpected.getMessage());
        }
        if (staged.size() != 2) {
            throw new AssertionError("the staged names were modified");
        }
    }

    public static void main(String[] args) {
        repeatedSourcesCollapseInReportedOrder();
        aRepeatedDisplayNameIsRefused();
        System.out.println("Android import selection: dedupe and duplicate-name refusal passed");
    }
}
