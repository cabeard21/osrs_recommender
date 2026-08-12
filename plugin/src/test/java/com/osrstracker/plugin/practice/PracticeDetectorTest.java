package com.osrstracker.plugin.practice;

import com.google.gson.JsonObject;
import com.osrstracker.plugin.AccountSnapshot;
import com.osrstracker.plugin.practice.PracticeDetector.Arena;
import org.junit.Test;

import java.time.Instant;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.stream.Collectors;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

/**
 * §7.6, including everything it refuses to count.
 *
 * <p>Most of these are negative tests, which is the right shape for this table: the expensive
 * failure is not a missed refresh, it is a milestone that looks practiced because somebody walked
 * into the Wilderness.
 */
public class PracticeDetectorTest
{
	private static final Instant T0 = Instant.parse("2026-08-12T18:00:00Z");

	private final PracticeDetector detector = new PracticeDetector();

	private static Instant at(int seconds)
	{
		return T0.plusSeconds(seconds);
	}

	/** Drains well after any session could still be open. */
	private List<AccountSnapshot.PracticeEvent> drain()
	{
		return detector.drain(at(3600));
	}

	private static Set<String> domainsOf(List<AccountSnapshot.PracticeEvent> events)
	{
		return events.stream()
			.map(e -> e.toJson().get("domain").getAsString())
			.collect(Collectors.toSet());
	}

	private static Set<String> evidenceOf(List<AccountSnapshot.PracticeEvent> events)
	{
		return events.stream()
			.map(e -> e.toJson().get("evidence_type").getAsString())
			.collect(Collectors.toSet());
	}

	private static Set<String> setOf(String... values)
	{
		return new HashSet<>(java.util.Arrays.asList(values));
	}

	// -------------------------------------------------------------------------------------
	// The threshold: two attacks, or ten seconds
	// -------------------------------------------------------------------------------------

	@Test
	public void oneAttackDoesNotRefreshAnything()
	{
		// "Someone misclicked another player."
		detector.observePlayerCombat(Arena.WILDERNESS, at(0), true, false);

		assertTrue(drain().isEmpty());
	}

	@Test
	public void aSingleHitTakenWhileEscapingDoesNotRefreshAnything()
	{
		detector.observePlayerCombat(Arena.WILDERNESS, at(0), false, true);

		assertTrue(drain().isEmpty());
	}

	@Test
	public void twoAttacksCrossTheThreshold()
	{
		detector.observePlayerCombat(Arena.WILDERNESS, at(0), true, false);
		detector.observePlayerCombat(Arena.WILDERNESS, at(1), true, false);

		assertEquals(setOf("wilderness_pvp", "general_pvp"), domainsOf(drain()));
	}

	@Test
	public void nineSecondsOfCombatStateWithOneAttackDoesNot()
	{
		detector.observePlayerCombat(Arena.WILDERNESS, at(0), true, false);
		for (int second = 1; second <= 9; second++)
		{
			detector.observeCombatState(Arena.WILDERNESS, at(second));
		}

		assertTrue(drain().isEmpty());
	}

	@Test
	public void tenSecondsOfCombatStateQualifiesWithoutASecondAttack()
	{
		// The other arm of the disjunction, and the reason `observeCombatState` exists: a long
		// engagement in which the plugin only ever resolved one attack is still practice.
		detector.observePlayerCombat(Arena.WILDERNESS, at(0), true, false);
		for (int second = 1; second <= 10; second++)
		{
			detector.observeCombatState(Arena.WILDERNESS, at(second));
		}

		assertEquals(setOf("wilderness_pvp", "general_pvp"), domainsOf(drain()));
	}

	@Test
	public void combatStateAloneWithNoAttackAtAllStillNeedsTheDuration()
	{
		detector.observeCombatState(Arena.WILDERNESS, at(0));
		detector.observeCombatState(Arena.WILDERNESS, at(3));

		assertTrue(drain().isEmpty());
	}

	// -------------------------------------------------------------------------------------
	// What §7.6 rejects
	// -------------------------------------------------------------------------------------

