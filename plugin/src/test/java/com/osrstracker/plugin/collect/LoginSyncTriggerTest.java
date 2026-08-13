package com.osrstracker.plugin.collect;

import org.junit.Test;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;

/**
 * The login sync must arrive late enough to carry container evidence, exactly once, and never
 * across an account boundary.
 *
 * <p>These are timing rules, and the failure they guard against is silent: a sync that fires too
 * early still succeeds, still gets accepted, and simply carries no inventory or equipment. The
 * tests therefore assert on the tick the fire happens rather than on whether one eventually does.
 */
public class LoginSyncTriggerTest
{
	/** A short delay, so a test reads as "three ticks" rather than as a countdown transcript. */
	private static final int DELAY = 3;

	private final LoginSyncTrigger trigger = new LoginSyncTrigger(DELAY);

	/** @return the 1-based tick on which the trigger fired, or -1 within {@code limit} ticks. */
	private int tickUntilFired(int limit)
	{
		for (int tick = 1; tick <= limit; tick++)
		{
			if (trigger.onTick())
			{
				return tick;
			}
		}
		return -1;
	}

	@Test
	public void doesNotFireOnTheLoginEdgeItself()
	{
		trigger.onLogin();

		// The whole point: at this instant ItemContainerChanged has not run for inventory or
		// equipment, so a snapshot built here carries no container scans.
		assertFalse(trigger.onTick());
	}

	@Test
	public void firesOnceTheDelayHasElapsed()
	{
		trigger.onLogin();

		assertEquals("the sync fires on the tick after the delay elapses",
			DELAY + 1, tickUntilFired(DELAY + 5));
	}

	@Test
	public void firesOnlyOncePerSession()
	{
		trigger.onLogin();
		tickUntilFired(DELAY + 5);

		trigger.onLogin();

		assertFalse("a second login within one session must not queue another sync",
			tickUntilFired(DELAY + 5) > 0);
	}

	@Test
	public void reEnteringLoggedInDoesNotPushTheSyncFurtherOut()
	{
		trigger.onLogin();
		trigger.onTick();

		// GameStateChanged can deliver LOGGED_IN more than once for a single arrival. Re-arming on
		// each would let a chatty login defer the sync indefinitely.
		trigger.onLogin();

		assertEquals("re-arming would let a chatty login defer the sync indefinitely",
			DELAY, tickUntilFired(DELAY + 5));
	}

	@Test
	public void aPendingSyncIsDisarmedByLoggingOut()
	{
		trigger.onLogin();
		trigger.onTick();

		trigger.reset();

		assertFalse("a countdown surviving logout would sync whichever account logged in next",
			tickUntilFired(DELAY + 5) > 0);
	}

	@Test
	public void theNextAccountGetsItsOwnSync()
	{
		trigger.onLogin();
		tickUntilFired(DELAY + 5);

		trigger.reset();
		trigger.onLogin();

		assertEquals("a fresh login is a fresh session, not a spent one",
			DELAY + 1, tickUntilFired(DELAY + 5));
	}
}
