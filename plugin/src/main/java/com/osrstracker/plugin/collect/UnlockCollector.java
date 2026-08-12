package com.osrstracker.plugin.collect;

import com.osrstracker.plugin.AccountSnapshot;
import net.runelite.api.Client;
import net.runelite.api.Quest;
import net.runelite.api.QuestState;
import net.runelite.api.Varbits;
import net.runelite.api.gameval.VarbitID;

import java.lang.reflect.Field;
import java.lang.reflect.Modifier;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * Unlock flags: achievement diaries, combat achievements, spellbooks and the scroll prayers
 * (§7.1, A12). Must run on the client thread.
 *
 * <p>Three sources, for three different reasons:
 *
 * <ul>
 *   <li><b>Diaries and CAs</b> come from {@code Varbits}, enumerated reflectively. That class is
 *       deprecated in favour of {@code gameval.VarbitID}, but it is the only one whose constants
 *       are <em>named</em> ({@code DIARY_WILDERNESS_HARD}), and names are what let this collect
 *       all 48 diary tiers without transcribing 48 integers by hand.</li>
 *   <li><b>Rigour and Augury</b> come from {@code VarbitID}, which is the only place the
 *       {@code _UNLOCKED} flags exist. Note {@code Varbits.PRAYER_RIGOUR} is the <em>active</em>
 *       prayer, not the unlock — using it would report Rigour as locked whenever it is switched
 *       off, which is most of the time.</li>
 *   <li><b>Spellbooks and Ancient Magicks</b> are derived from the granting quest, per the
 *       ruling in docs/CONTRACT_RECONCILIATION.md. {@code Varbits.SPELLBOOK} is the currently
 *       open book — an "unlock" that flips when the player walks to an altar is not an
 *       unlock.</li>
 * </ul>
 *
 * <p><b>Known G9 tension.</b> {@link #QUEST_GRANTED_UNLOCKS} is game content living in Java: it
 * says Desert Treasure I grants Ancients. It is here because the payload must carry the unlock
 * key {@code content/} asks for, and the client exposes no varbit for it. Three entries is the
 * whole of it, and moving it into {@code content/} as a `grants` mapping is the obvious fix if
 * this list ever starts growing.
 */
public final class UnlockCollector
{
	/** §6.3 states. `available` means purchasable, not owned (A5) — nothing here emits it. */
	static final String UNLOCKED = "unlocked";
	static final String LOCKED = "locked";

	/** See the class note on G9. Quest constant name → the unlock keys its completion grants. */
	static final Map<String, String[]> QUEST_GRANTED_UNLOCKS = new LinkedHashMap<String, String[]>()
	{
		{
			put("DESERT_TREASURE_I", new String[]{"ancient_magicks", "spellbook_ancient"});
			put("LUNAR_DIPLOMACY", new String[]{"spellbook_lunar"});
			put("THE_ASCENT_OF_ARCEUUS", new String[]{"spellbook_arceuus"});
		}
	};

	private UnlockCollector()
	{
	}

	public static List<AccountSnapshot.Unlock> collect(Client client)
	{
		final List<AccountSnapshot.Unlock> unlocks = new ArrayList<>();

		for (Map.Entry<String, Integer> varbit : namedVarbits("DIARY_").entrySet())
		{
			unlocks.add(unlock(slug(varbit.getKey()), client.getVarbitValue(varbit.getValue())));
		}

		for (Map.Entry<String, Integer> varbit : namedVarbits("COMBAT_ACHIEVEMENT_TIER_").entrySet())
		{
			final String tier = varbit.getKey().substring("COMBAT_ACHIEVEMENT_TIER_".length());
			unlocks.add(unlock("ca_" + slug(tier), client.getVarbitValue(varbit.getValue())));
		}

		unlocks.add(unlock("rigour", client.getVarbitValue(VarbitID.PRAYER_RIGOUR_UNLOCKED)));
		unlocks.add(unlock("augury", client.getVarbitValue(VarbitID.PRAYER_AUGURY_UNLOCKED)));

		unlocks.addAll(questGranted(client));
		return unlocks;
	}

	/** The spellbook and Ancients rows, read off quest completion rather than the active book. */
	static List<AccountSnapshot.Unlock> questGranted(Client client)
	{
		final List<AccountSnapshot.Unlock> unlocks = new ArrayList<>();
		for (Quest quest : Quest.values())
		{
			final String[] granted = QUEST_GRANTED_UNLOCKS.get(quest.name());
			if (granted == null)
			{
				continue;
			}
			final boolean complete = quest.getState(client) == QuestState.FINISHED;
			for (String key : granted)
			{
				unlocks.add(new AccountSnapshot.Unlock(key, complete ? UNLOCKED : LOCKED));
			}
		}
		return unlocks;
	}

	static AccountSnapshot.Unlock unlock(String key, int varbitValue)
	{
		return new AccountSnapshot.Unlock(key, varbitValue > 0 ? UNLOCKED : LOCKED);
	}

	/**
	 * Every {@code Varbits} constant whose name starts with the prefix, in declaration order.
	 *
	 * <p>Reflection rather than a hand-written list: 48 diary tiers and 6 CA tiers transcribed by
	 * hand is 54 chances to fat-finger an integer, and the mistake would look like a locked
	 * diary rather than like a bug.
	 */
	static Map<String, Integer> namedVarbits(String prefix)
	{
		final Map<String, Integer> found = new LinkedHashMap<>();
		for (Field field : Varbits.class.getDeclaredFields())
		{
			if (!Modifier.isStatic(field.getModifiers()) || field.getType() != int.class)
			{
				continue;
			}
			if (!field.getName().startsWith(prefix))
			{
				continue;
			}
			try
			{
				found.put(field.getName(), field.getInt(null));
			}
			catch (IllegalAccessException ignored)
			{
				// Public constants on a public class; unreachable in practice.
			}
		}
		return found;
	}

	static String slug(String constantName)
	{
		return constantName.toLowerCase(Locale.ROOT).replaceAll("[^a-z0-9]+", "_");
	}
}
