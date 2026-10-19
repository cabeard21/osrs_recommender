package com.osrstracker.plugin;

import com.osrstracker.plugin.statusbars.EnhancedStatusBarsOverlay;
import com.osrstracker.plugin.statusbars.EffectiveMaxHealthResolver;
import net.runelite.api.Client;
import com.osrstracker.plugin.statusbars.HpScalingDiagnostics;
import java.lang.reflect.Field;
import java.util.Collections;
import java.util.ArrayList;
import java.util.List;
import net.runelite.client.events.ConfigChanged;
import java.util.concurrent.atomic.AtomicReference;
import javax.swing.JLabel;
import javax.swing.SwingUtilities;
import net.runelite.client.callback.ClientThread;
import net.runelite.client.plugins.PluginManager;
import net.runelite.client.plugins.statusbars.StatusBarsPlugin;
import net.runelite.client.ui.ClientToolbar;
import net.runelite.client.ui.overlay.OverlayManager;
import org.junit.Test;
import static org.junit.Assert.*;
import static org.mockito.Mockito.*;

public class EnhancedBarsLifecycleTest
{
	@Test
	public void defaultsPreserveDisplay()
	{
		TrackerConfig config = new TrackerConfig() {};
		assertFalse(config.enhancedBarsEnabled());
		assertTrue(config.automaticHpScaling());
		assertFalse(config.manualHpMaximumEnabled());
		assertEquals(99, config.manualHpMaximum());
		assertEquals(20, config.sharkHealing());
		assertEquals(35, config.doubleEatHealing());
		assertEquals(56, config.tripleEatHealing());
	}

	@Test
	public void lifecycleIsIdempotentAndConflictDoesNotDisableBuiltin() throws Exception
	{
		TrackerPlugin plugin = new TrackerPlugin();
		TrackerConfig config = mock(TrackerConfig.class);
		OverlayManager manager = mock(OverlayManager.class);
		EnhancedStatusBarsOverlay overlay = new EnhancedStatusBarsOverlay(mock(Client.class), config, null, null, null);
		PluginManager plugins = mock(PluginManager.class);
		StatusBarsPlugin builtin = mock(StatusBarsPlugin.class);
		set(plugin, "config", config);
		set(plugin, "overlayManager", manager);
		set(plugin, "enhancedStatusBarsOverlay", overlay);
		set(plugin, "pluginManager", plugins);
		when(config.enhancedBarsEnabled()).thenReturn(true);
		when(plugins.getPlugins()).thenReturn(Collections.singletonList(builtin));
		when(plugins.isPluginActive(builtin)).thenReturn(true);
		plugin.reconcileEnhancedBars();
		plugin.reconcileEnhancedBars();
		verify(manager, times(1)).add(overlay);
		assertEquals(true, get(overlay, "suppressed"));
		when(plugins.isPluginActive(builtin)).thenReturn(false);
		plugin.reconcileEnhancedBars();
		assertEquals(false, get(overlay, "suppressed"));
		when(config.enhancedBarsEnabled()).thenReturn(false);
		plugin.reconcileEnhancedBars();
		plugin.reconcileEnhancedBars();
		verify(manager, times(1)).remove(overlay);
		verify(plugins, never()).setPluginEnabled(any(), anyBoolean());
	}

	@Test
	public void stoppedLifecycleCannotRestoreOverlay() throws Exception
	{
		TrackerPlugin plugin = new TrackerPlugin();
		ClientThread thread = mock(ClientThread.class);
		TrackerConfig config = mock(TrackerConfig.class);
		OverlayManager manager = mock(OverlayManager.class);
		EnhancedStatusBarsOverlay overlay = new EnhancedStatusBarsOverlay(mock(Client.class), config, null, null, null);
		Client client = mock(Client.class);
		HpScalingDiagnostics diagnostics = new HpScalingDiagnostics(client, config, new EffectiveMaxHealthResolver(client, config));
		set(diagnostics, "lastSignature", "old lifecycle" );
		AtomicReference<Runnable> queued = new AtomicReference<>();
		doAnswer(call -> { queued.set(call.getArgument(0)); return null; })
			.when(thread).invokeLater(any(Runnable.class));
		set(plugin, "clientThread", thread);
		set(plugin, "overlayManager", manager);
		set(plugin, "enhancedStatusBarsOverlay", overlay);
		set(plugin, "hpScalingDiagnostics", diagnostics);
		set(plugin, "clientToolbar", mock(ClientToolbar.class));
		set(plugin, "active", true);
		plugin.onProfileChanged(null);
		assertNotNull(queued.get());
		plugin.shutDown();
		queued.get().run();
		verify(manager).remove(overlay);
		verify(manager, never()).add(overlay);
		assertNull(get(diagnostics, "lastSignature"));
		verifyNoInteractions(client);
	}

