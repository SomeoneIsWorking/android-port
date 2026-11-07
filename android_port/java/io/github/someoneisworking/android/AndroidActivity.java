package io.github.someoneisworking.android;

import android.os.Build;
import android.os.Bundle;
import android.view.DisplayCutout;
import android.view.MotionEvent;
import android.view.RoundedCorner;
import android.view.View;
import android.view.Window;
import android.view.WindowInsets;
import android.view.WindowInsetsController;

import org.libsdl.app.SDLActivity;

/**
 * Base SDLActivity for Android-backed SDL3 applications.
 *
 * Owns system UI visibility (sticky immersive landscape fullscreen) and graceful task termination.
 */
public class AndroidActivity extends SDLActivity {
    private final AndroidTouchContacts touchContacts = new AndroidTouchContacts();
    private volatile long contentInsets;

    /**
     * Installs title-owned contact interpretation without taking over Android or SDL event delivery.
     *
     * <p>The listener receives physical-pixel contacts before SDL handles the same event. It must map
     * those contacts through the title's normal input policy; it must not return Android event-consumed
     * state or create a second input transport.</p>
     */
    public final void setRawTouchListener(AndroidTouchContacts.Listener listener) {
        touchContacts.setListener(listener);
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        // Before anything native can report: an application has no console, so a native write
        // would otherwise be lost — including a watchdog's fatal report from a signal handler.
        AndroidStdioLog.redirect(getPackageName());
        hideSystemUI();
        getWindow().getDecorView().setOnApplyWindowInsetsListener((view, insets) -> {
            contentInsets = contentInsetsOf(insets);
            return view.onApplyWindowInsets(insets);
        });
    }

    /**
     * Pixels in from each edge that content keeps clear of to be seen whole: the display cutout and
     * the rounded corners, not the hidden bars' gesture strips. Packed 16 bits each, left lowest,
     * then top, right and bottom; callable from any thread.
     */
    public long contentInsets() {
        return contentInsets;
    }

    private static long contentInsetsOf(WindowInsets insets) {
        int left = 0;
        int top = 0;
        int right = 0;
        int bottom = 0;
        DisplayCutout cutout = insets.getDisplayCutout();
        if (cutout != null) {
            left = cutout.getSafeInsetLeft();
            top = cutout.getSafeInsetTop();
            right = cutout.getSafeInsetRight();
            bottom = cutout.getSafeInsetBottom();
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            int[] positions = {RoundedCorner.POSITION_TOP_LEFT, RoundedCorner.POSITION_TOP_RIGHT,
                    RoundedCorner.POSITION_BOTTOM_RIGHT, RoundedCorner.POSITION_BOTTOM_LEFT};
            for (int position : positions) {
                RoundedCorner corner = insets.getRoundedCorner(position);
                if (corner == null) {
                    continue;
                }
                // A box whose corner stands this far in along both edges clears the arc.
                int clear = (int) Math.ceil(corner.getRadius() * (1.0 - Math.sqrt(0.5)));
                boolean atLeft = position == RoundedCorner.POSITION_TOP_LEFT
                        || position == RoundedCorner.POSITION_BOTTOM_LEFT;
                boolean atTop = position == RoundedCorner.POSITION_TOP_LEFT
                        || position == RoundedCorner.POSITION_TOP_RIGHT;
                if (atLeft) {
                    left = Math.max(left, clear);
                } else {
                    right = Math.max(right, clear);
                }
                if (atTop) {
                    top = Math.max(top, clear);
                } else {
                    bottom = Math.max(bottom, clear);
                }
            }
        }
        return (left & 0xFFFFL) | (top & 0xFFFFL) << 16 | (right & 0xFFFFL) << 32
                | (bottom & 0xFFFFL) << 48;
    }

    @Override
    protected void onResume() {
        super.onResume();
        hideSystemUI();
    }

    @Override
    public boolean dispatchTouchEvent(MotionEvent event) {
        captureTouchContacts(event);
        return super.dispatchTouchEvent(event);
    }

    @Override
    protected void onPause() {
        touchContacts.cancelAll();
        super.onPause();
    }

    @Override
    public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        if (hasFocus) {
            hideSystemUI();
        } else {
            touchContacts.cancelAll();
        }
    }

    @Override
    protected void onDestroy() {
        touchContacts.cancelAll();
        super.onDestroy();
    }

    /**
     * Enforce sticky immersive fullscreen hiding the navigation bar and status bar.
     */
    protected void hideSystemUI() {
        Window window = getWindow();
        if (window == null) {
            return;
        }

        // PhoneWindow may not have installed its decor yet while SDLActivity is finishing
        // onCreate. Window#getInsetsController dereferences that absent decor on API 35.
        // Obtaining the decor first creates it when necessary, and its controller is only
        // available once the view is attached.
        View decor = window.getDecorView();
        if (decor == null) {
            return;
        }

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            // Hidden bars still inset a decor that fits them; below API 35 that strip shows the theme's background.
            window.setDecorFitsSystemWindows(false);
            WindowInsetsController controller = decor.getWindowInsetsController();
            if (controller != null) {
                controller.hide(WindowInsets.Type.statusBars() | WindowInsets.Type.navigationBars());
                controller.setSystemBarsBehavior(
                        WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE);
            }
        } else {
            decor.setSystemUiVisibility(
                    View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                            | View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                            | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
                            | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                            | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                            | View.SYSTEM_UI_FLAG_FULLSCREEN);
        }
    }

    /**
     * Terminate the Android task and activity cleanly from native code or UI.
     */
    public void finishApp(String unused) {
        runOnUiThread(this::finishAndRemoveTask);
    }

    private void captureTouchContacts(MotionEvent event) {
        switch (event.getActionMasked()) {
            case MotionEvent.ACTION_DOWN:
            case MotionEvent.ACTION_POINTER_DOWN:
                captureDown(event, event.getActionIndex());
                break;
            case MotionEvent.ACTION_MOVE:
                for (int index = 0; index < event.getPointerCount(); ++index) {
                    touchContacts.update(
                            event.getPointerId(index), event.getX(index), event.getY(index),
                            event.getPressure(index));
                }
                break;
            case MotionEvent.ACTION_UP:
            case MotionEvent.ACTION_POINTER_UP:
                captureUp(event, event.getActionIndex());
                break;
            case MotionEvent.ACTION_CANCEL:
                touchContacts.cancelAll();
                break;
            default:
                break;
        }
    }

    private void captureDown(MotionEvent event, int index) {
        touchContacts.down(event.getPointerId(index), event.getX(index), event.getY(index),
                event.getPressure(index));
    }

    private void captureUp(MotionEvent event, int index) {
        touchContacts.up(event.getPointerId(index), event.getX(index), event.getY(index),
                event.getPressure(index));
    }
}
