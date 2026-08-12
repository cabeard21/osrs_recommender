package com.osrstracker.plugin;

import com.google.gson.Gson;
import com.google.inject.Provides;
import lombok.extern.slf4j.Slf4j;
import net.runelite.api.Client;
import net.runelite.api.GameState;
import net.runelite.api.Player;
import net.runelite.api.events.GameStateChanged;
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
			final AccountSnapshot snapshot = buildSnapshot();
			if (snapshot == null)
			{
				panel.update(SyncStatus.notConfigured("Log in first — there is no account to sync."));
				return;
			}
			executor.execute(() -> syncClient.submit(snapshot));
		});
	}

	/** @return null when there is no logged-in account to describe. */
	private AccountSnapshot buildSnapshot()
	{
		if (client.getGameState() != GameState.LOGGED_IN)
		{
			return null;
		}
		final Player local = client.getLocalPlayer();
		if (local == null || local.getName() == null)
		{
			return null;
		}

		// Step 12b replaces this with the collectors. Quest points read from the varp the
		// reconciliation confirmed; nothing else is claimed yet.
		return AccountSnapshot.builder(local.getName(), Instant.now())
			.displayName(local.getName())
			.combatLevel(local.getCombatLevel())
			.questPoints(client.getVarpValue(net.runelite.api.VarPlayer.QUEST_POINTS))
			.build();
	}
}
