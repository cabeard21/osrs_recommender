package com.osrstracker.plugin;

import java.time.Instant;

/**
 * The outcome of the last sync attempt, as the sidebar shows it.
 *
 * <p>Step 12a task 3 requires failures to surface in the sidebar and <b>never silently</b>. This
 * type is how: every terminal outcome produces one of these, so a failure has somewhere to go
 * that is not a swallowed exception or a log line nobody opens.
 */
public final class SyncStatus
{
	public enum State
	{
		IDLE,
		SENDING,
		OK,
		/** The server answered, and said no — 401, 409, 422. Retrying will not help. */
		REJECTED,
		/** The server could not be reached, or answered 5xx. Retried with backoff first. */
		UNREACHABLE,
		/** The plugin refused to send: no token, no URL, no username. */
		NOT_CONFIGURED
	}

	private final State state;
	private final String detail;
	private final Instant at;

	private SyncStatus(State state, String detail, Instant at)
	{
		this.state = state;
		this.detail = detail;
		this.at = at;
	}

	public static SyncStatus idle()
	{
		return new SyncStatus(State.IDLE, "No sync attempted yet.", null);
	}

	public static SyncStatus sending(Instant at)
	{
		return new SyncStatus(State.SENDING, "Sending…", at);
	}

	public static SyncStatus ok(Instant at)
	{
		return new SyncStatus(State.OK, "Accepted.", at);
	}

	public static SyncStatus rejected(int code, String detail, Instant at)
	{
		return new SyncStatus(State.REJECTED, "Rejected (HTTP " + code + "): " + detail, at);
	}

	public static SyncStatus unreachable(String detail, Instant at)
	{
		return new SyncStatus(State.UNREACHABLE, "Could not reach the tracker: " + detail, at);
	}

	public static SyncStatus notConfigured(String detail)
	{
		return new SyncStatus(State.NOT_CONFIGURED, detail, null);
	}

	public State state()
	{
		return state;
	}

	public String detail()
	{
		return detail;
	}

	public Instant at()
	{
		return at;
	}

	public boolean isFailure()
	{
		return state == State.REJECTED || state == State.UNREACHABLE || state == State.NOT_CONFIGURED;
	}
}
