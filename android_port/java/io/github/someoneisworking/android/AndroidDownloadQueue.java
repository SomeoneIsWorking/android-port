package io.github.someoneisworking.android;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Downloads a list of files on worker threads of its own, so a paused Activity or game thread
 * stops nothing. Each file lands in `destination + partialSuffix`, resumes from there with a
 * Range request, and is renamed into place once it has its listed size. Checking contents is the
 * title's; this owns transport, resumption and progress. Platform-free: Android presentation is
 * the listener's.
 */
public final class AndroidDownloadQueue {
    /** Progress, from the queue's own threads. */
    public interface Listener {
        void progress(long bytes, long totalBytes, int landed, int count);

        void finished(int failed);
    }

    /** One file: where it comes from, where it lands, and its size. */
    public static final class Job {
        final String url;
        final File destination;
        final long size;

        public Job(String url, File destination, long size) {
            if (size < 0) throw new IllegalArgumentException("negative size for " + url);
            this.url = url;
            this.destination = destination;
            this.size = size;
        }
    }

    private static final int BUFFER = 64 * 1024;
    private static final long PROGRESS_INTERVAL_MS = 500;

    private final List<Job> jobs;
    private final int workers;
    private final String partialSuffix;
    private final int timeoutMs;
    private final Listener listener;
    private final long totalBytes;
    private final AtomicLong bytes = new AtomicLong();
    private final AtomicInteger next = new AtomicInteger();
    private final List<Integer> landed = new ArrayList<>();
    private final Map<Integer, String> failures = new LinkedHashMap<>();
    private boolean started;
    private boolean finished;

    public AndroidDownloadQueue(List<Job> jobs, int workers, String partialSuffix, int timeoutMs,
                                Listener listener) {
        if (workers <= 0) throw new IllegalArgumentException("workers must be positive");
        this.jobs = Collections.unmodifiableList(new ArrayList<>(jobs));
        this.workers = workers;
        this.partialSuffix = partialSuffix;
        this.timeoutMs = timeoutMs;
        this.listener = listener;
        long total = 0;
        for (Job job : this.jobs) total += job.size;
        totalBytes = total;
    }

    /** Reads `size\turl\tdestination` lines, one job each. */
    public static List<Job> readJobs(File list) throws IOException {
        List<Job> jobs = new ArrayList<>();
        try (BufferedReader reader = new BufferedReader(
                new InputStreamReader(new FileInputStream(list), StandardCharsets.UTF_8))) {
            String line;
            while ((line = reader.readLine()) != null) {
                if (line.isEmpty()) continue;
                String[] fields = line.split("\t", -1);
                if (fields.length != 3) throw new IOException("malformed download job: " + line);
                jobs.add(new Job(fields[1], new File(fields[2]), Long.parseLong(fields[0])));
            }
        }
        return jobs;
    }

    /** Whether every job has landed or failed; false until then, started or not. */
    public synchronized boolean finished() {
        return finished;
    }

    public long totalBytes() {
        return totalBytes;
    }

    /** Starts the workers once; a second call leaves the running queue as it is. */
    public synchronized void start() {
        if (started) return;
        started = true;
        ExecutorService pool = Executors.newFixedThreadPool(workers);
        for (int worker = 0; worker < workers; worker++) {
            pool.execute(this::work);
        }
        pool.shutdown();
        Thread reporter = new Thread(() -> report(pool), "android-download-progress");
        reporter.setDaemon(true);
        reporter.start();
    }

    /**
     * The state as JSON: whether it is still to finish, the bytes landed, the jobs landed from position `from`
     * of the landing order on, and, once finished, each failed job's reason.
     */
    public synchronized String poll(int from) {
        StringBuilder json = new StringBuilder();
        json.append("{\"running\":").append(!finished)
                .append(",\"bytes\":").append(bytes.get())
                .append(",\"totalBytes\":").append(totalBytes)
                .append(",\"landedCount\":").append(landed.size())
                .append(",\"landed\":[");
        for (int at = Math.max(0, from); at < landed.size(); at++) {
            if (at > Math.max(0, from)) json.append(',');
            json.append(landed.get(at));
        }
        json.append("],\"failures\":{");
        if (finished) {
            boolean first = true;
            for (Map.Entry<Integer, String> failure : failures.entrySet()) {
                if (!first) json.append(',');
                first = false;
                json.append('"').append(failure.getKey()).append("\":");
                quote(json, failure.getValue());
            }
        }
        return json.append("}}").toString();
    }

