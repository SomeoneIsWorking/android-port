package io.github.someoneisworking.android;

import com.sun.net.httpserver.HttpServer;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Arrays;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

public final class AndroidDownloadQueueTest {
    private static byte[] body(int size, int seed) {
        byte[] bytes = new byte[size];
        for (int at = 0; at < size; at++) bytes[at] = (byte) (at * 31 + seed);
        return bytes;
    }

    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }

    public static void main(String[] arguments) throws Exception {
        File root = new File(arguments[0]);
        AndroidImportPromotion.remove(root);
        if (!root.mkdirs()) throw new IOException("cannot create " + root);
        byte[] first = body(300_000, 1);
        byte[] second = body(5_000, 2);
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/", exchange -> {
            byte[] content = exchange.getRequestURI().getPath().equals("/a") ? first
                    : exchange.getRequestURI().getPath().equals("/b") ? second : null;
            if (content == null) {
                exchange.sendResponseHeaders(404, -1);
                exchange.close();
                return;
            }
            String range = exchange.getRequestHeaders().getFirst("Range");
            int from = range == null ? 0 : Integer.parseInt(range.substring(6, range.length() - 1));
            exchange.sendResponseHeaders(from == 0 ? 200 : 206, content.length - from);
            try (OutputStream out = exchange.getResponseBody()) {
                out.write(content, from, content.length - from);
            }
        });
        server.start();
        String base = "http://127.0.0.1:" + server.getAddress().getPort() + "/";
        try {
            File a = new File(root, "deep/a.bin");
            File b = new File(root, "b.bin");
            File missing = new File(root, "missing.bin");
            // Half of a, landed by an earlier run, is resumed rather than fetched again.
            a.getParentFile().mkdirs();
            try (FileOutputStream partial = new FileOutputStream(a.getPath() + ".tmp")) {
                partial.write(first, 0, first.length / 2);
            }
            File list = new File(root, "jobs.tsv");
            Files.write(list.toPath(), (first.length + "\t" + base + "a\t" + a + "\n"
                    + second.length + "\t" + base + "b\t" + b + "\n"
                    + "10\t" + base + "none\t" + missing + "\n").getBytes(StandardCharsets.UTF_8));
            List<AndroidDownloadQueue.Job> jobs = AndroidDownloadQueue.readJobs(list);
            CountDownLatch done = new CountDownLatch(1);
            int[] failed = {-1};
            long[] last = {-1};
            AndroidDownloadQueue queue = new AndroidDownloadQueue(jobs, 2, ".tmp", 5000,
                    new AndroidDownloadQueue.Listener() {
                        @Override
                        public void progress(long bytes, long totalBytes, int landed, int count) {
                            last[0] = bytes;
                        }

                        @Override
                        public void finished(int failures) {
                            failed[0] = failures;
                            done.countDown();
                        }
                    });
            queue.start();
            queue.start();
            check(done.await(30, TimeUnit.SECONDS), "the queue never finished");
            check(failed[0] == 1, "expected one failure, got " + failed[0]);
            check(Arrays.equals(Files.readAllBytes(a.toPath()), first), "a was not resumed intact");
            check(Arrays.equals(Files.readAllBytes(b.toPath()), second), "b did not land");
            check(!new File(a.getPath() + ".tmp").exists(), "a's partial file was left behind");
            check(!missing.exists(), "a failed job left a file");
            check(last[0] == first.length + second.length, "progress ended at " + last[0]);
            String state = queue.poll(0);
            check(state.startsWith("{\"running\":false,\"bytes\":" + (first.length + second.length)), state);
            check(state.contains("\"landedCount\":2"), state);
            check(state.contains("\"failures\":{\"2\":\"" + base + "none: java.io.IOException: HTTP 404\"}"), state);
            check(queue.poll(2).contains("\"landed\":[]"), queue.poll(2));
            System.out.println("Android download queue: resume, fresh, 404 and polling passed");
        } finally {
            server.stop(0);
        }
    }
}
