package com.osrstracker.plugin;

import net.runelite.client.config.Config;
import net.runelite.client.config.ConfigGroup;
import net.runelite.client.config.ConfigItem;
import net.runelite.client.config.ConfigSection;
import net.runelite.client.config.Range;
import java.awt.Color;

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

	@ConfigSection(name = "Enhanced Status Bars", description = "Optional inventory-adjacent HP and Prayer bars.", position = 2)
	String enhancedBarsSection = "enhancedBars";
	@ConfigSection(name = "Hitpoints Scaling", description = "Automatic activity maximums and manual fallback.", position = 3)
	String hpScalingSection = "hpScaling";
	@ConfigSection(name = "Eating Thresholds", description = "Full nominal healing efficiency, not combat eating advice.", position = 4)
	String eatingSection = "eatingThresholds";
	@ConfigSection(name = "HP Diagnostics", description = "Local finite state snapshots; nothing is sent to the backend.", position = 5)
	String diagnosticsSection = "hpDiagnostics";

	@ConfigItem(keyName = "enhancedBarsEnabled", name = "Enable enhanced bars", description = "Disable built-in Status Bars before enabling.", section = enhancedBarsSection, position = 0)
	default boolean enhancedBarsEnabled()
	{
		return false;
	}

	@ConfigItem(keyName = "statusBarsCounters", name = "Show counters", description = "Show actual current HP and Prayer.", section = enhancedBarsSection, position = 1)
	default boolean statusBarsCounters()
	{
		return true;
	}

	@ConfigItem(keyName = "statusBarsIcons", name = "Show icons", description = "Show HP and Prayer icons.", section = enhancedBarsSection, position = 2)
	default boolean statusBarsIcons()
	{
		return true;
	}

	@ConfigItem(keyName = "automaticHpScaling", name = "Automatic scaling", description = "Recognized LMS and Pete Penultimate/Ultimate fights take precedence over manual maximum.", section = hpScalingSection, position = 3)
	default boolean automaticHpScaling()
	{
		return true;
	}

	@ConfigItem(keyName = "manualHpMaximumEnabled", name = "Manual maximum enabled", description = "Fallback maximum for unrecognized activities. Disable automatic scaling to force this value.", section = hpScalingSection, position = 4)
	default boolean manualHpMaximumEnabled()
	{
		return false;
	}

	@Range(min = 1, max = 255)
	@ConfigItem(keyName = "manualHpMaximum", name = "Manual maximum HP", description = "Maximum HP for manual scaling.", section = hpScalingSection, position = 5)
	default int manualHpMaximum()
	{
		return 99;
	}

	@ConfigItem(keyName = "eatingThresholdsEnabled", name = "Enable eating thresholds", description = "Markers show missing HP needed for full nominal healing.", section = eatingSection, position = 6)
	default boolean eatingThresholdsEnabled()
	{
		return true;
	}

	@ConfigItem(keyName = "sharkThresholdEnabled", name = "Show Shark threshold", description = "Example single-eat preset.", section = eatingSection, position = 7)
	default boolean sharkThresholdEnabled()
	{
		return true;
	}

	@Range(min = 1, max = 255)
	@ConfigItem(keyName = "sharkHealing", name = "Shark healing", description = "Nominal healing; customize for your food and mode.", section = eatingSection, position = 8)
	default int sharkHealing()
	{
		return 20;
	}

	@ConfigItem(keyName = "sharkMarkerColor", name = "Shark color", description = "Color of the single-eat marker.", section = eatingSection, position = 9)
	default Color sharkMarkerColor()
	{
		return Color.YELLOW;
	}

	@ConfigItem(keyName = "doubleEatThresholdEnabled", name = "Show double-eat threshold", description = "Example double-eat preset; no consumables are assumed.", section = eatingSection, position = 10)
	default boolean doubleEatThresholdEnabled()
	{
		return true;
	}

	@Range(min = 1, max = 255)
	@ConfigItem(keyName = "doubleEatHealing", name = "Double-eat healing", description = "Total nominal healing of your combination.", section = eatingSection, position = 11)
	default int doubleEatHealing()
	{
		return 35;
	}

	@ConfigItem(keyName = "doubleEatMarkerColor", name = "Double-eat color", description = "Color of the double-eat marker.", section = eatingSection, position = 12)
	default Color doubleEatMarkerColor()
	{
		return Color.CYAN;
	}

	@ConfigItem(keyName = "tripleEatThresholdEnabled", name = "Show triple-eat threshold", description = "Example triple-eat preset; no consumables are assumed.", section = eatingSection, position = 13)
	default boolean tripleEatThresholdEnabled()
	{
		return true;
	}

	@Range(min = 1, max = 255)
	@ConfigItem(keyName = "tripleEatHealing", name = "Triple-eat healing", description = "Total nominal healing of your combination.", section = eatingSection, position = 14)
	default int tripleEatHealing()
	{
		return 56;
	}

	@ConfigItem(keyName = "tripleEatMarkerColor", name = "Triple-eat color", description = "Color of the triple-eat marker.", section = eatingSection, position = 15)
	default Color tripleEatMarkerColor()
	{
		return new Color(180, 80, 255);
	}

	@ConfigItem(keyName = "hpScalingDiagnostics", name = "Enable local diagnostics", description = "Log scaling state changes locally; no continuous HP or backend telemetry.", section = diagnosticsSection, position = 16)
	default boolean hpScalingDiagnostics()
	{
		return false;
	}
}
