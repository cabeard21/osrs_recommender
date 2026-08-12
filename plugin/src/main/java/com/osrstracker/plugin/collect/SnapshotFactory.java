package com.osrstracker.plugin.collect;

import com.osrstracker.plugin.AccountSnapshot;
import net.runelite.api.Client;
import net.runelite.api.GameState;
import net.runelite.api.Player;
import net.runelite.api.VarPlayer;

import java.time.Instant;

/**
 * Assembles one {@link AccountSnapshot} from the collectors. <b>Client thread only</b> — every
 * collector here reads client state.
 *
 * <p>Sections are populated only when there is evidence for them, which is why the container
 * lists are asked for rather than assumed: §6.5's "never looked" has to survive all the way into
 * the payload as an absent key.
 */
public final class SnapshotFactory
{
	private SnapshotFactory()
	{
	}

	/** @return null when there is no logged-in account to describe. */
	public static AccountSnapshot build(Client client, ContainerObserver containers, Instant now)
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

		final AccountSnapshot.Builder builder = AccountSnapshot.builder(local.getName(), now)
			.displayName(local.getName())
			.combatLevel(local.getCombatLevel())
			.questPoints(client.getVarpValue(VarPlayer.QUEST_POINTS));

		SkillCollector.collect(client).forEach(builder::skill);
		QuestCollector.collect(client).forEach(builder::quest);
		UnlockCollector.collect(client).forEach(builder::unlock);
		containers.items().forEach(builder::item);
		containers.scans().forEach(builder::containerScan);

		// practice_events stay empty here: Step 12c owns the detector, and until it exists the
		// honest payload carries no practice claims at all (G7 — participation is not competence).
		return builder.build();
	}
}
