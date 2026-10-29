package com.osrstracker.plugin.collect;

import com.osrstracker.plugin.AccountSnapshot;
import net.runelite.api.Client;
import net.runelite.api.Quest;
import net.runelite.api.QuestState;
import net.runelite.api.Skill;
import net.runelite.api.gameval.VarPlayerID;
import org.junit.Test;

import java.util.Map;
import java.util.regex.Pattern;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * The mapping decisions, tested without a client.
 *
 * <p>Enumerating an enum is glue; deciding what {@code IN_PROGRESS} means, or which varbit stands
 * for a diary tier, is the part that can be wrong in a way nothing else catches.
 */
public class CollectorMappingTest
{
	/** The contract's `content_key`: lowercase, digits, underscores, no leading underscore. */
	private static final Pattern CONTENT_KEY = Pattern.compile("^[a-z0-9][a-z0-9_]*$");

	@Test
	public void questIdentityIsTheSlugContentAlreadyAuthors()
	{
		// The reconciliation's central ruling, and the evidence for it: `content/` independently
		// authors both of these strings.
		assertEquals("desert_treasure_i", QuestCollector.questId(Quest.DESERT_TREASURE_I));
		assertEquals("lunar_diplomacy", QuestCollector.questId(Quest.LUNAR_DIPLOMACY));
	}

	@Test
	public void everyQuestIdIsAValidContentKey()
	{
		// Apostrophes and punctuation are why display names were rejected; the enum route has to
		// survive the same test for all 200-odd quests, including the RFD sub-quests.
		for (Quest quest : Quest.values())
		{
			final String id = QuestCollector.questId(quest);
			assertTrue(quest.name() + " -> " + id, CONTENT_KEY.matcher(id).matches());
		}
	}

	@Test
	public void inProgressIsNotAPositiveState()
	{
		// A5. §9.1 evaluates it `unsatisfied`; flattening it into "complete enough" is the
		// mistake the SDD calls out by name.
		assertEquals("in_progress", QuestCollector.status(QuestState.IN_PROGRESS));
		assertEquals("complete", QuestCollector.status(QuestState.FINISHED));
		assertEquals("not_started", QuestCollector.status(QuestState.NOT_STARTED));
	}

	@Test
	public void anUnreadableQuestStateIsUnknownRatherThanNotStarted()
	{
		// G3's shape: absence of evidence is not evidence of absence.
		assertEquals("unknown", QuestCollector.status(null));
	}

	@Test
	public void skillKeysAreContentKeys()
	{
		for (Skill skill : Skill.values())
		{
			final String key = SkillCollector.key(skill);
			assertTrue(key, CONTENT_KEY.matcher(key).matches());
		}
		assertEquals("magic", SkillCollector.key(Skill.MAGIC));
	}

	@Test
	public void allFortyEightDiaryTiersAreFound()
	{
		// Twelve regions times four tiers. If a RuneLite rename drops one, this fails rather than
		// the diary quietly reading `locked` forever.
		final Map<String, Integer> diaries = UnlockCollector.namedVarbits("DIARY_");
		assertEquals(48, diaries.size());
		assertTrue(diaries.containsKey("DIARY_WILDERNESS_HARD"));
	}

	@Test
	public void allSixCombatAchievementTiersAreFound()
	{
		assertEquals(6, UnlockCollector.namedVarbits("COMBAT_ACHIEVEMENT_TIER_").size());
	}

	@Test
	public void diaryAndCaKeysUseTheReservedPrefixes()
	{
		// A12: these ride as `unlock` rows under reserved prefixes rather than getting tables of
		// their own.
		assertEquals("diary_wilderness_hard", UnlockCollector.slug("DIARY_WILDERNESS_HARD"));
		assertEquals("ca_grandmaster", "ca_" + UnlockCollector.slug("GRANDMASTER"));

		for (String name : UnlockCollector.namedVarbits("DIARY_").keySet())
		{
			assertTrue(name, CONTENT_KEY.matcher(UnlockCollector.slug(name)).matches());
		}
	}

