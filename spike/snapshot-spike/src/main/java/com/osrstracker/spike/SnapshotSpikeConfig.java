package com.osrstracker.spike;

import net.runelite.client.config.Config;
import net.runelite.client.config.ConfigGroup;
import net.runelite.client.config.ConfigItem;
import net.runelite.client.config.Keybind;

import java.awt.event.KeyEvent;

/**
 * Step 8.5 spike config. One knob: the capture hotkey. No server URL, no token — the spike
 * writes to disk and never speaks HTTP (plan step 8.5 task 1).
 */
@ConfigGroup(SnapshotSpikeConfig.GROUP)
public interface SnapshotSpikeConfig extends Config
{
	String GROUP = "osrstrackerspike";

	@ConfigItem(
		keyName = "captureHotkey",
		name = "Capture snapshot",
		description = "Writes one snapshot to ~/snapshot.json."
	)
	default Keybind captureHotkey()
	{
		return new Keybind(KeyEvent.VK_S, KeyEvent.CTRL_DOWN_MASK | KeyEvent.SHIFT_DOWN_MASK);
	}
}
