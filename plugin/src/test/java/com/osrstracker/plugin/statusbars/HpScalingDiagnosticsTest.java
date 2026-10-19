package com.osrstracker.plugin.statusbars;

import com.osrstracker.plugin.TrackerConfig;
import java.util.ArrayList;
import java.util.List;
import net.runelite.api.*;
import org.junit.Test;
import static org.junit.Assert.*;
import static org.mockito.Mockito.*;

public class HpScalingDiagnosticsTest
{
    @Test public void optInSnapshotsIgnoreOrdinaryHpChangesButRefreshOnStateChange()
    {
        Client client=mock(Client.class);TrackerConfig config=mock(TrackerConfig.class);
        List<String> snapshots=new ArrayList<>();
        HpScalingDiagnostics diagnostics=new HpScalingDiagnostics(client,config,
            new EffectiveMaxHealthResolver(client,config),snapshots::add);
        diagnostics.tick(); assertTrue(snapshots.isEmpty());
        when(config.enhancedBarsEnabled()).thenReturn(true);
        diagnostics.tick(); assertTrue(snapshots.isEmpty());
        when(config.hpScalingDiagnostics()).thenReturn(true);
        when(client.getGameState()).thenReturn(GameState.LOGIN_SCREEN);
        diagnostics.tick();diagnostics.tick();assertEquals(1,snapshots.size());
        Player player=mock(Player.class);
        when(client.getGameState()).thenReturn(GameState.LOGGED_IN);
        when(client.getLocalPlayer()).thenReturn(player);
        when(client.getBoostedSkillLevel(Skill.HITPOINTS)).thenReturn(54);
        when(client.getRealSkillLevel(Skill.HITPOINTS)).thenReturn(54);
        diagnostics.tick();assertEquals(2,snapshots.size());
        assertTrue(snapshots.get(1).contains("current=54"));
        when(client.getBoostedSkillLevel(Skill.HITPOINTS)).thenReturn(30);
        diagnostics.tick();assertEquals(2,snapshots.size());
        when(config.manualHpMaximumEnabled()).thenReturn(true);
        when(config.manualHpMaximum()).thenReturn(99);
        diagnostics.tick();assertEquals(3,snapshots.size());
        assertTrue(snapshots.get(2).contains("MANUAL"));
        when(config.hpScalingDiagnostics()).thenReturn(false);
        diagnostics.tick();when(config.hpScalingDiagnostics()).thenReturn(true);
        diagnostics.tick();assertEquals(4,snapshots.size());
        diagnostics.reset();diagnostics.tick();assertEquals(5,snapshots.size());
    }
}
