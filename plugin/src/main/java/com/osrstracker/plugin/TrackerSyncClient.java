package com.osrstracker.plugin;

/**
 * §13.2's narrow seam, verbatim:
 *
 * <pre>interface TrackerSyncClient { void submit(AccountSnapshot snapshot); }</pre>
 *
 * <p>How the plugin is <em>distributed</em> must not influence snapshot construction,
 * serialization, authentication, versioning or app-side ingestion. If a future Plugin Hub
 * submission would require changing any of those, the boundary has eroded — which is exactly
 * what this one-method interface exists to make visible.
 */
public interface TrackerSyncClient
{
	/**
	 * Send one snapshot. Never throws: a transport failure is a {@link SyncStatus} the user can
	 * see, not an exception thrown into a game-thread event handler.
	 */
	void submit(AccountSnapshot snapshot);
}
