package com.osrstracker.spike;

import java.time.Instant;

/**
 * Evidence for the one question the app side cannot answer for itself: is a <em>complete</em>
 * bank scan detectable (§6.5, plan step 8.5 task 3)?
 *
 * <p>The bank item container is only populated once the bank interface has been opened, and it
 * keeps its contents after closing. So "the container is non-null" is not evidence of a scan —
 * a close event is. This records both edges and lets the reconciliation doc decide whether the
 * close edge is a trustworthy anchor.
 */
final class BankWatch
{
	private Instant openedAt;
	private Instant closedAt;

	void onOpened(Instant at)
	{
		openedAt = at;
	}

	void onClosed(Instant at)
	{
		closedAt = at;
	}

	boolean everOpened()
	{
		return openedAt != null;
	}

	Instant openedAt()
	{
		return openedAt;
	}

	Instant closedAt()
	{
		return closedAt;
	}
}