    private void work() {
        for (int index = next.getAndIncrement(); index < jobs.size(); index = next.getAndIncrement()) {
            Job job = jobs.get(index);
            try {
                fetch(job);
                synchronized (this) {
                    landed.add(index);
                }
            } catch (IOException | RuntimeException error) {
                synchronized (this) {
                    failures.put(index, job.url + ": " + error);
                }
            }
        }
    }

    // A failure takes back the bytes it added to the count.
    private void fetch(Job job) throws IOException {
        File parent = job.destination.getParentFile();
        if (parent != null && !parent.isDirectory() && !parent.mkdirs() && !parent.isDirectory()) {
            throw new IOException("cannot create " + parent);
        }
        File partial = new File(job.destination.getPath() + partialSuffix);
        long have = partial.isFile() ? partial.length() : 0;
        if (have > job.size) {
            if (!partial.delete()) throw new IOException("cannot remove oversized " + partial);
            have = 0;
        }
        long counted = 0;
        if (have < job.size || job.size == 0) {
            HttpURLConnection connection = (HttpURLConnection) new URL(job.url).openConnection();
            try {
                connection.setConnectTimeout(timeoutMs);
                connection.setReadTimeout(timeoutMs);
                if (have > 0) connection.setRequestProperty("Range", "bytes=" + have + "-");
                int status = connection.getResponseCode();
                if (status != HttpURLConnection.HTTP_OK && status != HttpURLConnection.HTTP_PARTIAL) {
                    throw new IOException("HTTP " + status);
                }
                boolean append = have > 0 && status == HttpURLConnection.HTTP_PARTIAL;
                if (!append) have = 0;
                counted += have;
                bytes.addAndGet(have);
                byte[] buffer = new byte[BUFFER];
                try (InputStream in = connection.getInputStream();
                     OutputStream out = new FileOutputStream(partial, append)) {
                    for (int read = in.read(buffer); read >= 0; read = in.read(buffer)) {
                        out.write(buffer, 0, read);
                        counted += read;
                        bytes.addAndGet(read);
                    }
                }
            } catch (IOException error) {
                bytes.addAndGet(-counted);
                throw error;
            } finally {
                connection.disconnect();
            }
        } else {
            counted = have;
            bytes.addAndGet(have);
        }
        long received = partial.length();
        if (received != job.size) {
            bytes.addAndGet(-counted);
            if (received > job.size) partial.delete();
            throw new IOException("expected " + job.size + " bytes, received " + received);
        }
        if (job.destination.exists() && !job.destination.delete()) {
            bytes.addAndGet(-counted);
            throw new IOException("cannot replace " + job.destination);
        }
        if (!partial.renameTo(job.destination)) {
            bytes.addAndGet(-counted);
            throw new IOException("cannot move " + partial + " into place");
        }
    }

    private void report(ExecutorService pool) {
        try {
            while (!pool.awaitTermination(PROGRESS_INTERVAL_MS, TimeUnit.MILLISECONDS)) {
                listener.progress(bytes.get(), totalBytes, landedCount(), jobs.size());
            }
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
        }
        int failed;
        synchronized (this) {
            finished = true;
            failed = failures.size();
        }
        listener.progress(bytes.get(), totalBytes, landedCount(), jobs.size());
        listener.finished(failed);
    }

    private synchronized int landedCount() {
        return landed.size();
    }

    private static void quote(StringBuilder json, String text) {
        json.append('"');
        for (int at = 0; at < text.length(); at++) {
            char c = text.charAt(at);
            if (c == '"' || c == '\\') {
                json.append('\\').append(c);
            } else if (c < 0x20) {
                json.append(String.format("\\u%04x", (int) c));
            } else {
                json.append(c);
            }
        }
        json.append('"');
    }
}
