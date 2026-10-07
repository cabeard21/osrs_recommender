package com.osrstracker.plugin;

import org.slf4j.LoggerFactory;

/** Checks the actual developer-client classpath without opening a game client. */
public final class RuneLiteRuntimeCheck
{
	private RuneLiteRuntimeCheck()
	{
	}

	public static void main(String[] args) throws ClassNotFoundException
	{
		String loggerFactory = LoggerFactory.getILoggerFactory().getClass().getName();
		if (!"ch.qos.logback.classic.LoggerContext".equals(loggerFactory))
		{
			throw new IllegalStateException("RuneLite logging is unavailable: " + loggerFactory);
		}
		ClassLoader loader = RuneLiteRuntimeCheck.class.getClassLoader();
		checkAssertions(loader, "net.runelite.client.externalplugins.ExternalPluginManager", true);
		checkAssertions(loader, "com.osrstracker.plugin.TrackerPlugin", true);
		checkAssertions(loader, "net.runelite.client.plugins.menuentryswapper.MenuEntrySwapperPlugin", false);
		checkAssertions(loader, "net.runelite.client.RuneLite", true);
		if (loader.getResource("com/networknt/schema/JsonSchema.class") != null
			|| loader.getResource("org/junit/Test.class") != null)
		{
			throw new IllegalStateException("Test-only dependencies leaked into the RuneLite client");
		}
		System.out.println("RuneLite launch runtime has working Logback, scoped assertions, and no test-only dependencies.");
	}

	private static void checkAssertions(ClassLoader loader, String className, boolean expected)
		throws ClassNotFoundException
	{
		if (Class.forName(className, false, loader).desiredAssertionStatus() != expected)
		{
			throw new IllegalStateException("Incorrect assertion setting for " + className);
		}
	}
}
