package com.osrstracker.plugin;

import net.runelite.client.config.Config;
import net.runelite.client.config.ConfigGroup;
import net.runelite.client.config.ConfigItem;
import net.runelite.client.config.ConfigSection;

/**
 * Plugin settings (plan step 12a task 2).
 *
 * <p>§11.1/§11.5: the app binds to a private address and there is no public deployment story, so
 * the default URL is loopback. A user who points this at a public host has left the design's
 * threat model behind.
 */
@ConfigGroup(TrackerConfig.GROUP)
public interface TrackerConfig extends Config
{
	String GROUP = "osrstracker";

	@ConfigSection(
		name = "Connection",
		description = "Where the tracker runs, and the token it expects.",
		position = 0
	)
	String connectionSection = "connection";

	@ConfigSection(
		name = "Collection",
		description = "What the plugin observes and when it sends it.",
		position = 1
	)
	String collectionSection = "collection";

	@ConfigItem(
		keyName = "serverUrl",
		name = "Server URL",
		description = "Base URL of the tracker, e.g. http://127.0.0.1:8502",
		section = connectionSection,
		position = 0
	)
	default String serverUrl()
	{
		return "http://127.0.0.1:8502";
	}

	@ConfigItem(
		keyName = "apiToken",
		name = "API token",
		description = "Bearer token from config.yaml. Stored by RuneLite in your profile.",
		section = connectionSection,
		position = 1,
		secret = true
	)
	default String apiToken()
	{
		return "";
	}

	@ConfigItem(
		keyName = "syncOnLogin",
		name = "Sync on login",
		description = "Send a snapshot shortly after the game world loads.",
		section = collectionSection,
		position = 0
	)
	default boolean syncOnLogin()
	{
		return true;
	}

	@ConfigItem(
		keyName = "practiceDetection",
		name = "Practice detection",
		description =
			"Summarize PvP sessions as practice evidence (§7.6). Never transmits opponents, "
				+ "chat, prayers, inventories or locations. Step 12c implements the detector.",
		section = collectionSection,
		position = 1
	)
	default boolean practiceDetection()
	{
		return true;
	}
}
