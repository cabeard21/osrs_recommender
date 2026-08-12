package com.osrstracker.spike;

import net.runelite.client.RuneLite;
import net.runelite.client.externalplugins.ExternalPluginManager;

/**
 * Launches RuneLite in developer mode with the spike loaded. Lives in the test source set
 * because it depends on the client at runtime, which the plugin itself must not.
 *
 * <p>This is the Step 8.5 run path — no jar is copied into
 * {@code ~/.runelite/sideloaded-plugins}. Real side-loading is Step 12's human gate.
 */
public class SnapshotSpikeLauncher
{
	public static void main(String[] args) throws Exception
	{
		ExternalPluginManager.loadBuiltin(SnapshotSpikePlugin.class);
		RuneLite.main(args);
	}
}
