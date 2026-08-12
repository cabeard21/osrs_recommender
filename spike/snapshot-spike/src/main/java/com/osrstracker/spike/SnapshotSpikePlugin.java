package com.osrstracker.spike;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.JsonObject;
import com.google.inject.Provides;
import lombok.extern.slf4j.Slf4j;
import net.runelite.api.ChatMessageType;
import net.runelite.api.Client;
import net.runelite.api.GameState;
import net.runelite.api.events.ItemContainerChanged;
import net.runelite.api.events.WidgetClosed;
import net.runelite.api.events.WidgetLoaded;
import net.runelite.api.gameval.InterfaceID;
import net.runelite.client.callback.ClientThread;
import net.runelite.client.config.ConfigManager;
import net.runelite.client.eventbus.Subscribe;
import net.runelite.client.input.KeyManager;
import net.runelite.client.plugins.Plugin;
import net.runelite.client.plugins.PluginDescriptor;
import net.runelite.client.util.HotkeyListener;

import javax.inject.Inject;
import java.io.IOException;
import java.io.Writer;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.time.Instant;

/**
 * Plan step 8.5, the whole of it: press a hotkey, write one real snapshot to disk, so the
 * provisional {@code contracts/sync_payload.schema.json} can be reconciled against something
 * RuneLite actually produces rather than against a guess.
 *
 * <p><b>This code is throwaway.</b> No auth, no HTTP, no practice detection, no retry — Step 12a
 * builds the real plugin in {@code plugin/} against the frozen contract, and this whole
 * {@code spike/} tree is deleted when the reconciliation doc lands.
 */
@Slf4j
@PluginDescriptor(
	name = "OSRS Tracker snapshot spike",
	description = "Throwaway: dumps one account snapshot to ~/snapshot.json for contract reconciliation.",
	tags = {"osrs", "tracker", "spike"},
	developerPlugin = true
)
public class SnapshotSpikePlugin extends Plugin
{
	private static final Path OUTPUT = Paths.get(System.getProperty("user.home"), "snapshot.json");

	@Inject
	private Client client;

	@Inject
	private ClientThread clientThread;

	@Inject
	private KeyManager keyManager;

	@Inject
	private SnapshotSpikeConfig config;

	private final BankWatch bankWatch = new BankWatch();
	private final ContainerCache containers = new ContainerCache();
	private final Gson gson = new GsonBuilder().setPrettyPrinting().serializeNulls().create();

	private final HotkeyListener captureHotkey = new HotkeyListener(() -> config.captureHotkey())
	{
		@Override
		public void hotkeyPressed()
		{
			// Every varbit read and Quest#getState must happen on the client thread.
			clientThread.invoke(SnapshotSpikePlugin.this::capture);
		}
	};

	@Provides
	SnapshotSpikeConfig provideConfig(ConfigManager configManager)
	{
		return configManager.getConfig(SnapshotSpikeConfig.class);
	}

	@Override
	protected void startUp()
	{
		keyManager.registerKeyListener(captureHotkey);
		log.info("snapshot spike ready; press the capture hotkey to write {}", OUTPUT);
	}

	@Override
	protected void shutDown()
	{
		keyManager.unregisterKeyListener(captureHotkey);
	}

	/**
	 * The only reliable source of container contents in 1.12.35 — see {@link ContainerCache} for
	 * what the direct lookups returned. Fires on login for inventory and equipment, and on bank
	 * open, so a session that logs in and opens the bank has all three.
	 */
	@Subscribe
	public void onItemContainerChanged(ItemContainerChanged event)
	{
		containers.record(event.getContainerId(), event.getItemContainer(), Instant.now());
	}

	@Subscribe
	public void onWidgetLoaded(WidgetLoaded event)
	{
		if (event.getGroupId() == InterfaceID.BANKMAIN)
		{
			bankWatch.onOpened(Instant.now());
		}
	}

	@Subscribe
	public void onWidgetClosed(WidgetClosed event)
	{
		if (event.getGroupId() == InterfaceID.BANKMAIN)
		{
			bankWatch.onClosed(Instant.now());
		}
	}

	private void capture()
	{
		if (client.getGameState() != GameState.LOGGED_IN)
		{
			message("Snapshot spike: log in first — nothing was written.");
			return;
		}

		final JsonObject snapshot;
		try
		{
			snapshot = SnapshotBuilder.build(client, bankWatch, containers);
		}
		catch (RuntimeException e)
		{
			// Never fail silently: a spike that writes half a snapshot and says nothing produces
			// a reconciliation doc built on a lie.
			log.error("snapshot build failed", e);
			message("Snapshot spike: build FAILED — see the client log.");
			return;
		}

		try (Writer writer = Files.newBufferedWriter(OUTPUT, StandardCharsets.UTF_8))
		{
			gson.toJson(snapshot, writer);
		}
		catch (IOException e)
		{
			log.error("snapshot write failed", e);
			message("Snapshot spike: write FAILED — " + e.getMessage());
			return;
		}

		message("Snapshot spike: wrote " + OUTPUT + " — bank scan emitted: " + bankWatch.everOpened());
		log.info("wrote snapshot to {}", OUTPUT);
	}

	private void message(String text)
	{
		client.addChatMessage(ChatMessageType.GAMEMESSAGE, "", text, null);
	}
}
