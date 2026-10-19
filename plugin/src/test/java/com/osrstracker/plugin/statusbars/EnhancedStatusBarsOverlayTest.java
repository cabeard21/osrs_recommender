package com.osrstracker.plugin.statusbars;

import com.osrstracker.plugin.TrackerConfig;
import java.awt.Color;
import java.awt.Graphics2D;
import java.awt.image.BufferedImage;
import net.runelite.api.Client;
import net.runelite.api.GameState;
import net.runelite.api.Player;
import net.runelite.api.Point;
import net.runelite.api.Prayer;
import net.runelite.api.Skill;
import net.runelite.api.gameval.InterfaceID;
import net.runelite.api.gameval.VarPlayerID;
import net.runelite.api.gameval.VarbitID;
import net.runelite.api.widgets.Widget;
import net.runelite.client.game.SkillIconManager;
import net.runelite.client.game.SpriteManager;
import org.junit.Before;
import org.junit.Test;
import static org.junit.Assert.*;
import static org.mockito.Mockito.*;

public class EnhancedStatusBarsOverlayTest
{
    private Client client;
    private TrackerConfig config;
    private EnhancedStatusBarsOverlay overlay;
    private SkillIconManager icons;
    private SpriteManager sprites;
    private Widget widget;

    @Before public void setup()
    {
        client = mock(Client.class);
        config = mock(TrackerConfig.class);
        icons = mock(SkillIconManager.class);
        sprites = mock(SpriteManager.class);
        widget = mock(Widget.class);
        when(client.getGameState()).thenReturn(GameState.LOGGED_IN);
        when(client.getLocalPlayer()).thenReturn(mock(Player.class));
        when(client.getRealSkillLevel(Skill.HITPOINTS)).thenReturn(54);
        when(client.getBoostedSkillLevel(Skill.HITPOINTS)).thenReturn(54);
        when(client.getRealSkillLevel(Skill.PRAYER)).thenReturn(54);
        when(client.getBoostedSkillLevel(Skill.PRAYER)).thenReturn(54);
        when(config.enhancedBarsEnabled()).thenReturn(true);
        when(widget.getCanvasLocation()).thenReturn(new Point(100, 10));
        when(widget.getWidth()).thenReturn(190);
        overlay = new EnhancedStatusBarsOverlay(client, config,
            new EffectiveMaxHealthResolver(client, config), icons, sprites);
    }

    private BufferedImage render()
    {
        BufferedImage result = new BufferedImage(500, 400, BufferedImage.TYPE_INT_ARGB);
        Graphics2D graphics = result.createGraphics();
        overlay.render(graphics);
        graphics.dispose();
        return result;
    }

    @Test public void allViewportAnchorsDrawCorrectly()
    {
        for (StatusBarsViewport viewport : StatusBarsViewport.values())
        {
            reset(client);
            when(client.getGameState()).thenReturn(GameState.LOGGED_IN);
            when(client.getLocalPlayer()).thenReturn(mock(Player.class));
            when(client.getRealSkillLevel(Skill.HITPOINTS)).thenReturn(54);
            when(client.getBoostedSkillLevel(Skill.HITPOINTS)).thenReturn(54);
            when(client.getRealSkillLevel(Skill.PRAYER)).thenReturn(54);
            when(client.getBoostedSkillLevel(Skill.PRAYER)).thenReturn(54);
            when(client.getWidget(viewport.getViewport())).thenReturn(widget);
            BufferedImage image = render();
            int left = viewport == StatusBarsViewport.RESIZED_BOTTOM ? 49 : 80;
            int right = viewport == StatusBarsViewport.RESIZED_BOTTOM ? 75 : 290;
            assertNotEquals(0, image.getRGB(left + 5, 100));
            assertNotEquals(0, image.getRGB(right + 5, 100));
        }
    }

    @Test public void suppressedDisabledLoggedOutAndMissingViewportDrawNothing()
    {
        when(client.getWidget(StatusBarsViewport.FIXED.getViewport())).thenReturn(widget);
        overlay.setSuppressed(true);
        assertEquals(0, render().getRGB(85, 100));
        overlay.setSuppressed(false);
        when(config.enhancedBarsEnabled()).thenReturn(false);
        assertEquals(0, render().getRGB(85, 100));
        when(config.enhancedBarsEnabled()).thenReturn(true);
        when(client.getGameState()).thenReturn(GameState.LOGIN_SCREEN);
        assertEquals(0, render().getRGB(85, 100));
        when(client.getGameState()).thenReturn(GameState.LOGGED_IN);
        when(widget.isHidden()).thenReturn(true);
        assertEquals(0, render().getRGB(85, 100));
        when(widget.isHidden()).thenReturn(false);
        when(widget.getCanvasLocation()).thenReturn(null);
        assertEquals(0, render().getRGB(85, 100));
    }

