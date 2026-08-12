package com.osrstracker.plugin.collect;

import com.osrstracker.plugin.AccountSnapshot;
import net.runelite.api.Client;
import net.runelite.api.GameState;
import net.runelite.api.Player;
import net.runelite.api.VarPlayer;

import java.time.Instant;
import java.util.List;

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

	/**
	 * @param practiceEvents evidence drained from the §7.6 detector, or null when practice
	 *                       detection is switched off — which is a different fact from "no
	 *                       practice happened" and so contributes no events either way.
	 * @return null when there is no logged-in account to describe.
	 */
	public static AccountSnapshot build(Client client, ContainerObserver containers,
		List<AccountSnapshot.PracticeEvent> practiceEvents, Instant now)
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

		if (practiceEvents != null)
		{
			// G7: these refresh freshness only. Nothing here can set `achieved` — participation
			// is not competence, and the server enforces that too.
			practiceEvents.forEach(builder::practiceEvent);
		}
		return builder.build();
	}
}