	@Test
	public void merelyEnteringTheWildernessEmitsNothing()
	{
		detector.observeWildernessEntry(at(0));
		detector.observeWildernessEntry(at(60));

		assertTrue(drain().isEmpty());
	}

	@Test
	public void switchingPrayersEmitsNothing()
	{
		for (int i = 0; i < 20; i++)
		{
			detector.observePrayerSwitch(at(i));
		}

		assertTrue(drain().isEmpty());
	}

	@Test
	public void equippingMultipleCombatStylesEmitsNothing()
	{
		detector.observeStyleSwitch(at(0));
		detector.observeStyleSwitch(at(2));
		detector.observeStyleSwitch(at(4));

		assertTrue(drain().isEmpty());
	}

	@Test
	public void loggingInAfterALongBreakEmitsNothing()
	{
		detector.observeLogin(at(0));

		assertTrue(drain().isEmpty());
	}

	@Test
	public void combatOutsideAnArenaEmitsNothing()
	{
		// Duel arena, castle wars, a PvP-world safe zone: not one of §7.6's domains.
		detector.observePlayerCombat(Arena.ELSEWHERE, at(0), true, false);
		detector.observePlayerCombat(Arena.ELSEWHERE, at(1), true, false);
		detector.observeCombatState(Arena.ELSEWHERE, at(30));

		assertTrue(drain().isEmpty());
	}

	// -------------------------------------------------------------------------------------
	// Anti-PK: only if the player fights back
	// -------------------------------------------------------------------------------------

	@Test
	public void beingAttackedWithoutFightingBackIsNotAntiPk()
	{
		// Killed on a PvM setup while running. §7.6 credits the fighting back; crediting the
		// dying would reward the exact thing anti-PK practice exists to fix.
		detector.observePlayerCombat(Arena.WILDERNESS, at(0), false, true);
		detector.observePlayerCombat(Arena.WILDERNESS, at(3), false, true);

		final Set<String> domains = domainsOf(drain());
		assertTrue(domains.toString(), domains.contains("wilderness_pvp"));
		assertFalse(domains.toString(), domains.contains("anti_pking"));
	}

	@Test
	public void beingAttackedAndFightingBackIsAntiPk()
	{
		detector.observePlayerCombat(Arena.WILDERNESS, at(0), false, true);
		detector.observePlayerCombat(Arena.WILDERNESS, at(2), true, false);

		assertEquals(setOf("wilderness_pvp", "general_pvp", "anti_pking"), domainsOf(drain()));
	}

	@Test
	public void startingTheFightYourselfIsNotAntiPkEvenIfTheyHitBack()
	{
		// The player picked this fight; it is already credited as wilderness PvP. Calling it
		// anti-PK too would refresh a milestone about being ambushed.
		detector.observePlayerCombat(Arena.WILDERNESS, at(0), true, false);
		detector.observePlayerCombat(Arena.WILDERNESS, at(2), false, true);

		assertFalse(domainsOf(drain()).contains("anti_pking"));
	}

	@Test
	public void anAntiPkThatNeverCrossesTheThresholdIsStillNothing()
	{
		detector.observePlayerCombat(Arena.WILDERNESS, at(0), false, true);

		assertTrue(drain().isEmpty());
	}

	// -------------------------------------------------------------------------------------
	// LMS
	// -------------------------------------------------------------------------------------

	@Test
	public void aCompletedLmsMatchRefreshesEntryAndExitDomains()
	{
		detector.lmsMatchStarted(at(0));
		detector.lmsMatchEnded(at(300));

		final List<AccountSnapshot.PracticeEvent> events = drain();
		assertEquals(setOf("lms", "nh_combat", "general_pvp"), domainsOf(events));
		assertEquals(setOf("lms_match_completed"), evidenceOf(events));
	}

	@Test
	public void anLmsMatchTheClientOnlySawTheEndOfIsNotInvented()
	{
		// No start means no span. §4.5: guessing one is how an age becomes silently wrong.
		detector.lmsMatchEnded(at(300));

		assertTrue(drain().isEmpty());
	}

