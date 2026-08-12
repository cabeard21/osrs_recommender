package com.osrstracker.plugin.collect;

import com.osrstracker.plugin.AccountSnapshot;
import net.runelite.api.Client;
import net.runelite.api.Skill;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

/**
 * Skills and XP (§7.1). Must run on the client thread.
 *
 * <p>Every skill the client knows is sent, including ones the corpus has never heard of —
 * {@code sailing} appeared in the reconciliation capture at level 1. The app tolerates unknown
 * skill keys; a collector that filtered to a hard-coded list would put game content in code (G9)
 * and would silently drop the next new skill.
 */
public final class SkillCollector
{
	private SkillCollector()
	{
	}

	public static List<AccountSnapshot.Skill> collect(Client client)
	{
		final List<AccountSnapshot.Skill> skills = new ArrayList<>();
		for (Skill skill : Skill.values())
		{
			if ("OVERALL".equals(skill.name()))
			{
				// A total, not a skill. §6.2 stores one row per trainable skill.
				continue;
			}
			skills.add(new AccountSnapshot.Skill(
				key(skill),
				client.getRealSkillLevel(skill),
				client.getSkillExperience(skill)));
		}
		return skills;
	}

	/**
	 * G5 note: this never produces null. The client reports 0 xp for an untrained skill, never
	 * -1 — confirmed against a real capture — so the null-means-unranked case belongs to the
	 * hiscores and WOM adapters (§7.3), not here. See docs/CONTRACT_RECONCILIATION.md.
	 */
	static String key(Skill skill)
	{
		return skill.name().toLowerCase(Locale.ROOT);
	}
}
