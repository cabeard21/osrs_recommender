package com.osrstracker.plugin.collect;

/**
 * When the automatic login sync fires — a few ticks after {@code LOGGED_IN}, not on it.
 *
 * <p><b>Why this class exists.</b> Syncing on the {@code LOGGED_IN} edge looks right and is
 * wrong. {@link ContainerObserver} can only learn a container from {@code ItemContainerChanged}
 * (docs/CONTRACT_RECONCILIATION.md ruling 4 — the direct lookups return null in 1.12.35), and the
 * client fires those events for inventory and equipment a few ticks <em>after</em> the state
 * change. A snapshot built on the edge therefore carries no container evidence at all, every
 * time. That is not a hypothetical: the app's own database held 215 bank items from a later
 * manual sync and not one inventory or equipment row, across three accepted syncs.
 *
 * <p>The cost of getting this wrong is quiet rather than loud, which is what makes it worth a
 * class of its own. A missing scan is honest under §6.5 — the app reads {@code unknown} — so
 * nothing errors. Every {@code item:} leaf simply stays unresolved forever, and the
 * recommendations degrade from "do this" to "sync this" with no failure anywhere to explain it.
 *
 * <p>Kept free of RuneLite types so it can be tested for what it actually is: a small piece of
 * timing logic. The plugin owns the events and the config; this owns the counting.
 */
public final class LoginSyncTrigger
{
	/**
	 * Ticks to wait. A tick is 600ms, so this is about three seconds.
	 *
	 * <p>Chosen high rather than tight. Waiting too long costs a few seconds on a sync that
	 * happens once per login; waiting too little costs the container evidence silently, and the
	 * arrival time of the login container events is a client-internal detail with no contract
	 * behind it. Where the failure is silent, the margin belongs on the safe side.
	 */
	private static final int DEFAULT_DELAY_TICKS = 5;

	private final int delayTicks;

	/** Ticks left before firing; {@code -1} when nothing is pending. */
	private int remaining = -1;

	/** §12's once-per-session rule, which a login burst would otherwise breach. */
	private boolean firedThisSession;

	public LoginSyncTrigger()
	{
		this(DEFAULT_DELAY_TICKS);
	}

	LoginSyncTrigger(int delayTicks)
	{
		this.delayTicks = delayTicks;
	}

	/**
	 * The client reached {@code LOGGED_IN}.
	 *
	 * <p>Idempotent within a session: the state can be re-entered several times during a single
	 * arrival, and each re-entry must not queue another sync or push the pending one further out.
	 */
	public void onLogin()
	{
		if (firedThisSession || remaining >= 0)
		{
			return;
		}
		remaining = delayTicks;
	}

	/**
	 * One game tick has passed.
	 *
	 * @return true exactly once per login, on the tick the delay elapses.
	 */
	public boolean onTick()
	{
		if (remaining < 0)
		{
			return false;
		}
		if (remaining > 0)
		{
			remaining--;
			return false;
		}
		remaining = -1;
		firedThisSession = true;
		return true;
	}

	/**
	 * Back to the login screen.
	 *
	 * <p>Disarms as well as clearing the session flag. A pending countdown that survived the
	 * logout would fire against whichever account logged in next, and attribute one player's
	 * containers to another — the same cross-account leak {@link ContainerObserver#reset()}
	 * exists to prevent.
	 */
	public void reset()
	{
		remaining = -1;
		firedThisSession = false;
	}
}