	@Test
	public void sustainedLmsCombatRefreshesLmsAndNhButNotGeneralPvp()
	{
		// §7.6 gives the narrower pair to combat inside a match; general_pvp belongs to the
		// completed match, not to every exchange within one.
		detector.observePlayerCombat(Arena.LMS, at(0), true, false);
		detector.observePlayerCombat(Arena.LMS, at(4), true, false);

		assertEquals(setOf("lms", "nh_combat"), domainsOf(drain()));
	}

	// -------------------------------------------------------------------------------------
	// Sessions and shape
	// -------------------------------------------------------------------------------------

	@Test
	public void aSessionIsOneEventPerDomainNotOnePerAttack()
	{
		for (int i = 0; i < 12; i++)
		{
			detector.observePlayerCombat(Arena.WILDERNESS, at(i), true, false);
		}

		assertEquals(2, drain().size());
	}

	@Test
	public void aQuietGapEndsTheEngagement()
	{
		detector.observePlayerCombat(Arena.WILDERNESS, at(0), true, false);
		detector.observePlayerCombat(Arena.WILDERNESS, at(2), true, false);
		detector.observePlayerCombat(Arena.WILDERNESS, at(600), true, false);
		detector.observePlayerCombat(Arena.WILDERNESS, at(602), true, false);

		assertEquals(4, detector.drain(at(1200)).size());
	}

	@Test
	public void anEngagementStillUnderwayIsNotReportedYet()
	{
		detector.observePlayerCombat(Arena.WILDERNESS, at(0), true, false);
		detector.observePlayerCombat(Arena.WILDERNESS, at(2), true, false);

		// Reporting now would claim the fight ended when the snapshot happened to be taken.
		assertTrue(detector.drain(at(5)).isEmpty());
	}

	@Test
	public void movingBetweenArenasClosesTheFirstEngagement()
	{
		detector.observePlayerCombat(Arena.WILDERNESS, at(0), true, false);
		detector.observePlayerCombat(Arena.WILDERNESS, at(2), true, false);
		detector.observePlayerCombat(Arena.LMS, at(4), true, false);
		detector.observePlayerCombat(Arena.LMS, at(6), true, false);

		assertEquals(setOf("wilderness_pvp", "general_pvp", "lms", "nh_combat"), domainsOf(drain()));
	}

	@Test
	public void eventsAreDrainedOnceAndForgotten()
	{
		detector.observePlayerCombat(Arena.WILDERNESS, at(0), true, false);
		detector.observePlayerCombat(Arena.WILDERNESS, at(2), true, false);

		assertEquals(2, drain().size());
		// Re-sending would turn one session into two on the server (§6.7).
		assertTrue(drain().isEmpty());
	}

	@Test
	public void loggingOutDiscardsAnUnfinishedEngagement()
	{
		detector.observePlayerCombat(Arena.WILDERNESS, at(0), true, false);
		detector.observePlayerCombat(Arena.WILDERNESS, at(2), true, false);

		detector.reset();

		assertTrue(drain().isEmpty());
	}

	@Test
	public void everyEventCarriesExactlyTheFourSummaryFields()
	{
		// G8. The schema's additionalProperties:false enforces it at the boundary; this pins the
		// intent at the source, where a well-meaning "just add the opponent" would start.
		detector.observePlayerCombat(Arena.WILDERNESS, at(0), false, true);
		detector.observePlayerCombat(Arena.WILDERNESS, at(2), true, false);

		for (AccountSnapshot.PracticeEvent event : drain())
		{
			final JsonObject json = event.toJson();
			assertEquals(json.toString(),
				setOf("domain", "started_at", "ended_at", "evidence_type"), json.keySet());
		}
	}

	@Test
	public void spansAreOffsetAwareAndCoverTheEngagement()
	{
		detector.observePlayerCombat(Arena.WILDERNESS, at(0), true, false);
		detector.observePlayerCombat(Arena.WILDERNESS, at(30), true, false);

		final JsonObject json = drain().get(0).toJson();
		assertEquals("2026-08-12T18:00:00Z", json.get("started_at").getAsString());
		assertEquals("2026-08-12T18:00:30Z", json.get("ended_at").getAsString());
	}
}
