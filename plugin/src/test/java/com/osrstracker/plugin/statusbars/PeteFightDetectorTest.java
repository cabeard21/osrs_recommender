package com.osrstracker.plugin.statusbars;

import com.osrstracker.plugin.TrackerConfig;
import net.runelite.api.*;
import net.runelite.api.coords.*;
import org.junit.Test;
import java.util.Arrays;
import java.util.Collections;
import static org.junit.Assert.*;
import static org.mockito.Mockito.*;

public class PeteFightDetectorTest
{
    @Test public void sourceBackedArenaAndFormsAreNarrow()
    {
        WorldPoint arena = new WorldPoint(2783,5920,0);
        for(int id=16579;id<=16597;id++)
            assertEquals(id!=16587,PeteFightDetector.matches(arena,id));
        for(int id:new int[]{-1,16576,16577,16578,16587,16598,16607})
            assertFalse(PeteFightDetector.matches(arena,id));
        assertFalse(PeteFightDetector.matches(new WorldPoint(2783,5920,1),16579));
        assertFalse(PeteFightDetector.matches(new WorldPoint(2816,5920,0),16579));
        assertFalse(PeteFightDetector.matches(null,16579));
    }

    @Test public void loadedCombatFormsNeedNoAttackInteraction()
    {
        Client c=mock(Client.class);Player p=mock(Player.class);NPC pete=mock(NPC.class);
        when(c.getGameState()).thenReturn(GameState.LOGGED_IN);
        when(c.getLocalPlayer()).thenReturn(p);
        WorldView view=mock(WorldView.class);
        when(c.getWorldView(anyInt())).thenReturn(view);when(c.getTopLevelWorldView()).thenReturn(view);
        when(view.getBaseX()).thenReturn(2752);when(view.getBaseY()).thenReturn(5888);
        when(p.getLocalLocation()).thenReturn(new LocalPoint(31*128+64,32*128+64));
        when(c.getNpcs()).thenReturn(Arrays.asList(null,pete));
        when(pete.getId()).thenReturn(16579,16582,16597);
        assertTrue(PeteFightDetector.isFight(c));
        assertTrue(PeteFightDetector.isFight(c));
        assertTrue(PeteFightDetector.isFight(c));
        when(view.isInstance()).thenReturn(true);
        int[][][] chunks=new int[4][13][13];
        chunks[0][3][4]=(344 << 14) | (736 << 3);
        when(view.getInstanceTemplateChunks()).thenReturn(chunks);
        assertTrue(PeteFightDetector.isFight(c));
        when(view.getInstanceTemplateChunks()).thenReturn(null);
        assertFalse(PeteFightDetector.isFight(c));
        when(view.isInstance()).thenReturn(false);
        verify(pete,never()).getInteracting();
        when(c.getNpcs()).thenReturn(Collections.emptyList());
        assertFalse(PeteFightDetector.isFight(c));
        when(c.getNpcs()).thenReturn(null);
        assertFalse(PeteFightDetector.isFight(c));
    }

    @Test public void unavailableStateAndOutsideArenaDoNotRecognizeFight()
    {
        Client c=mock(Client.class);
        assertFalse(PeteFightDetector.isFight(c));
        when(c.getGameState()).thenReturn(GameState.LOGGED_IN);
        assertFalse(PeteFightDetector.isFight(c));
        Player p=mock(Player.class);when(c.getLocalPlayer()).thenReturn(p);
        assertFalse(PeteFightDetector.isFight(c));
        when(p.getLocalLocation()).thenReturn(new LocalPoint(64,64));
        assertFalse(PeteFightDetector.isFight(c));
        verify(c,never()).getNpcs();
    }

    @Test public void resolverReadsFreshStatsAndLmsWidgetWithoutBackend()
    {
        Client c=mock(Client.class);Player p=mock(Player.class);
        TrackerConfig config=mock(TrackerConfig.class);
        when(config.automaticHpScaling()).thenReturn(true);
        EffectiveMaxHealthResolver resolver=new EffectiveMaxHealthResolver(c,config);
        assertFalse(resolver.resolve().isAvailable());
        when(c.getGameState()).thenReturn(GameState.LOGGED_IN);
        assertFalse(resolver.resolve().isAvailable());
        when(c.getLocalPlayer()).thenReturn(p);
        when(c.getRealSkillLevel(Skill.HITPOINTS)).thenReturn(54);
        when(c.getBoostedSkillLevel(Skill.HITPOINTS)).thenReturn(30,54,120);
        assertEquals(30,resolver.resolve().current());
        net.runelite.api.widgets.Widget lms=mock(net.runelite.api.widgets.Widget.class);
        when(c.getWidget(net.runelite.api.gameval.InterfaceID.BrOverlay.CONTENT)).thenReturn(lms);
        assertEquals(99,resolver.resolve().maximum());
        assertEquals(120,resolver.resolve().current());
        when(c.getWidget(net.runelite.api.gameval.InterfaceID.BrOverlay.CONTENT)).thenReturn(null);
        assertEquals(54,resolver.resolve().maximum());
        when(c.getGameState()).thenReturn(GameState.LOGIN_SCREEN);
        assertFalse(resolver.resolve().isAvailable());
    }
}
