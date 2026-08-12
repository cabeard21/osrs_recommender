package com.osrstracker.plugin;

import com.google.gson.Gson;
import com.google.inject.Provides;
import com.osrstracker.plugin.collect.ContainerObserver;
import com.osrstracker.plugin.collect.SnapshotFactory;
import lombok.extern.slf4j.Slf4j;
import net.runelite.api.Client;
import net.runelite.api.GameState;
import net.runelite.api.events.GameStateChanged;
import net.runelite.api.events.ItemContainerChanged;
import net.runelite.api.events.WidgetClosed;
import net.runelite.api.gameval.InterfaceID;
import net.runelite.client.callback.ClientThread;
import net.runelite.client.config.ConfigManager;
import net.runelite.client.eventbus.Subscribe;
import net.runelite.client.plugins.Plugin;
import net.runelite.client.plugins.PluginDescriptor;
import net.runelite.client.ui.ClientToolbar;
import net.runelite.client.ui.NavigationButton;
import net.runelite.client.util.ImageUtil;
import okhttp3.OkHttpClient;

import javax.inject.Inject;
import java.awt.image.BufferedImage;
import java.time.Instant;
import java.util.concurrent.ScheduledExecutorService;

/**
 * The OSRS PvP progression tracker's RuneLite companion (SDD §12, §13).
 *
 * <p><b>Step 12a is the skeleton and the seam.</b> It builds a snapshot carrying only account
 * identity — username, display name, combat level, quest points — and sends it. Step 12b adds
 * the collectors that fill skills, quests, unlocks and containers; Step 12c adds the practice
 * detector. Sending an identity-only snapshot is honest under §6.5: a section the plugin has not
 * collected is <em>absent</em>, never an empty array claiming "observed, nothing there".
 */
@Slf4j
@PluginDescriptor(
	name = "OSRS Tracker",
	description = "Syncs account facts to your local PvP progression tracker.",
	tags = {"osrs", "pvp", "wilderness", "tracker", "progression"}
)
public class TrackerPlugin extends Plugin
{
	@Inject
	private Client client;

	@Inject
	private ClientThread clientThread;

	@Inject
	private ClientToolbar clientToolbar;

	@Inject
	private ScheduledExecutorService executor;

	@Inject
	private OkHttpClient okHttpClient;

	@Inject
	private Gson gson;

	@Inject
	private TrackerConfig config;

	private TrackerPanel panel;
	private NavigationButton navButton;
	private TrackerSyncClient syncClient;

	/** Session evidence for §6.5. Written by events, read when a snapshot is built. */
	private final ContainerObserver containers = new ContainerObserver();

	/** Guards against a login burst queueing several syncs for the same arrival. */
	private volatile boolean syncedThisSession;

	@Provides
	TrackerConfig provideConfig(ConfigManager configManager)
	{
		return configManager.getConfig(TrackerConfig.class);
	}

	@Override
	protected void startUp()
	{
		panel = new TrackerPanel(this::syncNow);
		syncClient = new HttpTrackerSyncClient(okHttpClient, gson, config, panel::update);

		final BufferedImage icon = ImageUtil.loadImageResource(TrackerPlugin.class, "/tracker_icon.png");
		navButton = NavigationButton.builder()
			.tooltip("OSRS Tracker")
			.icon(icon)
			.priority(7)
			.panel(panel)
			.build();
		clientToolbar.addNavigation(navButton);
	}

	@Override
	protected void shutDown()
	{
		clientToolbar.removeNavigation(navButton);
		panel = null;
		syncClient = null;
		syncedThisSession = false;
	}

	@Subscribe
	public void onGameStateChanged(GameStateChanged event)
	{
		if (event.getGameState() == GameState.LOGIN_SCREEN)
		{
			syncedThisSession = false;
			// A different account may be about to log in, and container evidence is per-session
			// (§6.5). Carrying it across would attribute one account's bank to another's.
			containers.reset();
			return;
		}
		if (event.getGameState() != GameState.LOGGED_IN || syncedThisSession || !config.syncOnLogin())
		{
			return;
		}
		syncedThisSession = true;
		syncNow();
	}

	/**
	 * The only working source of container contents in 1.12.35 — the direct lookups return null.
	 * Fires on change, so silence means "not observed", never "empty"
	 * (docs/CONTRACT_RECONCILIATION.md).
	 */
	@Subscribe
	public void onItemContainerChanged(ItemContainerChanged event)
	{
		containers.onContainerChanged(event.getContainerId(), event.getItemContainer(), Instant.now());
	}

	/**
	 * A closed bank interface is a sighting of the <em>whole</em> bank, which is the only way an
	 * empty bank can be told apart from one nobody has opened (§6.5, plan step 12b task 2).
	 */
	@Subscribe
	public void onWidgetClosed(WidgetClosed event)
	{
		if (event.getGroupId() == InterfaceID.BANKMAIN)
		{
			containers.onBankClosed(Instant.now());
		}
	}

	/**
	 * Build on the client thread, send off it.
	 *
	 * <p>Both halves matter. Reading {@code getLocalPlayer()} off the client thread races the
	 * game loop, and blocking the client thread on an HTTP call with retries would freeze the
	 * game for as long as the tracker is down — turning "my tracker is off" into "my client
	 * stutters", which is how a companion plugin gets uninstalled.
	 */
	private void syncNow()
	{
		clientThread.invoke(() -> {
			final AccountSnapshot snapshot = SnapshotFactory.build(client, containers, Instant.now());
			if (snapshot == null)
			{
				panel.update(SyncStatus.notConfigured("Log in first — there is no account to sync."));
				return;
			}
			executor.execute(() -> syncClient.submit(snapshot));
		});
	}

}
