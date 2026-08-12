package com.osrstracker.plugin;

import com.google.gson.Gson;
import lombok.extern.slf4j.Slf4j;
import okhttp3.HttpUrl;
import okhttp3.MediaType;
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.RequestBody;
import okhttp3.Response;
import okhttp3.ResponseBody;

import java.io.IOException;
import java.time.Instant;
import java.util.function.Consumer;

/**
 * POSTs a snapshot to {@code /api/sync} with a bearer token (§11.2, §12.1).
 *
 * <p>Retries only what retrying can fix. §11.3 makes an unauthenticated write an audited
 * rejection on the server, and §12.2 makes an unknown {@code payload_version} a 409 — repeating
 * either just writes more audit rows for the same mistake. So 4xx is terminal and only transport
 * failures and 5xx back off and retry.
 */
@Slf4j
public final class HttpTrackerSyncClient implements TrackerSyncClient
{
	private static final MediaType JSON = MediaType.parse("application/json; charset=utf-8");
	private static final String SYNC_PATH = "api/sync";

	/** Three attempts over ~3s. The client is on the same machine; long retries help nobody. */
	static final int MAX_ATTEMPTS = 3;
	static final long BASE_BACKOFF_MILLIS = 500L;

	private final OkHttpClient httpClient;
	private final Gson gson;
	private final TrackerConfig config;
	private final Consumer<SyncStatus> statusSink;
	private final Sleeper sleeper;

	/** Injected so the retry test does not spend real seconds asleep. */
	interface Sleeper
	{
		void sleep(long millis) throws InterruptedException;
	}

	public HttpTrackerSyncClient(OkHttpClient httpClient, Gson gson, TrackerConfig config,
		Consumer<SyncStatus> statusSink)
	{
		this(httpClient, gson, config, statusSink, Thread::sleep);
	}

	HttpTrackerSyncClient(OkHttpClient httpClient, Gson gson, TrackerConfig config,
		Consumer<SyncStatus> statusSink, Sleeper sleeper)
	{
		this.httpClient = httpClient;
		this.gson = gson;
		this.config = config;
		this.statusSink = statusSink;
		this.sleeper = sleeper;
	}

	@Override
	public void submit(AccountSnapshot snapshot)
	{
		final HttpUrl url = syncUrl();
		if (url == null)
		{
			publish(SyncStatus.notConfigured("Set a valid server URL in the plugin settings."));
			return;
		}
		final String token = config.apiToken();
		if (token == null || token.trim().isEmpty())
		{
			// §11.2: the server would answer 401 and audit it. Refusing locally is both kinder
			// and quieter, and the user gets a message that names the actual problem.
			publish(SyncStatus.notConfigured("Set the API token in the plugin settings."));
			return;
		}

		final String body = gson.toJson(snapshot.toJson());
		publish(SyncStatus.sending(Instant.now()));

		for (int attempt = 1; attempt <= MAX_ATTEMPTS; attempt++)
		{
			final Request request = new Request.Builder()
				.url(url)
				.header("Authorization", "Bearer " + token.trim())
				.post(RequestBody.create(JSON, body))
				.build();

			try (Response response = httpClient.newCall(request).execute())
			{
				if (response.isSuccessful())
				{
					publish(SyncStatus.ok(Instant.now()));
					return;
				}
				if (response.code() < 500)
				{
					// Terminal: a bad token or an unsupported payload_version will be just as bad
					// on the next attempt (§11.3, §12.2).
					publish(SyncStatus.rejected(response.code(), describe(response), Instant.now()));
					return;
				}
				log.warn("sync attempt {}/{} failed with HTTP {}", attempt, MAX_ATTEMPTS, response.code());
				if (attempt == MAX_ATTEMPTS)
				{
					publish(SyncStatus.unreachable("HTTP " + response.code(), Instant.now()));
					return;
				}
			}
			catch (IOException e)
			{
				log.warn("sync attempt {}/{} could not reach {}", attempt, MAX_ATTEMPTS, url, e);
				if (attempt == MAX_ATTEMPTS)
				{
					publish(SyncStatus.unreachable(String.valueOf(e.getMessage()), Instant.now()));
					return;
				}
			}

			if (!backOff(attempt))
			{
				publish(SyncStatus.unreachable("Interrupted while retrying.", Instant.now()));
				return;
			}
		}
	}

	/** @return false if the wait was interrupted, which ends the attempt sequence. */
	private boolean backOff(int attempt)
	{
		try
		{
			sleeper.sleep(BASE_BACKOFF_MILLIS * (1L << (attempt - 1)));
			return true;
		}
		catch (InterruptedException e)
		{
			Thread.currentThread().interrupt();
			return false;
		}
	}

	private HttpUrl syncUrl()
	{
		final String configured = config.serverUrl();
		if (configured == null || configured.trim().isEmpty())
		{
			return null;
		}
		// Trailing slashes are what a user pastes out of a browser bar. Left alone they become
		// an empty path segment and the request goes to `//api/sync`, which the router does not
		// serve — a 404 that looks like a server problem and is not.
		String trimmed = configured.trim();
		while (trimmed.endsWith("/"))
		{
			trimmed = trimmed.substring(0, trimmed.length() - 1);
		}
		final HttpUrl base = HttpUrl.parse(trimmed);
		return base == null ? null : base.newBuilder().addPathSegments(SYNC_PATH).build();
	}

	/** A short, safe rendering of a rejection — enough to act on, not a wall of HTML. */
	private static String describe(Response response)
	{
		try
		{
			final ResponseBody body = response.body();
			if (body == null)
			{
				return response.message();
			}
			final String text = body.string().trim();
			if (text.isEmpty())
			{
				return response.message();
			}
			return text.length() > 200 ? text.substring(0, 200) + "…" : text;
		}
		catch (IOException e)
		{
			return response.message();
		}
	}

	private void publish(SyncStatus status)
	{
		if (status.isFailure())
		{
			log.warn("sync: {}", status.detail());
		}
		statusSink.accept(status);
	}
}