	@Test
	public void sidebarWarningPreservesSyncStatus() throws Exception
	{
		AtomicReference<TrackerPanel> ref = new AtomicReference<>();
		SwingUtilities.invokeAndWait(() -> ref.set(new TrackerPanel(() -> {})));
		TrackerPanel panel = ref.get();
		panel.update(SyncStatus.unreachable("Backend unavailable", null));
		panel.updateBarsWarning(true);
		SwingUtilities.invokeAndWait(() -> {});
		assertEquals("Unreachable", ((JLabel) get(panel, "stateLabel")).getText());
		assertTrue(((JLabel) get(panel, "barsWarning")).isVisible());
		panel.updateBarsWarning(false);
		SwingUtilities.invokeAndWait(() -> {});
		assertFalse(((JLabel) get(panel, "barsWarning")).isVisible());
		assertEquals("Unreachable", ((JLabel) get(panel, "stateLabel")).getText());
	}

	@Test
	public void startupDisabledAndReloadDoNotCreateDuplicateOverlays() throws Exception
	{
		LifecycleFixture fixture = new LifecycleFixture();
		fixture.plugin.startUp();
		fixture.callbacks.get(0).run();
		verify(fixture.manager, never()).add(fixture.overlay);
		assertNotNull(get(fixture.plugin, "syncClient"));
		assertNotNull(get(fixture.plugin, "panel"));
		fixture.plugin.shutDown();
		when(fixture.config.enhancedBarsEnabled()).thenReturn(true);
		fixture.plugin.startUp();
		fixture.callbacks.get(1).run();
		fixture.plugin.onProfileChanged(null);
		fixture.callbacks.get(2).run();
		verify(fixture.manager, times(1)).add(fixture.overlay);
		fixture.plugin.shutDown();
		verify(fixture.manager, times(2)).remove(fixture.overlay);
	}

	@Test
	public void configurationEventsAreGroupFilteredAndProfileChangesReconcile() throws Exception
	{
		LifecycleFixture fixture = new LifecycleFixture();
		fixture.plugin.startUp();
		fixture.callbacks.get(0).run();
		ConfigChanged event = new ConfigChanged();
		event.setGroup("unrelated");
		fixture.plugin.onConfigChanged(event);
		assertEquals(1, fixture.callbacks.size());
		event.setGroup(TrackerConfig.GROUP);
		when(fixture.config.enhancedBarsEnabled()).thenReturn(true);
		fixture.plugin.onConfigChanged(event);
		fixture.callbacks.get(1).run();
		verify(fixture.manager).add(fixture.overlay);
		when(fixture.config.enhancedBarsEnabled()).thenReturn(false);
		fixture.plugin.onProfileChanged(null);
		fixture.callbacks.get(2).run();
		verify(fixture.manager).remove(fixture.overlay);
		fixture.plugin.shutDown();
	}

	@Test
	public void callbacksFromPreviousGenerationAreIgnoredAfterRestart() throws Exception
	{
		LifecycleFixture fixture = new LifecycleFixture();
		when(fixture.config.enhancedBarsEnabled()).thenReturn(true);
		fixture.plugin.startUp();
		Runnable stale = fixture.callbacks.get(0);
		fixture.plugin.shutDown();
		fixture.plugin.startUp();
		stale.run();
		verify(fixture.manager, never()).add(fixture.overlay);
		fixture.callbacks.get(1).run();
		verify(fixture.manager).add(fixture.overlay);
		fixture.plugin.shutDown();
	}

	private static final class LifecycleFixture
	{
		final TrackerPlugin plugin = new TrackerPlugin();
		final TrackerConfig config = mock(TrackerConfig.class);
		final OverlayManager manager = mock(OverlayManager.class);
		final EnhancedStatusBarsOverlay overlay;
		final List<Runnable> callbacks = new ArrayList<>();

