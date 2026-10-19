package com.osrstracker.plugin;

import com.google.gson.Gson;
import com.osrstracker.plugin.statusbars.EnhancedStatusBarsOverlay;
import com.osrstracker.plugin.statusbars.HpScalingDiagnostics;
import net.runelite.client.events.ConfigChanged;
import net.runelite.client.events.ProfileChanged;
import net.runelite.client.events.PluginChanged;
import net.runelite.client.plugins.PluginManager;
import net.runelite.client.plugins.statusbars.StatusBarsPlugin;
import net.runelite.client.ui.overlay.OverlayManager;
import com.google.inject.Provides;
import com.osrstracker.plugin.collect.ContainerObserver;
import com.osrstracker.plugin.collect.LoginSyncTrigger;
import com.osrstracker.plugin.collect.SnapshotFactory;
import lombok.extern.slf4j.Slf4j;
import net.runelite.api.Client;
import net.runelite.api.GameState;
import net.runelite.api.events.GameStateChanged;
import net.runelite.api.events.GameTick;
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
 * the collectors that fill skills, quests, unlocks and containers. Sending an identity-only snapshot is honest under §6.5: a section the plugin has not
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

	@Inject
	private OverlayManager overlayManager;
	@Inject
	private PluginManager pluginManager;
	@Inject
	private EnhancedStatusBarsOverlay enhancedStatusBarsOverlay;
	@Inject
	private HpScalingDiagnostics hpScalingDiagnostics;

	private final Object enhancedBarsLock = new Object();
	private boolean enhancedBarsRegistered;
	private volatile boolean active;
	private volatile long lifecycleGeneration;
	private TrackerPanel panel;
	private NavigationButton navButton;
	private TrackerSyncClient syncClient;

	/** Session evidence for §6.5. Written by events, read when a snapshot is built. */
	private final ContainerObserver containers = new ContainerObserver();

	/**
	 * When the login sync fires, and the guard against a login burst queueing several for one
	 * arrival. Deliberately not the {@code LOGGED_IN} edge — see {@link LoginSyncTrigger}.
	 */
	private final LoginSyncTrigger loginSync = new LoginSyncTrigger();

	@Provides
	TrackerConfig provideConfig(ConfigManager configManager)
	{
		return configManager.getConfig(TrackerConfig.class);
	}

	@Override
	protected void startUp()
	{
		synchronized (enhancedBarsLock)
		{
			active = true;
			lifecycleGeneration++;
		}
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
		queueEnhancedBarsReconcile();
	}

	@Override
	protected void shutDown()
	{
		synchronized (enhancedBarsLock)
		{
			active = false;
			lifecycleGeneration++;
			overlayManager.remove(enhancedStatusBarsOverlay);
			enhancedBarsRegistered = false;
			hpScalingDiagnostics.reset();
		}
		clientToolbar.removeNavigation(navButton);
		panel = null;
		syncClient = null;
		loginSync.reset();
	}

	@Subscribe
	public void onGameStateChanged(GameStateChanged event)
	{
		tickHpDiagnostics();
		if (event.getGameState() == GameState.LOGIN_SCREEN)
		{
			// A different account may be about to log in, and container evidence is per-session
			// (§6.5). Carrying it across would attribute one account's bank to another's — and
			// the same argument applies to a pending login sync.
			loginSync.reset();
			containers.reset();
			return;
		}
		if (event.getGameState() != GameState.LOGGED_IN || !config.syncOnLogin())
		{
			return;
		}
		// Armed, not sent. The containers this snapshot exists to carry have not been announced
		// yet — see LoginSyncTrigger for why that is a silent failure rather than a loud one.
		loginSync.onLogin();
	}

	/** Drives {@link LoginSyncTrigger}'s countdown; fires the armed login sync when it elapses. */
	@Subscribe
	public void onGameTick(GameTick event)
	{
		tickHpDiagnostics();
		if (loginSync.onTick())
		{
			syncNow();
		}
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

	@Subscribe
	public void onConfigChanged(ConfigChanged event)
	{
		if (TrackerConfig.GROUP.equals(event.getGroup()))
		{
			queueEnhancedBarsReconcile();
		}
	}

	@Subscribe
	public void onProfileChanged(ProfileChanged event)
	{
		queueEnhancedBarsReconcile();
	}

	@Subscribe
	public void onPluginChanged(PluginChanged event)
	{
		queueEnhancedBarsReconcile();
	}

	private void queueEnhancedBarsReconcile()
	{
		final long generation = lifecycleGeneration;
		clientThread.invokeLater(() -> {
			synchronized (enhancedBarsLock)
			{
				if (active && lifecycleGeneration == generation)
				{
					reconcileEnhancedBars();
					hpScalingDiagnostics.tick();
				}
			}
		});
	}

	/** Runs on the client thread; registration is independent of account synchronization. */
	void reconcileEnhancedBars()
	{
		synchronized (enhancedBarsLock)
		{
			final boolean enabled = config.enhancedBarsEnabled();
			final boolean conflict = enabled && pluginManager.getPlugins().stream()
				.anyMatch(plugin -> plugin instanceof StatusBarsPlugin && pluginManager.isPluginActive(plugin));
			enhancedStatusBarsOverlay.setSuppressed(conflict);
			if (enabled && !enhancedBarsRegistered)
			{
				overlayManager.add(enhancedStatusBarsOverlay);
				enhancedBarsRegistered = true;
			}
			else if (!enabled && enhancedBarsRegistered)
			{
				overlayManager.remove(enhancedStatusBarsOverlay);
				enhancedBarsRegistered = false;
			}
			if (panel != null)
			{
				panel.updateBarsWarning(conflict);
			}
		}
	}
	private void tickHpDiagnostics()
	{
		synchronized (enhancedBarsLock)
		{
			if (active)
			{
				hpScalingDiagnostics.tick();
			}
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
			final Instant now = Instant.now();
			final AccountSnapshot snapshot = SnapshotFactory.build(client, containers, now);
			if (snapshot == null)
			{
				panel.update(SyncStatus.notConfigured("Log in first — there is no account to sync."));
				return;
			}
			executor.execute(() -> syncClient.submit(snapshot));
		});
	}

}
