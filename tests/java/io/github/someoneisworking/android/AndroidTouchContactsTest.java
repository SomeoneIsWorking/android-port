package io.github.someoneisworking.android;

import java.util.ArrayList;
import java.util.List;

public final class AndroidTouchContactsTest {
  private static final class Received {
    final int pointerId;
    final float x;
    final float y;
    final AndroidTouchContacts.Phase phase;

    Received(AndroidTouchContacts.Contact contact) {
      pointerId = contact.pointerId;
      x = contact.x;
      y = contact.y;
      phase = contact.phase;
    }
  }

  private static final class Recorder implements AndroidTouchContacts.Listener {
    final List<Received> contacts = new ArrayList<>();

    @Override
    public void onContact(AndroidTouchContacts.Contact contact) {
      contacts.add(new Received(contact));
    }
  }

  private static void check(boolean condition) {
    if (!condition) {
      throw new AssertionError();
    }
  }

  private static void checkEvent(Received event, int pointerId, float x, float y,
                                 AndroidTouchContacts.Phase phase) {
    check(event.pointerId == pointerId);
    check(event.x == x);
    check(event.y == y);
    check(event.phase == phase);
  }

  private static void preservesContactIdentityAndCancelsAllCaptures() {
    AndroidTouchContacts contacts = new AndroidTouchContacts();
    Recorder recorder = new Recorder();
    contacts.setListener(recorder);

    contacts.down(4, 12.0F, 18.0F, 0.5F);
    contacts.down(9, 50.0F, 80.0F, 1.0F);
    contacts.update(4, 14.0F, 20.0F, 0.7F);
    contacts.cancelAll();

    check(recorder.contacts.size() == 5);
    checkEvent(recorder.contacts.get(0), 4, 12.0F, 18.0F, AndroidTouchContacts.Phase.Down);
    checkEvent(recorder.contacts.get(1), 9, 50.0F, 80.0F, AndroidTouchContacts.Phase.Down);
    checkEvent(recorder.contacts.get(2), 4, 14.0F, 20.0F, AndroidTouchContacts.Phase.Move);
    checkEvent(recorder.contacts.get(3), 4, 14.0F, 20.0F, AndroidTouchContacts.Phase.Cancel);
    checkEvent(recorder.contacts.get(4), 9, 50.0F, 80.0F, AndroidTouchContacts.Phase.Cancel);

    contacts.update(4, 17.0F, 22.0F, 1.0F);
    contacts.up(9, 50.0F, 80.0F, 1.0F);
    check(recorder.contacts.size() == 5);
  }

  private static void listenerReplacementReleasesThePriorOwner() {
    AndroidTouchContacts contacts = new AndroidTouchContacts();
    Recorder previous = new Recorder();
    Recorder next = new Recorder();
    contacts.setListener(previous);
    contacts.down(3, 4.0F, 5.0F, 1.0F);
    contacts.setListener(next);
    contacts.down(3, 6.0F, 7.0F, 1.0F);
    contacts.up(3, 6.0F, 7.0F, 1.0F);

    check(previous.contacts.size() == 2);
    checkEvent(previous.contacts.get(1), 3, 4.0F, 5.0F, AndroidTouchContacts.Phase.Cancel);
    check(next.contacts.size() == 2);
    checkEvent(next.contacts.get(0), 3, 6.0F, 7.0F, AndroidTouchContacts.Phase.Down);
    checkEvent(next.contacts.get(1), 3, 6.0F, 7.0F, AndroidTouchContacts.Phase.Up);
  }

  public static void main(String[] args) {
    preservesContactIdentityAndCancelsAllCaptures();
    listenerReplacementReleasesThePriorOwner();
    System.out.println("Android touch contacts: 2/2 tests passed");
  }
}