		LifecycleFixture() throws Exception
		{
			Client client = mock(Client.class);
			ClientThread thread = mock(ClientThread.class);
			PluginManager plugins = mock(PluginManager.class);
			when(plugins.getPlugins()).thenReturn(Collections.emptyList());
			doAnswer(call -> { callbacks.add(call.getArgument(0)); return null; })
				.when(thread).invokeLater(any(Runnable.class));
			overlay = new EnhancedStatusBarsOverlay(client, config, null, null, null);
			set(plugin, "config", config);
			set(plugin, "client", client);
			set(plugin, "clientThread", thread);
			set(plugin, "clientToolbar", mock(ClientToolbar.class));
			set(plugin, "pluginManager", plugins);
			set(plugin, "overlayManager", manager);
			set(plugin, "enhancedStatusBarsOverlay", overlay);
			set(plugin, "hpScalingDiagnostics", new HpScalingDiagnostics(client, config,
				new EffectiveMaxHealthResolver(client, config)));
		}
	}
	@Test
	public void inFlightRegistrationCannotOutliveShutdown() throws Exception
	{
		TrackerPlugin plugin=new TrackerPlugin();
		TrackerConfig config=mock(TrackerConfig.class);
		Client client=mock(Client.class);
		ClientThread thread=mock(ClientThread.class);
		OverlayManager manager=mock(OverlayManager.class);
		EnhancedStatusBarsOverlay overlay=new EnhancedStatusBarsOverlay(client,config,null,null,null);
		PluginManager plugins=mock(PluginManager.class);
		set(plugin,"config",config);set(plugin,"clientThread",thread);
		set(plugin,"overlayManager",manager);set(plugin,"enhancedStatusBarsOverlay",overlay);
		set(plugin,"pluginManager",plugins);set(plugin,"clientToolbar",mock(ClientToolbar.class));
		set(plugin,"hpScalingDiagnostics",new HpScalingDiagnostics(client,config,new EffectiveMaxHealthResolver(client,config)));
		set(plugin,"active",true);
		when(config.enhancedBarsEnabled()).thenReturn(true);
		when(plugins.getPlugins()).thenReturn(Collections.emptyList());
		AtomicReference<Runnable> callback=new AtomicReference<>();
		doAnswer(call -> { callback.set(call.getArgument(0));return null; }).when(thread).invokeLater(any(Runnable.class));
		plugin.onProfileChanged(null);
		java.util.concurrent.CountDownLatch entered=new java.util.concurrent.CountDownLatch(1);
		java.util.concurrent.CountDownLatch release=new java.util.concurrent.CountDownLatch(1);
		doAnswer(call -> { entered.countDown();assertTrue(release.await(5,java.util.concurrent.TimeUnit.SECONDS));return true; })
			.when(manager).add(overlay);
		AtomicReference<Throwable> failure=new AtomicReference<>();
		Thread reconcile=new Thread(() -> { try { callback.get().run(); } catch(Throwable e) { failure.set(e); } });
		Thread stop=new Thread(() -> { try { plugin.shutDown(); } catch(Throwable e) { failure.set(e); } });
		reconcile.start();assertTrue(entered.await(5,java.util.concurrent.TimeUnit.SECONDS));
		stop.start();
		// On the old implementation shutdown completes while add is blocked. With the fix it
		// waits on the lifecycle lock. Wait for either outcome before releasing registration.
		long deadline=System.nanoTime()+java.util.concurrent.TimeUnit.SECONDS.toNanos(5);
		while(stop.isAlive() && stop.getState()!=Thread.State.BLOCKED && System.nanoTime()<deadline)
			Thread.yield();
		release.countDown();reconcile.join(5000);stop.join(5000);
		assertFalse(reconcile.isAlive());assertFalse(stop.isAlive());assertNull(failure.get());
		assertEquals(false,get(plugin,"enhancedBarsRegistered"));
		org.mockito.InOrder order=inOrder(manager);order.verify(manager).add(overlay);order.verify(manager).remove(overlay);
	}

	private static Object get(Object target, String name) throws Exception
	{
		Field field = target.getClass().getDeclaredField(name);
		field.setAccessible(true);
		return field.get(target);
	}

	private static void set(Object target, String name, Object value) throws Exception
	{
		Field field = target.getClass().getDeclaredField(name);
		field.setAccessible(true);
		field.set(target, value);
	}
}