    @Test public void missingLocalPlayerHidesBothBars()
    {
        when(client.getWidget(StatusBarsViewport.FIXED.getViewport())).thenReturn(widget);
        when(client.getLocalPlayer()).thenReturn(null);
        BufferedImage image=render();
        assertEquals(0,image.getRGB(85,100));
        assertEquals(0,image.getRGB(295,100));
    }

    @Test public void currentHpAndMarkersUseFreshMaximumAndPrayerStaysIndependent()
    {
        when(client.getWidget(StatusBarsViewport.FIXED.getViewport())).thenReturn(widget);
        when(config.manualHpMaximumEnabled()).thenReturn(true);
        when(config.manualHpMaximum()).thenReturn(99);
        when(config.eatingThresholdsEnabled()).thenReturn(true);
        when(config.sharkThresholdEnabled()).thenReturn(true);
        when(config.sharkHealing()).thenReturn(20);
        when(config.sharkMarkerColor()).thenReturn(Color.YELLOW);
        BufferedImage image = render();
        int marker = EatingThresholds.calculate(99, 20, 15, 250).getAsInt();
        assertEquals(Color.YELLOW.getRGB(), image.getRGB(85, marker));
        assertNotEquals(0, image.getRGB(295, 20));
        when(config.sharkHealing()).thenReturn(99);
        assertNotEquals(Color.YELLOW.getRGB(), render().getRGB(85, marker));
        when(config.sharkThresholdEnabled()).thenReturn(false);
        when(config.doubleEatThresholdEnabled()).thenReturn(true);
        when(config.doubleEatHealing()).thenReturn(35);
        when(config.doubleEatMarkerColor()).thenReturn(Color.CYAN);
        when(config.tripleEatThresholdEnabled()).thenReturn(true);
        when(config.tripleEatHealing()).thenReturn(56);
        when(config.tripleEatMarkerColor()).thenReturn(Color.MAGENTA);
        image = render();
        assertEquals(Color.CYAN.getRGB(), image.getRGB(85, EatingThresholds.calculate(99,35,15,250).getAsInt()));
        assertEquals(Color.MAGENTA.getRGB(), image.getRGB(85,EatingThresholds.calculate(99,56,15,250).getAsInt()));
    }

    @Test public void unavailableHpDoesNotPreventValidPrayer()
    {
        when(client.getWidget(StatusBarsViewport.FIXED.getViewport())).thenReturn(widget);
        when(client.getRealSkillLevel(Skill.HITPOINTS)).thenReturn(0);
        assertEquals(0, render().getRGB(85, 100));
        assertNotEquals(0, render().getRGB(295, 100));
        when(client.getBoostedSkillLevel(Skill.PRAYER)).thenReturn(-1);
        assertEquals(0, render().getRGB(295, 100));
    }

    @Test public void statusColorsAndIconsAreIndependentOfMaximum()
    {
        when(client.getWidget(StatusBarsViewport.FIXED.getViewport())).thenReturn(widget);
        when(config.statusBarsIcons()).thenReturn(true);
        when(config.statusBarsCounters()).thenReturn(true);
        for (int poison : new int[]{0, 10, 60, 1000000})
        {
            when(client.getVarpValue(VarPlayerID.POISON)).thenReturn(poison);
            assertNotEquals(0, render().getRGB(85, 100));
        }
        when(client.getVarpValue(VarPlayerID.POISON)).thenReturn(0);
        when(client.getVarpValue(VarPlayerID.DISEASE)).thenReturn(1);
        render();
        when(client.getVarpValue(VarPlayerID.DISEASE)).thenReturn(0);
        when(client.getVarbitValue(VarbitID.PARASITE)).thenReturn(1);
        render();
        when(client.isPrayerActive(Prayer.THICK_SKIN)).thenReturn(true);
        render();
        when(client.getWidget(InterfaceID.BrOverlay.CONTENT)).thenReturn(mock(Widget.class));
        render();
        verify(icons, atLeastOnce()).getSkillImage(Skill.PRAYER, true);
        verify(sprites, atLeastOnce()).getSprite(anyInt(), eq(0));
    }
}
