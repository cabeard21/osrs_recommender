package com.osrstracker.plugin;

import com.google.gson.Gson;
import okhttp3.OkHttpClient;
import okhttp3.mockwebserver.MockResponse;
import okhttp3.mockwebserver.MockWebServer;
import okhttp3.mockwebserver.RecordedRequest;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

/** The transport half of step 12a task 3: bearer auth, retry with backoff, nothing silent. */
public class HttpTrackerSyncClientTest
{
	private MockWebServer server;
	private final List<SyncStatus> published = new ArrayList<>();

	@Before
	public void setUp() throws Exception
	{
		server = new MockWebServer();
		server.start();
		published.clear();
	}

	@After
	public void tearDown() throws Exception
	{
		server.shutdown();
	}

	private HttpTrackerSyncClient clientFor(String url, String token)
	{
		final TrackerConfig config = new TestConfig(url, token);
		// A no-op sleeper: the backoff *policy* is asserted by counting attempts, and a test that
		// actually slept 1.5s to prove it would just be slower, not stronger.
		return new HttpTrackerSyncClient(new OkHttpClient(), new Gson(), config, published::add,
			millis -> { });
	}

	private static AccountSnapshot snapshot()
	{
		return AccountSnapshot.builder("zezima", Instant.parse("2026-08-11T20:15:00Z"))
			.combatLevel(126)
			.build();
	}

	private SyncStatus last()
	{
		return published.get(published.size() - 1);
	}

	@Test
	public void anAcceptedSyncSendsTheBearerTokenAndTheContractPath() throws Exception
	{
		server.enqueue(new MockResponse().setResponseCode(202));

		clientFor(server.url("/").toString(), "test-token-1234567890").submit(snapshot());

		final RecordedRequest request = server.takeRequest();
		assertEquals("/api/sync", request.getPath());
		assertEquals("Bearer test-token-1234567890", request.getHeader("Authorization"));
		assertTrue(request.getBody().readUtf8().contains("\"payload_version\":1"));
		assertEquals(SyncStatus.State.OK, last().state());
	}

	@Test
	public void aTrailingSlashInTheConfiguredUrlDoesNotDoubleUp() throws Exception
	{
		server.enqueue(new MockResponse().setResponseCode(202));

		clientFor(server.url("/").toString() + "/", "token").submit(snapshot());

		assertEquals("/api/sync", server.takeRequest().getPath());
	}

	@Test
	public void aRejectionIsNotRetriedAndIsSurfaced() throws Exception
	{
		// §11.3: the server audits an unauthenticated write. Retrying writes more audit rows for
		// the same mistake, so 401 is terminal.
		server.enqueue(new MockResponse().setResponseCode(401).setBody("{\"detail\":\"unauthorized\"}"));

		clientFor(server.url("/").toString(), "wrong-token").submit(snapshot());

		assertEquals(1, server.getRequestCount());
		assertEquals(SyncStatus.State.REJECTED, last().state());
		assertTrue(last().detail(), last().detail().contains("401"));
	}

	@Test
	public void anUnsupportedPayloadVersionIsAlsoTerminal() throws Exception
	{
		// §12.2 answers 409. The plugin cannot fix its own version by asking again.
		server.enqueue(new MockResponse().setResponseCode(409));

		clientFor(server.url("/").toString(), "token").submit(snapshot());

		assertEquals(1, server.getRequestCount());
		assertEquals(SyncStatus.State.REJECTED, last().state());
	}

	@Test
	public void aServerErrorIsRetriedWithBackoffAndThenSurfaced() throws Exception
	{
		for (int i = 0; i < HttpTrackerSyncClient.MAX_ATTEMPTS; i++)
		{
			server.enqueue(new MockResponse().setResponseCode(503));
		}

		clientFor(server.url("/").toString(), "token").submit(snapshot());

		assertEquals(HttpTrackerSyncClient.MAX_ATTEMPTS, server.getRequestCount());
		assertEquals(SyncStatus.State.UNREACHABLE, last().state());
	}

	@Test
	public void aTransientFailureThatRecoversIsReportedAsSuccess() throws Exception
	{
		server.enqueue(new MockResponse().setResponseCode(503));
		server.enqueue(new MockResponse().setResponseCode(202));

		clientFor(server.url("/").toString(), "token").submit(snapshot());

		assertEquals(2, server.getRequestCount());
		assertEquals(SyncStatus.State.OK, last().state());
	}

	@Test
	public void anUnreachableServerIsSurfacedRatherThanSwallowed() throws Exception
	{
		final String url = server.url("/").toString();
		server.shutdown();

		clientFor(url, "token").submit(snapshot());

		assertEquals(SyncStatus.State.UNREACHABLE, last().state());
	}

	@Test
	public void aMissingTokenIsRefusedLocallyAndExplained()
	{
		clientFor(server.url("/").toString(), "   ").submit(snapshot());

		assertEquals(0, server.getRequestCount());
		assertEquals(SyncStatus.State.NOT_CONFIGURED, last().state());
		assertTrue(last().detail(), last().detail().toLowerCase().contains("token"));
	}

	@Test
	public void anUnparseableServerUrlIsRefusedLocallyAndExplained()
	{
		clientFor("not a url", "token").submit(snapshot());

		assertEquals(0, server.getRequestCount());
		assertEquals(SyncStatus.State.NOT_CONFIGURED, last().state());
	}

	/** A hand-written config; RuneLite's own is an interface with defaults, so this is enough. */
	private static final class TestConfig implements TrackerConfig
	{
		private final String url;
		private final String token;

		private TestConfig(String url, String token)
		{
			this.url = url;
			this.token = token;
		}

		@Override
		public String serverUrl()
		{
			return url;
		}

		@Override
		public String apiToken()
		{
			return token;
		}
	}
}