	@Test
	public void aVarbitOfZeroIsLockedAndAnythingElseIsUnlocked()
	{
		assertEquals("locked", UnlockCollector.unlock("diary_varrock_easy", 0).toJson()
			.get("state").getAsString());
		assertEquals("unlocked", UnlockCollector.unlock("diary_varrock_easy", 1).toJson()
			.get("state").getAsString());
	}

	@Test
	public void daeroTrainingRequiresTheClaimedRewardState()
	{
		final Client client = mock(Client.class);
		// Includes quest complete (9), which does not establish training completion.
		for (int progress = 0; progress <= 9; progress++)
		{
			when(client.getVarpValue(VarPlayerID.MM_MAIN)).thenReturn(progress);
			assertEquals("locked", UnlockCollector.daeroTraining(client).toJson()
				.get("state").getAsString());
		}
		when(client.getVarpValue(VarPlayerID.MM_MAIN)).thenReturn(10);
		final AccountSnapshot.Unlock trained = UnlockCollector.daeroTraining(client);
		assertEquals("daero_training_complete", trained.toJson().get("key").getAsString());
		assertEquals("unlocked", trained.toJson().get("state").getAsString());
	}

	@Test
	public void unexpectedDaeroProgressStaysUnknown()
	{
		for (int progress : new int[]{-1, 11, Integer.MAX_VALUE})
		{
			final Client client = mock(Client.class);
			when(client.getVarpValue(VarPlayerID.MM_MAIN)).thenReturn(progress);
			assertEquals("unknown", UnlockCollector.daeroTraining(client).toJson()
				.get("state").getAsString());
			verify(client).getVarpValue(VarPlayerID.MM_MAIN);
		}
	}

	@Test
	public void collectedUnlocksIncludeDaeroTrainingWithoutRfdCompletion()
	{
		final Client client = mock(Client.class);
		// RuneLite's Quest.getState reads the script result from this stack.
		// All quests are in progress here, including the final RFD subquest.
		when(client.getIntStack()).thenReturn(new int[]{0});
		when(client.getVarpValue(VarPlayerID.MM_MAIN)).thenReturn(10);
		final AccountSnapshot.Unlock[] training = UnlockCollector.collect(client).stream()
			.filter(unlock -> unlock.toJson().get("key").getAsString()
				.equals("daero_training_complete"))
			.toArray(AccountSnapshot.Unlock[]::new);
		assertEquals(1, training.length);
		assertEquals("unlocked", training[0].toJson().get("state").getAsString());
		verify(client).getVarpValue(VarPlayerID.MM_MAIN);
	}

	@Test
	public void nothingIsEverReportedAsAvailable()
	{
		// A5 again, from the other side: `available` means purchasable but not owned. No varbit
		// the plugin reads can witness that, so the collector must never claim it.
		final AccountSnapshot.Unlock locked = UnlockCollector.unlock("rigour", 0);
		final AccountSnapshot.Unlock unlocked = UnlockCollector.unlock("rigour", 1);

		assertFalse(locked.toJson().toString().contains("available"));
		assertFalse(unlocked.toJson().toString().contains("available"));
	}

	@Test
	public void theQuestGrantedUnlockTableCoversWhatContentAsksFor()
	{
		// `content/` references ancient_magicks and spellbook_lunar, and no varbit exposes
		// either — see the G9 note on UnlockCollector.
		assertTrue(UnlockCollector.QUEST_GRANTED_UNLOCKS.containsKey("DESERT_TREASURE_I"));
		assertTrue(UnlockCollector.QUEST_GRANTED_UNLOCKS.containsKey("LUNAR_DIPLOMACY"));

		for (Map.Entry<String, String[]> entry : UnlockCollector.QUEST_GRANTED_UNLOCKS.entrySet())
		{
			// Every key in the table must name a real quest constant, or it silently never fires.
			Quest.valueOf(entry.getKey());
			for (String key : entry.getValue())
			{
				assertTrue(key, CONTENT_KEY.matcher(key).matches());
			}
		}
	}
}
