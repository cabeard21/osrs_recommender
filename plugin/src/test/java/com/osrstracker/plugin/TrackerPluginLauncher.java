package com.osrstracker.plugin;

import net.runelite.client.RuneLite;
import net.runelite.client.externalplugins.ExternalPluginManager;

/**
 * Runs RuneLite in developer mode with the tracker loaded — {@code ./gradlew runClient}.
 *
 * <p>Lives in the test source set because it depends on the client at runtime, which the plugin
 * itself must not. Note this is the <em>only</em> way to run from source: a launcher-started
 * client computes {@code developerMode = has("developer-mode") && launcherVersion == null}, so it
 * can never side-load. Jagex-account logins go through the credentials route documented in
 * {@code docs/PLUGIN_SIDELOAD.md}.
 */
public class TrackerPluginLauncher
{
	public static void main(String[] args) throws Exception
	{
		ExternalPluginManager.loadBuiltin(TrackerPlugin.class);
		RuneLite.main(args);
	}
}
