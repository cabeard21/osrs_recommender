package com.osrstracker.plugin;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.osrstracker.plugin.practice.PracticeDetector;
import com.osrstracker.plugin.practice.PracticeDetector.Arena;
import org.junit.Test;

import java.nio.file.Paths;
import java.time.Instant;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Iterator;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;

import static org.junit.Assert.assertTrue;

/**
 * G8's structural check: walk the serialized payload and assert every key it contains is one the
 * frozen schema declares.
 *
 * <p>The plan is explicit that this <b>replaces</b> grepping the source for
 * {@code opponent|chatMessage|playerName}, which both false-positives on legitimate RuneLite API
 * use and never actually inspects the thing that leaves the machine. §7.6's collection boundary
 * is about the payload path, so the payload path is what gets audited.
 */
public class PayloadKeySetAuditTest
{
	private static final ObjectMapper MAPPER = new ObjectMapper();
	private static final Instant T0 = Instant.parse("2026-08-12T18:00:00Z");

	/** Every property name the contract declares, anywhere in it. */
	private static Set<String> declaredKeys() throws Exception
	{
		final JsonNode schema = MAPPER.readTree(Paths.get(System.getProperty("tracker.contract")).toFile());
		final Set<String> declared = new TreeSet<>();
		collectDeclared(schema, declared);
		return declared;
	}

	private static void collectDeclared(JsonNode node, Set<String> sink)
	{
		if (node.isObject())
		{
			final JsonNode properties = node.get("properties");
			if (properties != null && properties.isObject())
			{
				properties.fieldNames().forEachRemaining(sink::add);
			}
			final Iterator<Map.Entry<String, JsonNode>> fields = node.fields();
			while (fields.hasNext())
			{
				collectDeclared(fields.next().getValue(), sink);
			}
		}
		else if (node.isArray())
		{
			node.forEach(child -> collectDeclared(child, sink));
		}
	}

	private static void collectPayloadKeys(JsonNode node, Set<String> sink)
	{
		if (node.isObject())
		{
			final Iterator<Map.Entry<String, JsonNode>> fields = node.fields();
			while (fields.hasNext())
			{
				final Map.Entry<String, JsonNode> field = fields.next();
				sink.add(field.getKey());
				collectPayloadKeys(field.getValue(), sink);
			}
		}
		else if (node.isArray())
		{
			node.forEach(child -> collectPayloadKeys(child, sink));
		}
	}

	/** A payload with every section populated, including practice evidence from the detector. */
	private static AccountSnapshot fullyPopulated()
	{
		final PracticeDetector detector = new PracticeDetector();
		detector.observePlayerCombat(Arena.WILDERNESS, T0, false, true);
		detector.observePlayerCombat(Arena.WILDERNESS, T0.plusSeconds(4), true, false);

		final AccountSnapshot.Builder builder = AccountSnapshot.builder("redacted", T0)
			.displayName("redacted")
			.combatLevel(126)
			.questPoints(300)
			.skill(new AccountSnapshot.Skill("magic", 94, 7_195_629))
			.skill(new AccountSnapshot.Skill("construction", 1, null))
			.quest(new AccountSnapshot.Quest("desert_treasure_i", "complete"))
			.unlock(new AccountSnapshot.Unlock("ancient_magicks", "unlocked"))
			.item(new AccountSnapshot.ObservedItem(27690, 1, "bank"))
			.containerScan(new AccountSnapshot.ContainerScan("bank", T0.minusSeconds(60)));

		detector.drain(T0.plusSeconds(600)).forEach(builder::practiceEvent);
		return builder.build();
	}

	@Test
	public void thePayloadContainsNoKeyTheContractDoesNotDeclare() throws Exception
	{
		final Set<String> payloadKeys = new TreeSet<>();
		collectPayloadKeys(MAPPER.readTree(fullyPopulated().toJson().toString()), payloadKeys);

		final Set<String> undeclared = new HashSet<>(payloadKeys);
		undeclared.removeAll(declaredKeys());

		assertTrue("payload carries undeclared keys: " + undeclared, undeclared.isEmpty());
	}

	@Test
	public void theAuditWouldActuallyCatchALeak() throws Exception
	{
		// A test that can only pass is not a test. This proves the walker sees nested keys — the
		// place a leak would actually appear is inside a practice event, not at the root.
		final com.google.gson.JsonObject payload = fullyPopulated().toJson();
		payload.getAsJsonArray("practice_events").get(0).getAsJsonObject()
			.addProperty("opponent_name", "some_player");

		final Set<String> payloadKeys = new TreeSet<>();
		collectPayloadKeys(MAPPER.readTree(payload.toString()), payloadKeys);
		payloadKeys.removeAll(declaredKeys());

		assertTrue(payloadKeys.contains("opponent_name"));
	}

	@Test
	public void thePracticeEventsTheDetectorProducesCarryNothingExtra() throws Exception
	{
		// The §7.6 vocabulary is the whole vocabulary: no opponent, no chat, no prayers, no
		// fight-time inventory, no tick-by-tick location.
		final JsonNode events = MAPPER.readTree(fullyPopulated().toJson().toString())
			.get("practice_events");

		assertTrue(events.size() > 0);
		for (JsonNode event : events)
		{
			final Set<String> keys = new TreeSet<>();
			event.fieldNames().forEachRemaining(keys::add);
			assertTrue(keys.toString(), keys.equals(new TreeSet<>(
				Arrays.asList("domain", "started_at", "ended_at", "evidence_type"))));
		}
	}
}
