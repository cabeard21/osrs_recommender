package com.osrstracker.plugin;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.Test;

import java.nio.file.Paths;
import java.time.Instant;
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

	/** A payload with every current section populated. */
	private static AccountSnapshot fullyPopulated()
	{
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
		// This proves the walker sees nested keys in a current account fact.
		final com.google.gson.JsonObject payload = fullyPopulated().toJson();
		payload.getAsJsonArray("observed_items").get(0).getAsJsonObject()
			.addProperty("opponent_name", "some_player");

		final Set<String> payloadKeys = new TreeSet<>();
		collectPayloadKeys(MAPPER.readTree(payload.toString()), payloadKeys);
		payloadKeys.removeAll(declaredKeys());

		assertTrue(payloadKeys.contains("opponent_name"));
	}

}
