package com.osrstracker.plugin;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.google.gson.GsonBuilder;
import com.networknt.schema.JsonSchema;
import com.networknt.schema.JsonSchemaFactory;
import com.networknt.schema.SpecVersion;
import com.networknt.schema.ValidationMessage;
import com.osrstracker.plugin.contract.SyncPayloadFields;
import org.junit.Test;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.time.Instant;
import java.util.Set;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

/**
 * The Java half of step 12a's cross-language contract test.
 *
 * <p>It serializes an {@link AccountSnapshot} and validates it against <b>the same file</b> the
 * Python side validates against — {@code contracts/sync_payload.schema.json}, passed in by
 * Gradle rather than copied here, because a copied schema is two schemas.
 *
 * <p>It also writes {@code tests/contracts/fixtures/plugin_sample.json}, which
 * {@code tests/contracts/test_plugin_fixture.py} POSTs at the real API. The timestamps are fixed
 * so the file is byte-stable: a diff there means the serialization changed, which is precisely
 * when someone should be made to look.
 */
public class ContractSerializationTest
{
	/** Fixed instants — a byte-stable fixture is the point (see class javadoc). */
	private static final Instant OBSERVED_AT = Instant.parse("2026-08-11T20:15:00Z");
	private static final Instant BANK_SCANNED_AT = Instant.parse("2026-08-11T20:12:30Z");

	private static final ObjectMapper MAPPER = new ObjectMapper();

	private static AccountSnapshot sample()
	{
		return AccountSnapshot.builder("redacted", OBSERVED_AT)
			.displayName("redacted")
			.combatLevel(126)
			.questPoints(300)
			.skill(new AccountSnapshot.Skill("magic", 94, 7_195_629))
			// G5: unranked is null, never 0 — expressible from the plugin even though the client
			// itself never reports it (docs/CONTRACT_RECONCILIATION.md).
			.skill(new AccountSnapshot.Skill("construction", 1, null))
			.quest(new AccountSnapshot.Quest("desert_treasure_i", "complete"))
			.quest(new AccountSnapshot.Quest("lunar_diplomacy", "in_progress"))
			.unlock(new AccountSnapshot.Unlock("ancient_magicks", "unlocked"))
			// A5: "available" means purchasable, not owned. Kept in the fixture because it is the
			// single most likely thing for a future collector to get backwards.
			.unlock(new AccountSnapshot.Unlock("rigour", "available"))
			.unlock(new AccountSnapshot.Unlock("diary_wilderness_hard", "locked"))
			.item(new AccountSnapshot.ObservedItem(27690, 1, "bank"))
			.containerScan(new AccountSnapshot.ContainerScan("bank", BANK_SCANNED_AT))
			.build();
	}

	private static JsonSchema contract() throws Exception
	{
		final Path schemaPath = Paths.get(System.getProperty("tracker.contract"));
		final JsonNode schemaNode = MAPPER.readTree(schemaPath.toFile());
		return JsonSchemaFactory.getInstance(SpecVersion.VersionFlag.V202012).getSchema(schemaNode);
	}

	@Test
	public void aSerializedSnapshotValidatesAgainstTheFrozenContract() throws Exception
	{
		final JsonNode payload = MAPPER.readTree(sample().toJson().toString());
		final Set<ValidationMessage> errors = contract().validate(payload);
		assertTrue("schema violations: " + errors, errors.isEmpty());
	}

	@Test
	public void theFixtureThePythonSidePostsIsWrittenFromThisSerializer() throws Exception
	{
		final String json = new GsonBuilder().setPrettyPrinting().serializeNulls().create()
			.toJson(sample().toJson()) + "\n";

		final Path fixture = Paths.get(System.getProperty("tracker.fixture"));
		Files.createDirectories(fixture.getParent());
		Files.write(fixture, json.getBytes(StandardCharsets.UTF_8));

		// Round-trip: what was written is what validates.
		final Set<ValidationMessage> errors = contract().validate(MAPPER.readTree(fixture.toFile()));
		assertTrue("fixture violates the contract: " + errors, errors.isEmpty());
	}

	@Test
	public void anUncollectedSectionIsAbsentRatherThanEmpty()
	{
		// §6.5. `"skills": []` would claim the plugin looked and the account has no skills; a
		// missing key claims nothing. Step 12a collects none of these, so none may appear.
		final AccountSnapshot identityOnly =
			AccountSnapshot.builder("redacted", OBSERVED_AT).combatLevel(3).build();
		final String json = identityOnly.toJson().toString();

		assertFalse(json, json.contains(SyncPayloadFields.SKILLS));
		assertFalse(json, json.contains(SyncPayloadFields.CONTAINER_SCANS));
		assertFalse(json, json.contains(SyncPayloadFields.PRACTICE_EVENTS));
	}

	@Test
	public void anIdentityOnlySnapshotIsStillAValidPayload() throws Exception
	{
		// What Step 12a actually sends today. It must be acceptable on its own, or the skeleton
		// cannot be exercised end to end before the collectors land.
		final AccountSnapshot identityOnly =
			AccountSnapshot.builder("redacted", OBSERVED_AT).combatLevel(3).build();
		final JsonNode payload = MAPPER.readTree(identityOnly.toJson().toString());
		assertTrue(contract().validate(payload).isEmpty());
	}

	@Test
	public void timestampsCarryAnExplicitOffset()
	{
		// §4.5: an offset-naive instant is how an age becomes silently wrong. The schema's
		// pattern enforces it; this pins the formatter that has to satisfy it.
		assertEquals("2026-08-11T20:15:00Z", AccountSnapshot.timestamp(OBSERVED_AT));
		assertEquals("2026-08-11T20:15:00Z",
			AccountSnapshot.timestamp(OBSERVED_AT.plusMillis(400)));
	}

	@Test
	public void payloadVersionMatchesWhatTheServerSupports()
	{
		// §12.2. The server declares {1}; sending anything else earns a 409.
		assertEquals(1, AccountSnapshot.PAYLOAD_VERSION);
	}
}
