package io.github.someoneisworking.android;

import android.Manifest;
import android.app.Activity;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import java.io.File;
import java.io.IOException;
import java.util.Locale;

/**
 * One process-wide download queue under a foreground dataSync notification with a progress bar,
 * so the transfer continues while the app is in the background. The title supplies the job list,
 * its wording and the Activity a tap returns to; a second start while one runs returns it.
 */
public final class AndroidBackgroundDownload {
    private static final int NOTIFICATION_PERMISSION_REQUEST = 0x444c;
    private static final double MEGABYTE = 1024.0 * 1024.0;
    private static AndroidDownloadQueue current;

    private AndroidBackgroundDownload() {}

    /** Starts the jobs in `jobs`, or returns the queue already running. Call while visible. */
    public static synchronized AndroidDownloadQueue start(Activity activity, File jobs, int workers,
            String partialSuffix, int timeoutMs, int notificationId, String channelId,
            String channelName, String title, Class<? extends Activity> destination)
            throws IOException {
        if (current != null && !current.finished()) {
            return current;
        }
        if (Build.VERSION.SDK_INT >= 33
                && activity.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                        != PackageManager.PERMISSION_GRANTED) {
            activity.requestPermissions(new String[] {Manifest.permission.POST_NOTIFICATIONS},
                    NOTIFICATION_PERMISSION_REQUEST);
        }
        Handler main = new Handler(Looper.getMainLooper());
        AndroidImportProgress progress = new AndroidImportProgress(
                activity, notificationId, channelId, channelName, title, destination);
        AndroidDownloadQueue queue = new AndroidDownloadQueue(AndroidDownloadQueue.readJobs(jobs),
                workers, partialSuffix, timeoutMs, new AndroidDownloadQueue.Listener() {
                    @Override
                    public void progress(long bytes, long totalBytes, int landed, int count) {
                        String text = String.format(Locale.US, "%.0f of %.0f MB",
                                bytes / MEGABYTE, totalBytes / MEGABYTE);
                        main.post(() -> progress.update(text, bytes, totalBytes));
                    }

                    @Override
                    public void finished(int failed) {
                        main.post(progress::stop);
                    }
                });
        // The foreground promotion happens on the main thread, before any worker runs.
        main.post(() -> {
            progress.start("Starting", 0, queue.totalBytes());
            queue.start();
        });
        current = queue;
        return queue;
    }
}
