package com.osrstracker.plugin.collect;

import com.osrstracker.plugin.AccountSnapshot;
import net.runelite.api.Client;
import net.runelite.api.Quest;
import net.runelite.api.QuestState;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

/**
 * Quest completion (§7.1). Must run on the client thread — {@link Quest#getState(Client)} reads
 * varbits.
 *
 * <p>Identity is a slug of the RuneLite enum constant, the ruling in
 * docs/CONTRACT_RECONCILIATION.md: {@code DESERT_TREASURE_I} → {@code desert_treasure_i}, which
 * is exactly what {@code content/} independently authors. Numeric ids have gaps and display
 * names carry punctuation no {@code content_key} admits.
 *
 * <p>Recipe for Disaster appears as both the parent quest and its ten sub-quests, each with its
 * own state. Both are transmitted; nothing is derived from the other.
 */
public final class QuestCollector
{
	private QuestCollector()
	{
	}

	public static List<AccountSnapshot.Quest> collect(Client client)
	{
		final List<AccountSnapshot.Quest> quests = new ArrayList<>();
		for (Quest quest : Quest.values())
		{
			quests.add(new AccountSnapshot.Quest(questId(quest), status(quest.getState(client))));
		}
		return quests;
	}

	static String questId(Quest quest)
	{
		return slug(quest.name());
	}

	/**
	 * A5, the rule an implementer gets wrong by default: {@code IN_PROGRESS} is <b>not</b> a
	 * positive state. §9.1 evaluates it {@code unsatisfied}, so it must not be flattened into
	 * "started, close enough".
	 */
	static String status(QuestState state)
	{
		if (state == null)
		{
			return "unknown";
		}
		switch (state)
		{
			case FINISHED:
				return "complete";
			case IN_PROGRESS:
				return "in_progress";
			case NOT_STARTED:
				return "not_started";
			default:
				return "unknown";
		}
	}

	static String slug(String constantName)
	{
		return constantName
			.toLowerCase(Locale.ROOT)
			.replaceAll("[^a-z0-9]+", "_")
			.replaceAll("^_+|_+$", "");
	}
}
