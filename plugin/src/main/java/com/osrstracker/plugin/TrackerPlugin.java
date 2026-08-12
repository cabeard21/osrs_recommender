package com.osrstracker.plugin;

import com.google.gson.Gson;
import com.google.inject.Provides;
import com.osrstracker.plugin.collect.ContainerObserver;
import com.osrstracker.plugin.collect.SnapshotFactory;
import com.osrstracker.plugin.practice.PracticeDetector;
import com.osrstracker.plugin.practice.PracticeDetector.Arena;
import lombok.extern.slf4j.Slf4j;
import net.runelite.api.Actor;
import net.runelite.api.Client;
import net.runelite.api.GameState;
import net.runelite.api.Player;
import net.runelite.api.Varbits;
import net.runelite.api.events.GameStateChanged;
import net.runelite.api.events.HitsplatApplied;
import net.runelite.api.events.InteractingChanged;
import net.runelite.api.events.ItemContainerChanged;
import net.runelite.api.events.VarbitChanged;
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

	/** §7.6's policy. This class only feeds it signals; it decides what counts. */
	private final PracticeDetector practice = new PracticeDetector();

	/** Last known arena, so a varbit change can be read as entering or leaving. */
	private Arena arena = Arena.ELSEWHERE;

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
			// (§6.5). Carrying it across would attribute one account's bank to another's — and
			// the same argument applies to an unfinished fight.
			containers.reset();
			practice.reset();
			arena = Arena.ELSEWHERE;
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
	 * Arena tracking. Entering the Wilderness is fed to the detector as the rejected signal it
	 * is — §7.6 counts fighting, not walking north.
	 */
	@Subscribe
	public void onVarbitChanged(VarbitChanged event)
	{
		if (!config.practiceDetection())
		{
			return;
		}
		final Arena previous = arena;
		arena = currentArena();
		if (previous == arena)
		{
			return;
		}

		final Instant now = Instant.now();
		if (arena == Arena.LMS)
		{
			practice.lmsMatchStarted(now);
		}
		else if (previous == Arena.LMS)
		{
			practice.lmsMatchEnded(now);
		}
		if (arena == Arena.WILDERNESS)
		{
			practice.observeWildernessEntry(now);
		}
	}

	/**
	 * The local player attacked someone, or is engaged with them.
	 *
	 * <p><b>Best effort, deliberately.</b> Interaction is a coarse proxy for "attacked": it also
	 * fires for following. The precision that matters lives in the detector's threshold — two
	 * attacks or ten seconds — which is what stops a single misread interaction from refreshing
	 * anything.
	 */
	@Subscribe
	public void onInteractingChanged(InteractingChanged event)
	{
		if (!config.practiceDetection() || arena == Arena.ELSEWHERE)
		{
			return;
		}
		final Player local = client.getLocalPlayer();
		if (local == null)
		{
			return;
		}

		final Instant now = Instant.now();
		if (event.getSource() == local && event.getTarget() instanceof Player)
		{
			practice.observePlayerCombat(arena, now, true, false);
		}
		else if (event.getTarget() == local && event.getSource() instanceof Player)
		{
			// Someone has engaged us. Whether we fight back is what the detector decides on.
			practice.observePlayerCombat(arena, now, false, true);
		}
	}

	/** A hitsplat on the local player from a player fight keeps the engagement alive. */
	@Subscribe
	public void onHitsplatApplied(HitsplatApplied event)
	{
		if (!config.practiceDetection() || arena == Arena.ELSEWHERE)
		{
			return;
		}
		final Actor actor = event.getActor();
		final Player local = client.getLocalPlayer();
		if (local == null || (actor != local && !(actor instanceof Player)))
		{
			return;
		}
		// Not counted as an attack — a hitsplat cannot say who threw it. It only witnesses that
		// the player is *in* combat, which is the ten-second arm of the threshold.
		practice.observeCombatState(arena, Instant.now());
	}

	private Arena currentArena()
	{
		if (client.getVarbitValue(Varbits.IN_LMS) > 0)
		{
			return Arena.LMS;
		}
		return client.getVarbitValue(Varbits.IN_WILDERNESS) > 0 ? Arena.WILDERNESS : Arena.ELSEWHERE;
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
			// Practice evidence is drained here rather than collected inside the factory: the
			// drain is destructive (§6.7 — the server owns the history), so it must happen only
			// when a snapshot is genuinely being sent.
			final AccountSnapshot snapshot = SnapshotFactory.build(
				client, containers, config.practiceDetection() ? practice.drain(now) : null, now);
			if (snapshot == null)
			{
				panel.update(SyncStatus.notConfigured("Log in first — there is no account to sync."));
				return;
			}
			executor.execute(() -> syncClient.submit(snapshot));
		});
	}

}
